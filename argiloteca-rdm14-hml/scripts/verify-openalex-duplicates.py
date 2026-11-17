"""Native integration on explicitly labelled restricted synthetic records only."""
from copy import deepcopy
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import uuid
from unittest.mock import patch
import zipfile

from invenio_app.factory import create_ui
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from argiloteca.openalex.adapters import converter,digest
from argiloteca.openalex.duplicates import (record_snapshot,plan_group,reference_blockers,
    backup_path,inventory_groups,fingerprint)
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.service import actor_identity,inventory,matches
from argiloteca.openalex.tasks import run

app=create_ui()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reuse-fixtures',action='store_true')
args=parser.parse_args()
results={}
with app.app_context():
    identity=actor_identity(4)
    work='W'+str(int(uuid.uuid4().hex[:12],16))
    originals=[]
    if args.reuse_fixtures:
        saved=json.loads(Path('/tmp/openalex-duplicates-fixtures.json').read_text())
        originals,work=saved['ids'],saved['work']
        for i,rid in enumerate(originals):
            current=(service.read if i<2 else service.read_draft)(identity,rid).to_dict()
            assert current['metadata']['title'].startswith('TESTE SINTÉTICO — consolidação de duplicados ')
            assert current['access']['record']=='restricted'
    for i in range(3):
        if args.reuse_fixtures:
            continue
        payload={'metadata':{'title':'TESTE SINTÉTICO — consolidação de duplicados '+str(i+1),
            'resource_type':{'id':'publication-article'},'publication_date':'2026-10-23',
            'creators':[{'person_or_org':{'type':'personal','given_name':'Duplicados','family_name':'Teste','name':'Teste, Duplicados'}}],
            'description':['Descrição curta.','Descrição científica mais completa, preservada da duplicata.','Outro texto para conferir alternativas.'][i],
            'identifiers':[{'scheme':'url','identifier':'https://openalex.org/'+work}]},
            'files':{'enabled':True},'access':{'record':'restricted','files':'restricted'}}
        draft=service.create(identity,payload)
        rid=draft.id
        originals.append(rid)
        Path('/tmp/openalex-duplicates-fixtures.json').write_text(json.dumps({'ids':originals,'work':work}))
        files={'curva.csv':b'CURVE synthetic '+bytes([48+i])}
        if i==1:files['artigo.pdf']=b'%PDF synthetic file; not a scientific document'
        if i==2:files['suplemento.txt']=b'TEST synthetic supplement'
        for key,content in files.items():
            service.draft_files.init_files(identity,rid,[{'key':key}])
            service.draft_files.set_file_content(identity,rid,key,BytesIO(content),content_length=len(content))
            service.draft_files.commit_file(identity,rid,key)
        if i<2:
            service.publish(identity,rid)
    print('restricted fixtures',originals,flush=True)
    Path('/tmp/openalex-duplicates-fixtures.json').write_text(json.dumps({'ids':originals,'work':work}))
    rows=[record_snapshot(identity,{'id':rid,'kind':'published' if i<2 else 'draft','tokens':['openalex:'+work]}) for i,rid in enumerate(originals)]
    group=reference_blockers(plan_group(rows,originals[0],{'/metadata/description':'Descrição científica mais completa, preservada da duplicata.'}))
    assert not group['blockers'],group['blockers']
    assert len(group['files'])==5
    scan=OpenAlexJob(kind='dedup_scan',state='review',actor=4,snapshot={
        'groups':[group],'independent_records':3},result={'groups':1,'extra_records':2},params={'test_only':True})
    db.session.add(scan);db.session.commit()
    preview=OpenAlexJob(kind='dedup_preview',state='review',actor=4,snapshot={'schema':1,'group':group},
        params={'source_job':scan.id,'test_only':True})
    db.session.add(preview);db.session.commit()
    results['preview_job']=preview.id
    def merge_job():
        job=OpenAlexJob(kind='dedup_merge',actor=4,snapshot={'schema':1,'group':deepcopy(group)},
            params={'source_job':preview.id,'plan_sha256':digest(group),'test_only':True})
        db.session.add(job);db.session.commit()
        return job.id
    before={rid:deepcopy(read_record.to_dict()) for rid,read_record in [(r['id'],
        service.read(identity,r['id']) if r['kind']=='published' else service.read_draft(identity,r['id'])) for r in rows]}

    # A failed archive must stop before editing or retiring anything.
    failed=merge_job()
    with patch('argiloteca.openalex.duplicates.write_backup',side_effect=ValueError('TESTE: backup indisponível')):
        run(failed)
    assert db.session.get(OpenAlexJob,failed).state=='failed'
    for row in rows:
        current=(service.read if row['kind']=='published' else service.read_draft)(identity,row['id']).to_dict()
        assert fingerprint(current)==fingerprint(before[row['id']])
    results['backup_failure_changes_nothing']=True

    # A native transaction failure after copies/retirements must roll them back.
    failed_transaction=merge_job()
    with patch('invenio_records_resources.services.uow.UnitOfWork.commit',side_effect=RuntimeError('TEST precommit rollback')) as failed_commit:
        run(failed_transaction)
        failed_commit.assert_called_once()
    assert db.session.get(OpenAlexJob,failed_transaction).state=='failed'
    for row in rows:
        current=(service.read if row['kind']=='published' else service.read_draft)(identity,row['id']).to_dict()
        assert fingerprint(current)==fingerprint(before[row['id']])
    assert backup_path(failed_transaction).is_file()
    results['native_rollback_preserves_records_and_backup']=True

    # A saved preview cannot overwrite intervening edits.
    modified=deepcopy(before[originals[2]])
    data={'metadata':{**modified['metadata'],'publisher':'TEST changed after preview'},
          'custom_fields':modified.get('custom_fields',{}),'files':{'enabled':True}}
    service.update_draft(identity,originals[2],data)
    stale=merge_job();run(stale)
    assert db.session.get(OpenAlexJob,stale).state=='failed'
    assert not backup_path(stale).exists()
    results['stale_preview_refused']=True
    # Refresh the approved plan after restoring the test fixture metadata.
    data['metadata']=modified['metadata'];service.update_draft(identity,originals[2],data)
    rows=[record_snapshot(identity,{'id':rid,'kind':'published' if i<2 else 'draft','tokens':['openalex:'+work]}) for i,rid in enumerate(originals)]
    group=reference_blockers(plan_group(rows,originals[0],{'/metadata/description':'Descrição científica mais completa, preservada da duplicata.'}))
    preview.snapshot={'schema':1,'group':group};db.session.add(preview);db.session.commit()
    successful=merge_job();run(successful)
    job=db.session.get(OpenAlexJob,successful)
    assert job.state=='completed',job.result
    final=service.read(identity,originals[0]).to_dict()
    assert final['id']==originals[0] and final['versions']['index']==1
    assert final['metadata']['description']=='Descrição científica mais completa, preservada da duplicata.'
    assert final['access']['record']=='restricted' and final['access']['files']=='restricted'
    assert final['files']['count']==5
    assert service.record_cls.pid.resolve(originals[1]).deletion_status.is_deleted
    with zipfile.ZipFile(backup_path(successful)) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        assert len(manifest['files'])==5
        for entry in manifest['files']:
            content=archive.read(entry['archive'])
            assert hashlib.sha256(content).hexdigest()==entry['sha256']
            file=service.files.get_file_content(identity,originals[0],entry['destination'])
            with file.open_stream('rb') as stream:assert stream.read()==content
    metadata=converter(app.config['ARGILOTECA_OPENALEX_ROOT'])[0]
    assert {r['id'] for r in matches({'payload':final},inventory(metadata),metadata)}=={originals[0]}
    rev=final['revision_id'];run(successful)
    assert service.read(identity,originals[0]).to_dict()['revision_id']==rev
    results.update({'same_pid_and_version':True,'native_file_checksums_verified':5,
        'name_collisions_preserved':True,'published_and_draft_donors_retired':True,
        'redelivery_idempotent':True,'merge_job':successful,'canonical':originals[0]})

    # Retire the remaining restricted synthetic publication after testing.
    service.delete_record(identity,originals[0],{'removal_reason':{'id':'duplicate'},'is_visible':False,
        'note':'TESTE SINTÉTICO encerrado. Nenhum registro científico real foi usado.',
        'citation_text':'TESTE SINTÉTICO — encerrado.'})
    results['synthetic_records_not_active']=True
    Path('/tmp/openalex-duplicates-native-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False),flush=True)
