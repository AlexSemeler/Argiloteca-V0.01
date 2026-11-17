"""Preview/apply thematic communities to active existing records, never recreate them.

Run inside the configured Invenio UI runtime. Preview is mandatory; apply takes
its exact SHA-256. Native bulk_add changes parents only. All changes commit in
one UnitOfWork; the preview contains complete original parent snapshots.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import csv
import hashlib
import html
import json
import os
from pathlib import Path

from invenio_app.factory import create_ui
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records as ext
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
from invenio_pidstore.models import PersistentIdentifier
from invenio_records_resources.services.uow import UnitOfWork
from sqlalchemy import text

from argiloteca.openalex.adapters import digest
from argiloteca.openalex.classification import load_vocabulary, community_catalog, classify
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex.duplicates import inventory_groups


def active_records(identity):
    active_pids={p.pid_value for p in PersistentIdentifier.query.filter_by(pid_type='recid') if p.status.value in ('N','R')}
    published={str(r.id):r for r in RDMRecordMetadata.query.all()}
    parents=defaultdict(list)
    for model,kind in ((RDMRecordMetadata,'published'),(RDMDraftMetadata,'draft')):
        for row in model.query.all():
            if not row.json or str(row.json.get('id','')) not in active_pids:
                continue
            original=published.get(str(row.id))
            if original and original.deletion_status.value!='P':
                continue
            parents[str(row.parent_id)].append((row,kind))
    result=[]
    for parent,versions in parents.items():
        row,kind=max(versions,key=lambda r:(r[1]=='published',r[0].index))
        # Include all versions/edits in the immutable baseline, not only the latest.
        versions_json=[{'kind':k,'uuid':str(r.id),'json':deepcopy(r.json)} for r,k in versions]
        result.append({'id':row.json['id'],'kind':kind,'uuid':str(row.id),'parent_id':parent,
            'record':deepcopy(row.json),'parent':deepcopy(row.parent.json),
            'versions':sorted(versions_json,key=lambda r:(r['uuid'],r['kind']))})
    return sorted(result,key=lambda r:r['id'])


def make_preview(identity):
    vocabulary,version=load_vocabulary(app.config['ARGILOTECA_OPENALEX_ROOT'])
    catalog=community_catalog(identity)
    all_records=active_records(identity)
    counts=Counter();by_community=Counter();rows=[]
    for row in all_records:
        classification=classify({'payload':row['record'],'provenance':[]},vocabulary,catalog,version)
        current=row['parent'].get('communities',{}).get('ids',[])
        additions=[c for c in classification['communities'] if c['id'] not in current]
        blockers=[]
        for c in additions:
            community=__import__('invenio_communities.proxies',fromlist=['current_communities']).current_communities.service.record_cls.pid.resolve(c['id'])
            if community['access']['visibility']=='restricted' and row['record'].get('access',{}).get('record')=='public':
                blockers.append('Registro público e comunidade restrita incompatíveis.')
        state='blocked' if blockers else 'add' if additions else 'already_linked' if classification['communities'] else 'unclassified'
        counts[state]+=1
        if state=='add':by_community.update(c['slug'] for c in additions)
        rows.append({**row,'title':row['record'].get('metadata',{}).get('title','Sem título'),
            'current':current,'classification':classification,'additions':additions,'blockers':blockers,'state':state})
    return {'schema':1,'created':datetime.now(timezone.utc).isoformat(),'actor':args.actor,
        'policy':'add-only-parent-native-bulk-v1','rule':version,'records':rows,
        'summary':{'records':len(rows),**dict(counts),'new_links':sum(by_community.values()),'by_community':dict(by_community)},
        'catalog':catalog,'corpus_sha256':digest(all_records)}


def write_private(path,content):
    path.parent.mkdir(parents=True,exist_ok=True);os.chmod(path.parent,0o700)
    with path.open('w') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
    path.chmod(0o600)


def export_preview(plan,path):
    write_private(path,json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    names={c['id']:c['title'] for c in plan['catalog'].values()}
    rows=[]
    with path.with_suffix('.csv').open('w') as stream:
        writer=csv.writer(stream);writer.writerow(['id','title','state','current','additions','evidence','blockers'])
        for r in plan['records']:
            current=', '.join(names.get(c,c) for c in r['current']) or 'Sem comunidade'
            additions=', '.join(c['title'] for c in r['additions']) or 'Sem acréscimo'
            evidence='; '.join(h['label']+' ('+h['source']+')' for h in r['classification']['evidence'])
            values=[r['id'],r['title'],r['state'],current,additions,evidence,'; '.join(r['blockers'])]
            writer.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in values])
            rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in values)+'</tr>')
    path.with_suffix('.csv').chmod(0o600)
    page='<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Prévia de comunidades — Argiloteca</title><h1>Prévia da classificação dos registros existentes</h1><p>Somente acréscimos de comunidades; vínculos atuais, metadados, arquivos, PID e publicação preservados. Classificação temática por termos, sem inferência científica.</p><pre>'+html.escape(json.dumps(plan['summary'],ensure_ascii=False,indent=2))+'</pre><table border="1" cellpadding="6"><thead><tr>'+''.join('<th>'+s+'</th>' for s in ('Registro','Título','Situação','Comunidades atuais','Acrescentar','Termos e campos','Bloqueios'))+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></html>'
    write_private(path.with_suffix('.html'),page)


def apply_preview(identity,path,sha):
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=sha:raise ValueError('Hash da prévia divergente.')
    plan=json.loads(content)
    if plan['actor']!=args.actor or plan['policy']!='add-only-parent-native-bulk-v1':raise ValueError('Prévia não autorizada para este fluxo.')
    signature=digest({'preview':sha,'actor':args.actor})
    prior=next((j for j in OpenAlexJob.query.filter_by(kind='classify_existing') if j.params.get('signature')==signature and j.state=='completed'),None)
    if prior:return prior.result
    # Snapshot is also an immutable backup of every parent and all metadata.
    # A separate database dump is required by the operator before application.
    backup=Path(args.database_backup)
    if not backup.is_file() or backup.stat().st_size<1024 or backup.read_bytes()[:5]!=b'PGDMP':raise ValueError('Backup PostgreSQL ausente/inválido.')
    with UnitOfWork(db.session) as uow:
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
        # Lock native models/parents before rechecking the complete inventory.
        from invenio_rdm_records.records.models import RDMParentMetadata
        db.session.query(RDMParentMetadata).order_by(RDMParentMetadata.id).with_for_update().all()
        db.session.query(RDMRecordMetadata).order_by(RDMRecordMetadata.id).with_for_update().all()
        db.session.query(RDMDraftMetadata).order_by(RDMDraftMetadata.id).with_for_update().all()
        current=active_records(identity)
        if digest(current)!=plan['corpus_sha256']:raise ValueError('Acervo mudou após a prévia. Gere outra prévia.')
        fresh=make_preview(identity)
        # Recompute exact reviewed classifications and destinations from trusted
        # vocabulary/catalog, rather than trusting an edited plan file.
        for old,new in zip(plan['records'],fresh['records']):
            for key in ('id','classification','additions','state','blockers'):
                if old[key]!=new[key]:raise ValueError('Classificação/comunidade mudou após a prévia.')
        targets=defaultdict(list)
        draft_targets=defaultdict(list)
        for row in plan['records']:
            if row['state']=='add':
                for community in row['additions']:
                    (targets if row['kind']=='published' else draft_targets)[community['id']].append(row['id'])
        job=OpenAlexJob(kind='classify_existing',state='completed',actor=args.actor,
            params={'signature':signature,'preview_sha256':sha,'policy':plan['policy']},
            snapshot={'classification_plan':plan})
        db.session.add(job);db.session.flush()
        for cid,ids in targets.items():
            community=__import__('invenio_communities.proxies',fromlist=['current_communities']).current_communities.service.record_cls.pid.resolve(cid)
            cs=__import__('invenio_communities.proxies',fromlist=['current_communities']).current_communities.service
            for action in ('read','submit_record','include_directly'):cs.require_permission(identity,action,record=community)
            for start in range(0,len(ids),100):
                errors=ext.record_communities_service.bulk_add(identity,cid,ids[start:start+100],set_default=False,uow=uow)
                if errors:raise ValueError(str(errors))
        # Drafts use the same native parent manager as reviewed imports, without
        # touching draft metadata or creating/publishing a draft.
        from invenio_communities.proxies import current_communities
        from invenio_rdm_records.services.communities.service import ParentRecordCommitOp
        for cid,ids in draft_targets.items():
            cs=current_communities.service
            community=cs.record_cls.pid.resolve(cid)
            for action in ('read','submit_record','include_directly'):cs.require_permission(identity,action,record=community)
            for rid in ids:
                record=service.read_draft(identity,rid)._record
                service.require_permission(identity,'update_draft',record=record)
                if cid not in {str(c) for c in record.parent.communities.ids}:
                    record.parent.communities.add(community,default=not bool(record.parent.communities.ids))
                    uow.register(ParentRecordCommitOp(record.parent,indexer_context={'service':service},bulk_index=True))
        # Parent JSON changed in memory. Native record/versions must not.
        after=active_records(identity)
        before_by_id={r['id']:r for r in plan['records']}
        if len(after)!=len(plan['records']):raise ValueError('Contagem de registros mudou.')
        for actual in after:
            old=before_by_id[actual['id']]
            if actual['record']!=old['record'] or actual['versions']!=old['versions']:raise ValueError('Metadados/arquivos/versões mudaram.')
            expected=deepcopy(old['parent']);communities=expected.setdefault('communities',{})
            expected_ids=list(old['current'])
            if old['state']=='add':expected_ids+= [c['id'] for c in old['additions']]
            actual_ids=actual['parent'].get('communities',{}).get('ids',[])
            if set(actual_ids)!=set(expected_ids) or len(actual_ids)!=len(set(actual_ids)):raise ValueError('Vínculos inesperados/duplicados.')
            # Ignore only community ids and initial default assigned natively.
            for value in (expected,actual['parent']):
                block=value.get('communities',{});block.pop('ids',None)
                if not old['current']:block.pop('default',None)
                if not block:value.pop('communities',None)
            if expected!=actual['parent']:raise ValueError('Parent teve alteração fora das comunidades.')
        job.result={'summary':plan['summary'],'job_id':job.id,'preview_sha256':sha,
            'database_backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),
            'same_record_count':True,'metadata_files_versions_unchanged':True,
            'existing_links_preserved':True,'duplicate_memberships':0}
        if args.rollback_only:
            result={**deepcopy(job.result),'rollback_only':True}
            uow.rollback()
            return result
        uow.commit()
    return job.result


def refresh_search(plan):
    """Make affected versions visible immediately, independent of bulk polling."""
    import uuid
    indexed=set()
    for row in plan['records']:
        if row['state']!='add':continue
        for version in row['versions']:
            key=(version['kind'],version['uuid'])
            if key in indexed:continue
            indexer=service.indexer if version['kind']=='published' else service.draft_indexer
            indexer.index_by_id(uuid.UUID(version['uuid']))
            indexed.add(key)
    prefix=app.config.get('SEARCH_INDEX_PREFIX','')
    service.indexer.client.indices.refresh(index=','.join(prefix+c.index._name for c in (service.record_cls,service.draft_cls)))
    return len(indexed)


parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode',choices=['preview','apply'])
parser.add_argument('--actor',type=int,default=4)
parser.add_argument('--preview',required=True)
parser.add_argument('--sha256')
parser.add_argument('--database-backup')
parser.add_argument('--rollback-only',action='store_true')
args=parser.parse_args()
app=create_ui()
with app.app_context():
    identity=actor_identity(args.actor);path=Path(args.preview)
    if args.mode=='preview':
        plan=make_preview(identity);export_preview(plan,path)
        print(json.dumps({'summary':plan['summary'],'preview_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'preview':str(path)},ensure_ascii=False))
    else:
        if not args.sha256 or not args.database_backup:parser.error('apply requer --sha256 e --database-backup')
        result=apply_preview(identity,path,args.sha256)
        if not args.rollback_only and not result.get('search_refreshed'):
            indexed=refresh_search(json.loads(path.read_text()))
            result={**result,'search_refreshed':True,'indexed_versions':indexed}
            job=db.session.get(OpenAlexJob,result['job_id']);job.result=result;db.session.commit()
        write_private(path.with_name('rollback-test.json' if args.rollback_only else 'result.json'),json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False))
