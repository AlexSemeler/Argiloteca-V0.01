"""Reviewed, additive community curation of existing native parents."""
from collections import defaultdict
from copy import deepcopy
import uuid

from flask import current_app
from invenio_db import db
from sqlalchemy import text
from sqlalchemy.orm import joinedload
from invenio_pidstore.models import PersistentIdentifier
from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata, RDMParentMetadata
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.proxies import current_rdm_records as extension
from invenio_communities.proxies import current_communities
from invenio_records_resources.services.uow import UnitOfWork
from invenio_rdm_records.services.communities.service import ParentRecordCommitOp

from .adapters import digest
from .classification import classify, load_vocabulary, community_catalog
from .models import OpenAlexJob
from .service import actor_identity


def topic_hash(metadata):
    return digest({k:metadata.get(k) for k in ('title','description','subjects')})


def active_items():
    pids={p.pid_value for p in PersistentIdentifier.query.filter_by(pid_type='recid') if p.status.value in ('N','R')}
    published={str(r.id):r for r in RDMRecordMetadata.query.all()}
    parents=defaultdict(list)
    for model,kind in ((RDMRecordMetadata,'published'),(RDMDraftMetadata,'draft')):
        for row in model.query.options(joinedload(model.parent)).all():
            if not row.json or str(row.json.get('id','')) not in pids:continue
            original=published.get(str(row.id))
            if original and original.deletion_status.value!='P':continue
            parents[str(row.parent_id)].append((row,kind))
    return sorted((max(rows,key=lambda r:(r[1]=='published',r[0].index)) for rows in parents.values()),key=lambda r:r[0].json['id'])


def decisions():
    result=defaultdict(list)
    for job in OpenAlexJob.query.filter_by(kind='manual_apply',state='completed'):
        if job.result.get('decision'):
            result[job.result['decision']['parent_id']].append(job.result['decision'])
    return result


def is_reviewed(metadata,current,prior):
    return any(d['topic_sha256']==topic_hash(metadata) and set(d['confirmed_ids']).issubset(current) for d in prior)


def snapshot_record(identity,item):
    model,kind=item
    record=(service.read if kind=='published' else service.read_draft)(identity,model.json['id'])._record
    versions=[]
    for cls,k in ((RDMRecordMetadata,'published'),(RDMDraftMetadata,'draft')):
        versions.extend({'uuid':str(r.id),'kind':k,'raw':deepcopy(r.json)} for r in cls.query.filter_by(parent_id=record.parent.id))
    parent=deepcopy(dict(record.parent));raw=deepcopy(dict(record))
    return {'id':model.json['id'],'kind':kind,'uuid':str(record.id),'parent_id':str(record.parent.id),
        'metadata':deepcopy(raw.get('metadata',{})),'raw':raw,'parent_raw':parent,'versions':sorted(versions,key=lambda v:(v['kind'],v['uuid'])),
        'current_ids':[str(c) for c in record.parent.communities.ids],
        'topic_sha256':topic_hash(raw.get('metadata',{})),
        'fingerprint':digest({'raw':raw,'parent':parent,'kind':kind,'versions':sorted(versions,key=lambda v:(v['kind'],v['uuid']))})}


def scan_job(job):
    identity=actor_identity(job.actor)
    vocabulary,version=load_vocabulary(current_app.config['ARGILOTECA_OPENALEX_ROOT'])
    catalog=community_catalog(identity);prior=decisions();rows=[];reviewed=0;total=0
    for model,kind in active_items():
        total+=1;metadata=model.json.get('metadata',{})
        current=set(model.parent.json.get('communities',{}).get('ids',[]))
        classification=classify({'payload':{'metadata':metadata},'provenance':[]},vocabulary,catalog,version)
        if classification['state']!='needs_review':continue
        if is_reviewed(metadata,current,prior[str(model.parent_id)]):reviewed+=1;continue
        row=snapshot_record(identity,(model,kind));row['classification']=classification;rows.append(row)
    job.snapshot={'schema':1,'rows':rows,'catalog':catalog,'rule':version}
    job.result={'total':total,'pending':len(rows),'manually_reviewed':reviewed}
    job.state='review'


def selected_targets(identity,selected,catalog):
    """Expand native ancestor links so the preview shows every added community."""
    by_id={c['id']:c for c in catalog.values()};targets=[];seen=set()
    def include(cid):
        if cid in seen:return
        seen.add(cid)
        candidate=by_id.get(cid)
        if not candidate or not candidate['allowed']:raise ValueError('Comunidade indisponível ou sem permissão de inclusão direta.')
        community=current_communities.service.record_cls.pid.resolve(cid)
        if community.model.deletion_status.value!='P':raise ValueError('Comunidade desativada. Atualize a revisão.')
        for action in ('read','submit_record','include_directly'):
            current_communities.service.require_permission(identity,action,record=community)
        targets.append(deepcopy(candidate))
        parent=getattr(community,'parent',None)
        if parent:include(str(parent.id))
    for cid in selected:include(cid)
    return targets


def build_plan(identity,row,selected,note='',keep=False):
    selected=list(dict.fromkeys(selected))
    if len(selected)>100 or len(note)>2000:raise ValueError('Seleção ou justificativa excede o limite permitido.')
    if keep and (selected or not row['current_ids']):raise ValueError('Para concluir com os vínculos atuais, desmarque novos destinos. O registro precisa ter uma comunidade.')
    if not keep and not selected:raise ValueError('Selecione ao menos uma comunidade para acrescentar.')
    catalog=community_catalog(identity)
    targets=selected_targets(identity,selected,catalog)
    additions=[c for c in targets if c['id'] not in row['current_ids']]
    for target in additions:
        community=current_communities.service.record_cls.pid.resolve(target['id'])
        if community['access']['visibility']=='restricted' and row['raw'].get('access',{}).get('record')=='public':
            raise ValueError('Registro público não pode ser associado a uma comunidade restrita.')
    if row['kind']=='published':extension.record_communities_service.require_permission(identity,'bulk_add')
    else:service.require_permission(identity,'update_draft',record=service.read_draft(identity,row['id'])._record)
    return {'schema':1,'row':deepcopy(row),'selected':selected,'additions':additions,'keep':bool(keep),'note':note,
        'catalog':catalog,'confirmed_ids':sorted(set(row['current_ids'])|{c['id'] for c in additions})}


def verify_parent(before,after,expected_ids):
    before=deepcopy(before);after=deepcopy(after)
    ids=after.get('communities',{}).get('ids',[])
    if set(ids)!=set(expected_ids) or len(ids)!=len(set(ids)):raise ValueError('Vínculos finais não correspondem à prévia.')
    had_ids=bool(before.get('communities',{}).get('ids'))
    for value in (before,after):
        block=value.get('communities',{});block.pop('ids',None)
        if not had_ids:block.pop('default',None)
        if not block:value.pop('communities',None)
    if before!=after:raise ValueError('O parent mudou fora dos vínculos aprovados.')


def refresh_record(plan):
    """Refresh all sibling versions immediately, independently of bulk polling."""
    for version in plan['row']['versions']:
        cls=RDMRecordMetadata if version['kind']=='published' else RDMDraftMetadata
        model=db.session.get(cls,uuid.UUID(version['uuid']))
        if model is None or not model.json or version['kind']=='published' and model.deletion_status.value!='P':continue
        indexer=service.indexer if version['kind']=='published' else service.draft_indexer
        indexer.index_by_id(model.id)
    prefix=current_app.config.get('SEARCH_INDEX_PREFIX','')
    service.indexer.client.indices.refresh(index=','.join(prefix+c.index._name for c in (service.record_cls,service.draft_cls)))


def apply_job(job):
    identity=actor_identity(job.actor);plan=job.snapshot['plan'];row=plan['row']
    if job.params['plan_sha256']!=digest(plan):raise ValueError('Prévia alterada. Prepare outra revisão.')
    source=db.session.get(OpenAlexJob,job.params['source_job'])
    if not source or source.kind!='manual_preview' or source.actor!=job.actor or source.snapshot!=job.snapshot:
        raise ValueError('Prévia de origem inválida. Prepare outra revisão.')
    with UnitOfWork(db.session) as uow:
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
        db.session.query(RDMParentMetadata).filter_by(id=uuid.UUID(row['parent_id'])).with_for_update().one()
        for version in row['versions']:
            cls=RDMRecordMetadata if version['kind']=='published' else RDMDraftMetadata
            db.session.query(cls).filter_by(id=uuid.UUID(version['uuid'])).with_for_update().one()
        db.session.refresh(source)
        if source.state=='completed':raise ValueError('Esta prévia já foi concluída. Consulte o resultado e verifique novamente.')
        # Resolve the current active PID/kind; retired publications must never
        # be reintroduced through an orphaned draft or historical snapshot.
        item=next(((m,k) for m,k in active_items() if str(m.parent_id)==row['parent_id']),None)
        if item is None:raise ValueError('Registro retirado ou indisponível. Verifique novamente.')
        fresh=snapshot_record(identity,item)
        fresh['classification']=deepcopy(row.get('classification',{}))
        if fresh['fingerprint']!=row['fingerprint']:raise ValueError('O registro ou seus vínculos mudaram. Verifique novamente e revise uma nova prévia.')
        rebuilt=build_plan(identity,fresh,plan['selected'],plan['note'],plan['keep'])
        if rebuilt!=plan:raise ValueError('Os destinos mudaram após a prévia. Revise novamente.')
        if row['kind']=='published':
            for index,target in enumerate(plan['additions']):
                errors=extension.record_communities_service.bulk_add(identity,target['id'],[row['id']],
                    set_default=not row['current_ids'] and index==0,uow=uow)
                if errors:raise ValueError('Não foi possível incluir a comunidade: '+str(errors))
        elif plan['additions']:
            record=service.read_draft(identity,row['id'])._record
            for target in plan['additions']:
                record.parent.communities.add(current_communities.service.record_cls.pid.resolve(target['id']),default=not bool(record.parent.communities.ids))
            uow.register(ParentRecordCommitOp(record.parent,indexer_context={'service':service},bulk_index=True))
        parent=db.session.get(RDMParentMetadata,uuid.UUID(row['parent_id']))
        verify_parent(row['parent_raw'],parent.json,plan['confirmed_ids'])
        for version in row['versions']:
            cls=RDMRecordMetadata if version['kind']=='published' else RDMDraftMetadata
            if db.session.get(cls,uuid.UUID(version['uuid'])).json!=version['raw']:
                raise ValueError('Metadados ou arquivos mudaram durante a associação.')
        job.result={'id':row['id'],'kind':row['kind'],'added':plan['additions'],'previous_ids':row['current_ids'],
            'confirmed_ids':plan['confirmed_ids'],'preserved':True,'search_refreshed':False,
            'decision':{'parent_id':row['parent_id'],'topic_sha256':row['topic_sha256'],'confirmed_ids':plan['confirmed_ids']}}
        job.state='completed';source.state='completed';source.result={'apply_job':job.id}
        uow.commit()
    # A post-commit index failure never replays the association. A separate
    # protected refresh action can repair only the search document.
    try:
        refresh_record(plan)
        job.result={**job.result,'search_refreshed':True};db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Manual communities committed; index refresh pending: %s',job.id)
