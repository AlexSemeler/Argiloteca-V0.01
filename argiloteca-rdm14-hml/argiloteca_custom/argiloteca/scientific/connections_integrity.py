"""Guard curatorial connections on native draft/UI/API write paths."""
from copy import deepcopy
from marshmallow import ValidationError
from jsonschema import ValidationError as SchemaValidationError
from invenio_access.permissions import system_process
from invenio_administration.permissions import administration_permission
from invenio_drafts_resources.services.records.components import ServiceComponent
from invenio_records_resources.services.errors import PermissionDeniedError
from .connections import FIELD, validate_links, reconcile_native_relations, lock_connection_writes


class ConnectionsIntegrityComponent(ServiceComponent):
    def check(self, identity, data, record):
        previous = deepcopy((record.get('custom_fields') or {}).get(FIELD) or []) if record else []
        fields = data.setdefault('custom_fields', {})
        if FIELD not in fields and previous:
            fields[FIELD] = deepcopy(previous)
        links = fields.get(FIELD) or []
        if previous or links:
            lock_connection_writes()
        if links and 'arg:termo_catalogo' in fields:
            raise ValidationError('Select a bibliographic record or dataset / Selecione um registro bibliográfico ou conjunto de dados.', field_name='custom_fields')
        if links != previous:
            if not (system_process in identity.provides or administration_permission.allows(identity)):
                raise PermissionDeniedError('administration-access')
            try:
                validate_links(identity, str(record.get('id', '')) if record else '', links, previous)
            except (ValueError, SchemaValidationError) as error:
                raise ValidationError(str(error), field_name='custom_fields') from error
        if previous or links:
            metadata, links = reconcile_native_relations(data.get('metadata') or (record.get('metadata') if record else {}) or {}, previous, links)
            data['metadata'] = metadata
            data.setdefault('custom_fields', {})[FIELD] = links

    def create(self, identity, data=None, record=None, **kwargs):
        self.check(identity, data, record)

    def update_draft(self, identity, data=None, record=None, **kwargs):
        self.check(identity, data, record)

    def publish(self, identity, draft=None, record=None, **kwargs):
        self.check(identity, draft, record)
