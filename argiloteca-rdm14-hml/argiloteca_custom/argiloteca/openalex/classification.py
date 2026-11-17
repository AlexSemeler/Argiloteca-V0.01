"""Explainable collection routing using the existing vocabulary and mineral map.

This classifies bibliographic topics; it never infers samples, analyses or
scientific mineral identification from a paper or from an extraction term.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from html.parser import HTMLParser

from invenio_db import db

from .adapters import confined, digest, release
from ..mineralogia import normalize_lookup_key, resolve_group_community_slug, COMMUNITY_SLUG_BY_GROUP_KEY


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[]

    def handle_data(self,data):
        self.parts.append(data)


def plain(value):
    parser=TextOnly();parser.feed(str(value or ''))
    return normalize_lookup_key(' '.join(parser.parts)) or ''


def load_vocabulary(root):
    folder,version=release(root,'extractor')
    path=confined(folder/'runtime/argiloteca/app_data/data/vocabularies/argilominerais.jsonl',folder)
    content=path.read_bytes()
    rows=[json.loads(line) for line in content.decode().splitlines() if line.strip()]
    terms=[]
    for row in rows:
        props=row.get('props',{})
        if props.get('status') not in (None,'','preferred'):
            continue
        slug=resolve_group_community_slug(props.get('family'))
        aliases={normalize_lookup_key(v) for v in [row['id'],*row.get('title',{}).values()] if v}
        terms.append({'id':row['id'],'title':row.get('title',{}).get('pt',row['id']),
                      'family':props.get('family'),'slug':slug,'aliases':sorted(aliases)})
    return terms,{'version':'community-routing-v1','release':folder.name,
                  'release_sha256':version,'vocabulary_sha256':hashlib.sha256(content).hexdigest(),
                  'community_map_sha256':digest(COMMUNITY_SLUG_BY_GROUP_KEY)}


def community_catalog(identity):
    from invenio_communities.proxies import current_communities
    service=current_communities.service
    result={}
    for model in service.record_cls.model_cls.query.filter_by(deletion_status='P'):
        community=service.record_cls.get_record(model.id)
        if not service.check_permission(identity,'read',record=community):
            continue
        allowed=service.check_permission(identity,'submit_record',record=community) and service.check_permission(
            identity,'include_directly',record=community)
        result[model.slug]={'id':str(model.id),'slug':model.slug,
            'title':model.json.get('metadata',{}).get('title',model.slug),'allowed':bool(allowed)}
    return result


def classify(row, vocabulary, catalog, version):
    metadata=row['payload']['metadata']
    texts={'title':metadata.get('title',''),'description':metadata.get('description',''),
           'subjects':' '.join(s.get('subject','') for s in metadata.get('subjects',[]))}
    hits=[]
    for field,value in texts.items():
        text=plain(value);spans=[]
        for term in vocabulary:
            for alias in term['aliases']:
                if not alias:
                    continue
                for match in re.finditer(r'(?<![a-z0-9])'+re.escape(alias)+r'(?![a-z0-9])',text):
                    spans.append((match.start(),match.end(),term))
        accepted=[]
        # Specific mixed-layer names beat their contained generic constituents.
        for start,end,term in sorted(spans,key=lambda s:-(s[1]-s[0])):
            if any(start>=a and end<=b for a,b in accepted):
                continue
            accepted.append((start,end))
            hits.append({'term':term['id'],'label':term['title'],'family':term['family'],
                         'slug':term['slug'],'source':field})
    if not hits:
        aliases={alias:term for term in vocabulary for alias in term['aliases']}
        for origin in row.get('provenance',[]):
            data=origin.get('origin',{})
            term=aliases.get(normalize_lookup_key(data.get('termo_en'))) or aliases.get(normalize_lookup_key(data.get('termo_pt')))
            if term:
                hits.append({'term':term['id'],'label':term['title'],'family':term['family'],
                             'slug':term['slug'],'source':'extraction_term'})
    unique={digest(h):h for h in hits}
    hits=list(unique.values())
    destinations=[];unavailable=[]
    for slug in dict.fromkeys(h['slug'] for h in hits if h['slug']):
        destination=catalog.get(slug)
        if destination and destination['allowed']:
            destinations.append(deepcopy(destination))
        else:
            unavailable.append(slug)
    result={'rule':deepcopy(version),'evidence':hits,'communities':destinations,
            'unavailable':unavailable,'state':'classified' if destinations and not unavailable else 'needs_review'}
    result['sha256']=digest(result)
    return result


def classify_snapshot(root,snapshot,identity,context=None):
    if context is None:
        vocabulary,version=load_vocabulary(root)
        catalog=community_catalog(identity)
    else:
        vocabulary,version,catalog=context
    for row in snapshot['records']:
        row['classification']=classify(row,vocabulary,catalog,version)
        if row['classification']['state']=='needs_review':
            row['issues'].append({'severity':'warning','code':'community_classification','path':'communities',
                'message':'Sem comunidade confirmada para todos os termos. Confira a classificação temática antes de importar.'})
            if row['status']=='apto':
                row['status']='apto_com_alertas'
    snapshot['classification']={'rule':version,'classified':sum(
        bool(r['classification']['communities']) for r in snapshot['records']),
        'needs_review':sum(r['classification']['state']=='needs_review' for r in snapshot['records'])}
    snapshot['summary']={**snapshot['summary'],**{state:sum(r['status']==state for r in snapshot['records'])
        for state in ('apto','apto_com_alertas','bloqueado')}}
    return snapshot


def attach_communities(identity,record,classification,selected,uow):
    """Administrative native parent links; drafts remain unpublished.

    Every destination must permit direct inclusion. No inclusion requests,
    notifications, permission changes, removals or ownership transfers occur.
    """
    from invenio_communities.proxies import current_communities
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_records_resources.services.uow import RecordCommitOp
    expected=deepcopy(classification);signature=expected.pop('sha256',None)
    if digest(expected)!=signature:
        raise ValueError('Classificação alterada após a revisão. Prepare o lote novamente.')
    candidates={c['id']:c for c in classification['communities']}
    if set(selected)-set(candidates):
        raise ValueError('Comunidade fora da classificação revisada.')
    service.require_permission(identity,'update_draft',record=record)
    parent=record.parent
    existing={str(value) for value in parent.communities.ids}
    applied=[]
    for cid in selected:
        community=current_communities.service.record_cls.pid.resolve(cid)
        if community.model.deletion_status.value!='P' or community.model.slug!=candidates[cid]['slug']:
            raise ValueError('Uma comunidade mudou ou foi desativada. Prepare outra revisão.')
        for action in ('submit_record','include_directly'):
            current_communities.service.require_permission(identity,action,record=community)
        # Mirror native restrictions without broadening a record's visibility.
        if community['access']['visibility']=='restricted' and record.get('access',{}).get('record')=='public':
            raise ValueError('Registro público não pode ser incluído em comunidade restrita.')
        if cid not in existing:
            parent.communities.add(community,default=not bool(existing))
            existing.add(cid)
        applied.append(candidates[cid])
    if applied:
        uow.register(RecordCommitOp(parent))
        uow.register(RecordCommitOp(record,indexer=service.indexer))
        # Existing publications share the parent and need refreshed facets.
        from invenio_rdm_records.records.models import RDMRecordMetadata
        published_model=db.session.get(RDMRecordMetadata,record.id)
        if published_model and published_model.deletion_status.value=='P':
            published=service.record_cls.get_record(record.id)
            uow.register(RecordCommitOp(published,indexer=service.indexer))
        db.session.flush()
    return applied
