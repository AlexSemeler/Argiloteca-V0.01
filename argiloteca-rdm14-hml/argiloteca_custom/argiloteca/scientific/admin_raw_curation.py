"""Curatorial preparation of native drafts. This module never publishes records."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import html
import io
import json
import os
from pathlib import Path
import secrets

from argiloteca_drx_core.raw_lifecycle import validate_public_raw_files
from .admin_raw_store import CODE


class CurationBlocked(ValueError):
    pass


def trio_files(repository, row):
    rows = [r for r in repository.rows() if r['sample_code'] == row['sample_code']]
    if any(r.get('test_only') for r in rows):
        raise CurationBlocked('test_only')
    if len(rows) != 3 or {r['preparation'] for r in rows} != set('NGC'):
        raise CurationBlocked('complete_trio_required')
    if any(r['access'] != 'restricted' for r in rows):
        raise CurationBlocked('already_in_public_inventory')
    try:
        files = [(r['filename'], repository.content(r)) for r in sorted(rows, key=lambda r: r['preparation'])]
        if validate_public_raw_files(files) != [row['sample_code']]:
            raise ValueError('Unexpected sample')
    except (OSError, ValueError, KeyError):
        raise CurationBlocked('format_or_integrity_requires_review') from None
    return files


def eligibility(repository, row):
    try:
        trio_files(repository, row)
        return {'eligible': True, 'reason': None}
    except CurationBlocked as error:
        return {'eligible': False, 'reason': str(error)}


def linked_state(link, identity, service=None):
    """Reflect later manual publication/deletion without rewriting source classifications."""
    if not link:
        return None
    if service is None:
        from invenio_rdm_records.proxies import current_rdm_records_service
        service = current_rdm_records_service
    try:
        if service.read(identity, link['draft_id']).to_dict().get('is_published'):
            return 'published'
    except Exception:
        pass
    try:
        service.read_draft(identity, link['draft_id'])
        return 'draft'
    except Exception:
        return 'unavailable'


class CurationLinks:
    """Private, locked journal; a checkpoint prevents duplicate native drafts on retry."""
    def __init__(self, root):
        self.root = Path(root)

    def path(self, code):
        if not CODE.fullmatch(code):
            raise CurationBlocked('invalid_sample')
        return self.root / (code + '.json')

    def read(self, code):
        path = self.path(code)
        return json.loads(path.read_text()) if path.exists() else None

    def write(self, code, value):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.path(code)
        temporary = self.root / ('.pending-' + secrets.token_hex(16))
        try:
            with temporary.open('x') as stream:
                temporary.chmod(0o600)
                json.dump(value, stream, allow_nan=False)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def lock(self, code):
        self.path(code)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / (code + '.lock')).open('a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield


def draft_metadata(form):
    title = str(form.get('title', '')).strip()
    family = str(form.get('family_name', '')).strip()
    given = str(form.get('given_name', '')).strip()
    description = str(form.get('description', '')).strip()
    license_id = form.get('license', '')
    try:
        publication_date = date.fromisoformat(form['publication_date']).isoformat() if form.get('publication_date') else None
    except (TypeError, ValueError):
        raise CurationBlocked('metadata_required') from None
    if not title or len(title) > 300 or (given and not family) or len(family) > 100 or len(given) > 100 or len(description) > 10000 or license_id not in {'', 'cc-by-4.0', 'cc0-1.0'}:
        raise CurationBlocked('metadata_required')
    if any(form.get(key) != 'yes' for key in ('confirm_links', 'confirm_anonymity')) or (license_id and form.get('confirm_rights') != 'yes'):
        raise CurationBlocked('curation_confirmation_required')
    metadata = {'title': title, 'resource_type': {'id': 'dataset'}}
    if publication_date:
        metadata['publication_date'] = publication_date
    if family:
        metadata['creators'] = [{'person_or_org': {'type': 'personal', 'family_name': family, 'given_name': given}}]
    if license_id:
        metadata['rights'] = [{'id': license_id}]
    if description:
        metadata['description'] = '<p>' + html.escape(description).replace('\n', '<br>') + '</p>'
    return {'metadata': metadata, 'access': {'record': 'public', 'files': 'public'}, 'files': {'enabled': True}}


def prepare_draft(repository, row, links, form, identity, *, service=None, uow_factory=None):
    """Only anonymous bytes enter the native service, using the caller's identity."""
    files = trio_files(repository, row)  # No filesystem/DB writes before the publication-byte gate.
    payload = draft_metadata(form)
    fingerprint = hashlib.sha256(b''.join(name.encode() + hashlib.sha256(content).digest() for name, content in files)).hexdigest()
    code = row['sample_code']
    if service is None:
        from invenio_rdm_records.proxies import current_rdm_records_service
        service = current_rdm_records_service
    if uow_factory is None:
        from invenio_records_resources.services.uow import UnitOfWork
        uow_factory = UnitOfWork
    with links.lock(code):
        prior = links.read(code)
        if prior:
            if prior['fingerprint'] != fingerprint:
                raise CurationBlocked('source_changed')
            # Never silently recreate a deleted/published/inaccessible draft.
            service.read_draft(identity, prior['draft_id'])
            return prior
        with uow_factory() as uow:
            draft = service.create(identity, payload, uow=uow)
            record = draft.to_dict()
            allowed_pending = {field for key,field in [('creators','metadata.creators'),('publication_date','metadata.publication_date')]
                               if key not in payload['metadata']}
            if any(error.get('field') not in allowed_pending for error in record.get('errors', [])):
                raise CurationBlocked('native_validation_failed')
            draft_id = record['id']
            service.draft_files.init_files(identity, draft_id, [{'key': name} for name, _ in files], uow=uow)
            for name, content in files:
                result = service.draft_files.set_file_content(identity, draft_id, name,
                    io.BytesIO(content), content_length=len(content), uow=uow)
                if result.to_dict().get('errors'):
                    raise CurationBlocked('native_file_transfer_failed')
                service.draft_files.commit_file(identity, draft_id, name, uow=uow)
            attached = service.draft_files.list_files(identity, draft_id).to_dict().get('entries', [])
            expected = {name: ('md5:' + hashlib.md5(content, usedforsecurity=False).hexdigest(), len(content))
                        for name, content in files}
            if len(attached) != 3 or {f['key'] for f in attached} != set(expected) or any(
                f.get('status') != 'completed' or (f.get('checksum'), f.get('size')) != expected[f['key']]
                for f in attached):
                raise CurationBlocked('native_file_transfer_failed')
            saved = {'schema_version': 1, 'sample_code': code, 'draft_id': draft_id,
                'fingerprint': fingerprint, 'actor_id': str(identity.id),
                'prepared_at': datetime.now(timezone.utc).isoformat(),
                'pending_metadata': sorted(allowed_pending | ({'metadata.rights'} if 'rights' not in payload['metadata'] else set())),
                'files': {name: hashlib.sha256(content).hexdigest() for name, content in files}}
            # Journal before DB commit: after a crash the link requires explicit recovery,
            # never a second draft. A failed transaction leaves no published data.
            links.write(code, saved)
            uow.commit()
        return saved
