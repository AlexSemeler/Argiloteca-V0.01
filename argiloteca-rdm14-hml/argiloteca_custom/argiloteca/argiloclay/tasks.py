"""Scheduled public-metadata refresh. No attachment downloads or privileged reads."""
import json
import os
from celery import shared_task
from flask import current_app
from flask_principal import AnonymousIdentity
from invenio_access.permissions import any_user
from .index_sync import synchronize
from .public_metadata import project
from . import batch_sync


def public_records():
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_records_resources.services.errors import PermissionDeniedError, RecordPermissionDeniedError
    from invenio_pidstore.errors import PIDDeletedError,PIDDoesNotExistError
    from invenio_rdm_records.services.errors import RecordDeletedException
    identity=AnonymousIdentity();identity.provides.add(any_user)
    base=current_app.config['SITE_UI_URL']
    # Native scan applies visibility/latest-version filters. Read each hit again
    # against the database, so stale search entries cannot grant current access.
    result=service.scan(identity,params={})
    for hit in result._results:
        rid=hit.to_dict().get('id')
        if not rid:raise ValueError('Public scan without persistent identifier')
        try:item=service.read(identity,rid)
        except (PermissionDeniedError,RecordPermissionDeniedError,PIDDeletedError,PIDDoesNotExistError,RecordDeletedException):continue
        if item._record.get('access',{}).get('record')!='public':continue
        # Use the anonymous API schema as well as record-level permission checks.
        # Raw SQL/JSON may contain fields that the public schema does not expose.
        yield project(item.to_dict(),base)


def public_batch(checkpoint, size):
    """Enumerate registered native IDs; resolve all content with anonymous access.

    Search indexes can lag a restored/changed database. Only the native ID join
    is privileged here; bibliographic content always comes from service.read's
    anonymous public schema. No raw metadata or attachments are exported.
    """
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_records_resources.services.errors import PermissionDeniedError, RecordPermissionDeniedError
    from invenio_pidstore.errors import PIDDeletedError, PIDDoesNotExistError
    from invenio_rdm_records.services.errors import RecordDeletedException
    from invenio_pidstore.models import PersistentIdentifier, PIDStatus
    from invenio_rdm_records.records.models import RDMRecordMetadata
    from invenio_db import db
    from sqlalchemy import select
    identity = AnonymousIdentity(); identity.provides.add(any_user)
    fields={'id','updated','created','metadata','custom_fields','pids','access',
            'versions','is_published','is_draft','deletion_status'}
    selected=tuple(fields & set(service.schema.schema().fields))
    identifiers = db.session.execute(select(PersistentIdentifier.pid_value).join(
        RDMRecordMetadata, PersistentIdentifier.object_uuid == RDMRecordMetadata.id
    ).where(PersistentIdentifier.pid_type == 'recid', PersistentIdentifier.status == PIDStatus.REGISTERED
    ).order_by(PersistentIdentifier.pid_value).execution_options(yield_per=100)).scalars()
    rows = []
    try:
        for rid in identifiers:
            if checkpoint.execute('SELECT 1 FROM sync_seen WHERE rid=?', (rid,)).fetchone():
                continue
            if len(rows) == size:
                return rows, False
            try:
                item = service.read(identity, rid)
            except (PermissionDeniedError, RecordPermissionDeniedError, PIDDeletedError, PIDDoesNotExistError, RecordDeletedException):
                continue
            if item._record.get('access', {}).get('record') != 'public':
                continue
            # Use the same permission-aware native schema, restricted to the
            # projection's fields. Dumping stats/files/links needlessly performs
            # thousands of extra search requests and was a major timeout cost.
            data=item._schema.dump(item._record,schema_args={'only':selected},
                                   context={'identity':identity,'record':item._record})
            if data.get('versions', {}).get('is_latest') is False:
                continue
            rows.append(project(data, current_app.config['SITE_UI_URL']))
        return rows, True
    finally:
        identifiers.close()


@shared_task(ignore_result=True, soft_time_limit=250, time_limit=270)
def sync_public_records(run_id=None):
    path=os.environ.get('ARGILOCLAY_SYNC_INDEX')
    if not path:return {'state':'disabled'}
    status = batch_sync.state(path)
    if run_id is not None and (run_id != status.get('run_id') or status.get('state')=='ok'):
        return status
    if status.get('state') == 'restart_required':
        return status
    if status.get('state') not in ('running', 'paused', 'failed'):
        status = batch_sync.start(path)
    run_id = status['run_id']
    try:
        result = batch_sync.step(path, public_batch)
    except batch_sync.CheckpointConflict:
        # A deliberate safety stop is actionable in the administration, not a
        # repeating opaque ValueError in the hourly scheduler.
        return batch_sync.state(path)
    current_app.logger.info('ArgiloClay public synchronization: %s',json.dumps(result))
    if result.get('state') == 'running':
        sync_public_records.apply_async(args=[run_id],countdown=1)
    elif result.get('state') == 'busy':
        sync_public_records.apply_async(args=[run_id],countdown=5)
    return result


def configure(app):
    if not os.environ.get('ARGILOCLAY_SYNC_INDEX'):return
    imports=list(app.config.get('CELERY_IMPORTS',()))
    if __name__ not in imports:imports.append(__name__)
    app.config['CELERY_IMPORTS']=tuple(imports)
    app.config['CELERY_IMPORTS'] += ('argiloteca.argiloclay.admin',)
    schedule=app.config.setdefault('CELERY_BEAT_SCHEDULE',{})
    schedule['argiloclay-public-metadata']={'task':__name__+'.sync_public_records',
        'schedule':max(3600.0,min(86400.0,float(os.environ.get('ARGILOCLAY_SYNC_INTERVAL_SECONDS','3600')))),'options':{'expires':240}}
