"""Consolidate a reviewed, metadata-only pair using native services.

Requires a saved before snapshot. Default mode tests everything and rolls back.
Intentionally refuses files, pending edits, versions or unreviewed differences.
Run in the installed Invenio runtime; never against another deployment's backup.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from invenio_app.factory import create_ui
from invenio_db import db
from invenio_records_resources.services.uow import UnitOfWork
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
from sqlalchemy import text

from argiloteca.openalex.adapters import converter
from argiloteca.openalex.models import OpenAlexClaim, OpenAlexJob
from argiloteca.openalex.service import actor_identity, inventory, matches, tokens


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--before', required=True)
parser.add_argument('--canonical', required=True)
parser.add_argument('--duplicate', required=True)
parser.add_argument('--actor', type=int, required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
before = json.loads(Path(args.before).read_text())
assert set(before) == {args.canonical, args.duplicate}
keep, donor = before[args.canonical], before[args.duplicate]
assert keep['metadata'] == donor['metadata'], 'Bibliographic differences need review.'
assert keep['versions']['index'] == donor['versions']['index'] == 1
assert keep['parent']['id'] != donor['parent']['id']
mineral_field = 'arg:argilominerais'
assert {k:v for k,v in keep['custom_fields'].items() if k != mineral_field} == {
    k:v for k,v in donor['custom_fields'].items() if k != mineral_field}
old_minerals, new_minerals = (r['custom_fields'][mineral_field] for r in (keep, donor))
assert len(old_minerals) == len(new_minerals)
changes = []
for old, new in zip(old_minerals, new_minerals):
    assert old['external_uri'] == new['external_uri'] and old['nome'] == new['nome']
    assert set(old).issubset(new), 'Donor must retain every existing field.'
    for key in set(old) | set(new):
        if old.get(key) != new.get(key):
            assert isinstance(new[key], str) and len(new[key]) >= len(old.get(key) or '')
            if key == 'data_ultima_sincronizacao':
                assert new[key] > old[key]
            changes.append({'mineral':new['nome'], 'field':key, 'before':old.get(key), 'after':new[key]})
payload = {'metadata':deepcopy(keep['metadata']), 'custom_fields':deepcopy(donor['custom_fields']),
           'files':{'enabled':False}, 'media_files':{'enabled':False}}
fields = ('id', 'revision_id', 'metadata', 'custom_fields', 'access', 'pids',
          'parent', 'versions', 'files', 'media_files', 'deletion_status')


class RollbackCheck(Exception):
    pass


def bibliography(data):
    """Vocabulary labels are resolved from IDs by the native relation service."""
    result = deepcopy(data)
    for reference in [result.get('resource_type',{}), *result.get('languages',[])]:
        reference.pop('title',None)
    return result


app = create_ui()
with app.app_context():
    identity = actor_identity(args.actor)
    metadata = converter(app.config['ARGILOTECA_OPENALEX_ROOT'])[0]
    counts = (RDMRecordMetadata.query.count(), RDMDraftMetadata.query.count())
    assert tokens(keep,metadata) == tokens(donor,metadata) and tokens(keep,metadata)
    assert not OpenAlexJob.query.filter(OpenAlexJob.state.in_(['running','queued'])).count()
    journal = {'mode':'applied' if args.apply else 'rollback_test',
               'canonical':args.canonical, 'duplicate':args.duplicate,
               'identity':sorted(tokens(keep,metadata)), 'mineral_changes':changes,
               'time':datetime.now(timezone.utc).isoformat()}
    try:
        with UnitOfWork() as uow:
            # Same lock as imports. Native revisions also detect external edits.
            db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
            for pid in (args.canonical, args.duplicate):
                current = service.read(identity,pid)
                db.session.query(RDMRecordMetadata).filter_by(id=current._record.id).with_for_update().one()
                current_data = current.to_dict()
                assert {k:current_data.get(k) for k in fields} == {k:before[pid].get(k) for k in fields}, 'Snapshot changed: '+pid
                for category in ('files','media_files'):
                    assert not current_data[category]['enabled']
                    assert not current_data[category]['count'] and not current_data[category]['entries']
                draft = db.session.get(RDMDraftMetadata,current._record.id)
                assert not draft or not draft.json, 'Pending edit requires review: '+pid
            edited = service.edit(identity,args.canonical,uow=uow)
            updated = service.update_draft(identity,args.canonical,payload,
                revision_id=edited._record.revision_id,uow=uow)
            assert not updated.to_dict().get('errors'), updated.to_dict().get('errors')
            published = service.publish(identity,args.canonical,uow=uow)
            result = published.to_dict()
            Path(args.output+'.proposed.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
            assert result['id'] == args.canonical and result['versions'] == keep['versions']
            assert bibliography(result['metadata']) == bibliography(keep['metadata'])
            assert result['custom_fields'] == donor['custom_fields']
            for key in ('access','pids','files','media_files','parent'):
                assert result[key] == keep[key], 'Unexpected native change: '+key
            # Test that retained edit JSON cannot resurrect a deleted publication
            # in future imports. This edit is created only in the rollback test.
            if not args.apply:
                service.edit(identity,args.duplicate,uow=uow)
            tombstone = {
                'removal_reason':{'id':'duplicate'}, 'is_visible':True,
                'note':'Registro consolidado em https://127.0.0.1:5101/records/'+args.canonical+
                    '. Metadados mais completos preservados no registro principal; cópia anterior no backup local de 23/10/2026.',
                'citation_text':keep['metadata']['title']+' — '+', '.join(sorted(tokens(keep,metadata)))+'. Registro principal: '+args.canonical,
            }
            deleted = service.delete_record(identity,args.duplicate,tombstone,
                revision_id=before[args.duplicate]['revision_id'],uow=uow)
            db.session.flush()
            assert deleted._record.deletion_status.is_deleted
            # Repoint historical claims if the reviewed pair ever acquired one.
            for claim in OpenAlexClaim.query.filter_by(draft_id=args.duplicate):
                assert claim.token in tokens(result,metadata)
                claim.draft_id = args.canonical
            db.session.flush()
            found = matches({'payload':result},inventory(metadata),metadata)
            assert {m['id'] for m in found} == {args.canonical}, found
            assert (RDMRecordMetadata.query.count(), RDMDraftMetadata.query.count()) == counts
            journal.update({'canonical_after':result, 'duplicate_tombstone':deleted.to_dict(),
                            'importer_matches':found, 'files_in_pair':0, 'native_rows_preserved':True})
            if not args.apply:
                raise RollbackCheck()
            uow.commit()
    except RollbackCheck:
        pass
    db.session.expire_all()
    if not args.apply:
        for pid in (args.canonical,args.duplicate):
            current = service.read(identity,pid).to_dict()
            assert {k:current.get(k) for k in fields} == {k:before[pid].get(k) for k in fields}
        journal['rollback_verified'] = True
    else:
        persisted = service.read(identity,args.canonical).to_dict()
        assert persisted['custom_fields'] == donor['custom_fields']
        assert bibliography(persisted['metadata']) == bibliography(keep['metadata'])
        assert service.record_cls.pid.resolve(args.duplicate).deletion_status.is_deleted
        journal['persistence_verified'] = True
    Path(args.output).write_text(json.dumps(journal,ensure_ascii=False,indent=2,default=str))
    print(json.dumps({k:v for k,v in journal.items() if k not in
        ('canonical_after','duplicate_tombstone','mineral_changes')},ensure_ascii=False))
