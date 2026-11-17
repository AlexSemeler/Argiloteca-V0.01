"""Mac-agent end-to-end verification on one explicitly synthetic V59 lot."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import zipfile
from invenio_app.factory import create_ui
from invenio_db import db
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex import maintenance as clean
from argiloteca.openalex.tasks import run

app=create_ui();lot=sys.argv[1];assert lot.startswith('v59_TEST_MAINTENANCE_')
with app.app_context():
    identity=actor_identity(4);root=Path(app.config['ARGILOTECA_OPENALEX_ROOT']);queue=Path(app.config['ARGILOTECA_OPENALEX_QUEUE'])
    original=clean.maintenance_files.manifest(root,lot);jobs=[]
    # A failed SQL commit must never expose a destructive request to the Mac.
    from unittest.mock import patch
    p=clean.plan(identity,4,'lot',lot,'archive_lot',reason='TEST ONLY — failed commit guard')
    source=OpenAlexJob(kind='clean_preview',state='review',actor=4,params={'test_only':True},snapshot={'plan':p});db.session.add(source);db.session.commit()
    failed=OpenAlexJob(kind='clean_apply',actor=4,params={'source_job':source.id,'plan_sha256':digest(p),'test_only':True},snapshot={'plan':deepcopy(p)});db.session.add(failed);db.session.commit();fid=failed.id
    with patch('invenio_records_resources.services.uow.UnitOfWork.commit',side_effect=RuntimeError('TEST commit failure')):run(fid)
    assert db.session.get(OpenAlexJob,fid).state=='failed'
    assert not (queue/(fid+'.request.json')).exists() and (root/'lotes'/lot).exists()
    print('failed_sql_commit_not_dispatched OK',flush=True)
    for action,archived in [('archive_lot',False),('restore_lot',True),('delete_lot',False)]:
        p=clean.plan(identity,4,'lot',lot,action,archived=archived,reason='TEST ONLY — disposable lot maintenance')
        assert not p['blockers'],p['blockers']
        source=OpenAlexJob(kind='clean_preview',state='review',actor=4,params={'test_only':True},snapshot={'plan':p})
        db.session.add(source);db.session.commit()
        job=OpenAlexJob(kind='clean_apply',actor=4,params={'source_job':source.id,'plan_sha256':digest(p),'test_only':True},snapshot={'plan':deepcopy(p)})
        db.session.add(job);db.session.commit();jid=job.id;run(jid)
        # Re-delivery while waiting must never rewrite an already dispatched request.
        request=queue/(jid+'.request.json');saved=request.read_bytes();run(jid);assert request.read_bytes()==saved
        for _ in range(15):
            if (queue/(jid+'.result.json')).exists():break
            time.sleep(2)
        run(jid);db.session.expire_all();job=db.session.get(OpenAlexJob,jid)
        assert job.state=='completed',(job.state,job.result)
        with zipfile.ZipFile(queue/'maintenance-backups'/(jid+'.zip')) as archive:
            assert archive.read('lot/synthetic.txt').decode().startswith('TEST ONLY')
        jobs.append(jid)
        print(action,'OK',jid,flush=True)
        if action!='delete_lot':
            actual=clean.maintenance_files.manifest(root,lot,not archived)
            assert actual['files']==original['files']
    assert not (root/'lotes'/lot).exists() and not (root/'.admin-trash'/lot).exists()
    evidence={'synthetic_lot':lot,'jobs':jobs,'mac_archive_restore_delete':True,'backup_original_bytes':True,'dispatch_not_replayed':True,'failed_sql_commit_not_dispatched':True}
    Path('/tmp/admin-maintenance-lot-results.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence))
