"""Check draft-only consolidation and binary media on restricted synthetic data."""
from io import BytesIO
import json
from pathlib import Path
import uuid
import zipfile
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_records_resources.services.uow import UnitOfWork,RecordCommitOp
from invenio_rdm_records.proxies import current_rdm_records_service as service
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.duplicates import record_snapshot,plan_group,reference_blockers,backup_path
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex.tasks import run

app=create_ui()
with app.app_context():
    identity=actor_identity(4)
    work='W'+str(int(uuid.uuid4().hex[:12],16))
    ids=[]
    for i in range(2):
        draft=service.create(identity,{'metadata':{'title':'TESTE SINTÉTICO — mídia e rascunhos '+str(i),
            'resource_type':{'id':'publication-article'},'publication_date':'2026-10-23',
            'creators':[{'person_or_org':{'type':'personal','name':'Teste, Mídia','family_name':'Teste','given_name':'Mídia'}}],
            'identifiers':[{'scheme':'url','identifier':'https://openalex.org/'+work}]},
            'files':{'enabled':False},'media_files':{'enabled':True},
            'access':{'record':'restricted','files':'restricted'}})
        ids.append(draft.id)
        Path('/tmp/openalex-duplicates-media-fixtures.json').write_text(json.dumps(ids))
        with UnitOfWork() as uow:
            record=draft._record
            record.media_files.enabled=True
            if not record.media_files.bucket:record.media_files.create_bucket()
            record.media_files.create('media.txt',stream=BytesIO(b'TEST media '+bytes([48+i])),transfer={'type':'L'})
            record.media_files.commit('media.txt')
            uow.register(RecordCommitOp(record,indexer=service.indexer));uow.commit()
    rows=[record_snapshot(identity,{'id':rid,'kind':'draft','tokens':['openalex:'+work]}) for rid in ids]
    group=reference_blockers(plan_group(rows,ids[0]))
    assert not group['blockers'],group['blockers']
    job=OpenAlexJob(kind='dedup_merge',actor=4,params={'test_only':True,'plan_sha256':digest(group)},snapshot={'group':group})
    db.session.add(job);db.session.commit();jid=job.id
    run(jid)
    job=db.session.get(OpenAlexJob,jid)
    assert job.state=='completed',job.result
    after=service.read_draft(identity,ids[0]).to_dict()
    assert after['is_draft'] and after['media_files']['count']==2 and not after['files']['count']
    with zipfile.ZipFile(backup_path(jid)) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        for entry in manifest['files']:
            record=service.read_draft(identity,ids[0])._record
            with record.media_files[entry['destination']].open_stream('rb') as stream:
                assert stream.read()==archive.read(entry['archive'])
    service.delete_draft(identity,ids[0])
    result={'draft_only_remains_draft':True,'binary_media_verified':2,'media_name_collision_preserved':True,
            'synthetic_drafts_removed':True,'job':jid}
    Path('/tmp/openalex-duplicates-media-results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
