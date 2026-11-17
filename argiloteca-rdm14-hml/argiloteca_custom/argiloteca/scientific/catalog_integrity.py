"""Enforce permanent catalog identities on every native UI/API write path."""
import hashlib
from sqlalchemy import text
from marshmallow import ValidationError
from invenio_db import db
from invenio_drafts_resources.services.records.components import ServiceComponent
from invenio_records_resources.services.errors import PermissionDeniedError
from invenio_administration.permissions import administration_permission
from invenio_access.permissions import system_process
from .catalog import FIELD, catalog_rows


class CatalogIntegrityComponent(ServiceComponent):
    def _check(self, identity, data, record):
        fields = data.get('custom_fields') or {}
        previous = (record.get('custom_fields') or {}).get(FIELD) if record else None
        term = fields.get(FIELD)
        if (term is not None or previous is not None) and not (
                system_process in identity.provides or administration_permission.allows(identity)):
            raise PermissionDeniedError('administration-access')
        if previous and (not isinstance(term, dict) or term.get('slug') != previous['slug']):
            raise ValidationError('Catalog identifiers are permanent / O identificador do termo é permanente.', field_name='custom_fields')
        if not isinstance(term, dict) or not isinstance(term.get('slug'), str):
            return
        slug = term['slug']
        db.session.execute(text('SELECT pg_advisory_xact_lock(:key)'),
            {'key': int.from_bytes(hashlib.sha256(slug.encode()).digest()[:8], 'big', signed=True)})
        for row in [*catalog_rows(), *catalog_rows(drafts=True)]:
            # Drafts and published revisions share the native UUID.
            if row.id != getattr(record, 'id', None) and row.json['custom_fields'][FIELD]['slug'] == slug:
                raise ValidationError('Catalog identifier already exists / Identificador de termo já existente.', field_name='custom_fields')

    def create(self, identity, data=None, record=None, **kwargs):
        self._check(identity, data or {}, record)

    def update_draft(self, identity, data=None, record=None, **kwargs):
        self._check(identity, data or {}, record)

    def publish(self, identity, draft=None, record=None, **kwargs):
        self._check(identity, draft, record)
