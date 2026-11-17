"""Native scheduler composition and immediate catalog access invalidation."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch,Mock
from flask import Flask
from celery import Celery
from argiloteca.argiloclay.scheduler import ArgiloClayScheduler,KEY
from argiloteca.scientific import catalog


def test_native_scheduler_retains_jobs_and_does_not_reset_refresh_clock():
    celery=Celery('sync-test');celery.conf.beat_schedule={KEY:{'task':'argiloteca.argiloclay.tasks.sync_public_records','schedule':60.0}}
    scheduler=ArgiloClayScheduler(app=celery,lazy=True);scheduler.entries={}
    def native_sync(self):self.entries={'native-existing-job':object()}
    with patch('invenio_jobs.services.scheduler.RunScheduler.sync',native_sync):
        scheduler.sync();first=scheduler.entries[KEY];first.last_run_at=celery.now()-timedelta(seconds=120)
        scheduler.sync();assert scheduler.entries[KEY] is first
        assert 'native-existing-job' in scheduler.entries
        assert first.is_due().is_due
        next_entry=scheduler.reserve(first);assert next_entry.total_run_count==1
        assert not next_entry.is_due().is_due


def fake_row(access='public',state='ativo'):
    data={'slug':'test','nome_pt':'Teste','nome_en':'Test','nome_cientifico_padronizado':'Test','situacao':state,'sinonimos':[]}
    return SimpleNamespace(json={'id':'abcde-12345','custom_fields':{catalog.FIELD:data},'access':{'record':access}},deletion_status=catalog.RecordDeletionStatusEnum.PUBLISHED)


def test_catalog_keeps_native_anonymous_read_and_request_local_cache():
    app=Flask(__name__);app.extensions['invenio-rdm-records']=object();row=fake_row()
    record=SimpleNamespace(updated=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
    class Record(dict):
        @property
        def updated(self):return record.updated
    item=SimpleNamespace(id='abcde-12345',_record=Record(row.json))
    reader=Mock(return_value=item)
    with patch.object(catalog,'catalog_rows',return_value=[row]),patch.object(catalog,'service',SimpleNamespace(read=reader)):
        with app.test_request_context('/'):
            assert catalog.public_catalog()['test']['nome']=='Teste'
            catalog.public_catalog();assert reader.call_count==1
            identity=reader.call_args.args[0];assert identity.id is None
        row.json['custom_fields'][catalog.FIELD]['nome_pt']='Editado'
        with app.test_request_context('/'):
            assert catalog.public_catalog()['test']['nome']=='Editado';assert reader.call_count==2


def test_private_and_withdrawn_catalog_terms_never_fall_back_to_seed():
    app=Flask(__name__);app.extensions['invenio-rdm-records']=object()
    for row in [fake_row('restricted'),fake_row(state='retirado')]:
        with app.test_request_context('/'),patch.object(catalog,'catalog_rows',return_value=[row]),patch.object(catalog,'service',SimpleNamespace(read=Mock())):
            assert catalog.public_catalog()=={'test':None};assert not catalog.service.read.called


def test_snapshot_rechecks_current_native_permissions_even_with_stale_search_hits():
    from datetime import datetime,timezone
    from invenio_records_resources.services.errors import PermissionDeniedError
    from argiloteca.argiloclay.tasks import public_records
    app=Flask(__name__);app.config['SITE_UI_URL']='https://example.org'
    class Record(dict):
        created=updated=datetime(2026,10,22,tzinfo=timezone.utc)
    visible=Record(metadata={'title':'Público','creators':[]},access={'record':'public'})
    hidden=Record(metadata={'title':'Restrito'},access={'record':'restricted'})
    class Hit:
        def __init__(self,id):self.id=id
        def to_dict(self):return {'id':self.id}
    def read(identity,rid):
        assert identity.id is None
        if rid=='denied':raise PermissionDeniedError('read')
        r=visible if rid=='public' else hidden
        return SimpleNamespace(id=rid,_record=r,to_dict=lambda:{'id':rid,**r,'created':r.created.isoformat(),'updated':r.updated.isoformat()})
    native=SimpleNamespace(scan=lambda identity,params:SimpleNamespace(_results=[Hit('public'),Hit('hidden'),Hit('denied')]),read=read)
    with app.app_context(),patch('invenio_rdm_records.proxies.current_rdm_records_service',native):
        rows=list(public_records());assert [r['record_id'] for r in rows]==['public']


def test_record_gateway_distinguishes_native_outage_from_permission_denial():
    from flask import g
    from flask_principal import AnonymousIdentity
    from invenio_records_resources.services.errors import PermissionDeniedError
    from argiloteca.argiloclay.service import public_record,Unavailable
    app=Flask(__name__)
    for failure in [PermissionDeniedError('read'),RuntimeError('controlled database outage')]:
        reader=SimpleNamespace(read=Mock(side_effect=failure))
        with app.test_request_context('/'),patch('invenio_rdm_records.proxies.current_rdm_records_service',reader):
            g.identity=AnonymousIdentity()
            if isinstance(failure,PermissionDeniedError):assert public_record('abcde-12345') is None
            else:
                try:public_record('abcde-12345')
                except Unavailable:pass
                else:raise AssertionError('Database outage was misclassified')
