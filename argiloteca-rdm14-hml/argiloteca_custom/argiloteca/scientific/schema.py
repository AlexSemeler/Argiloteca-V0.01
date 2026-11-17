"""Native schema plus lossless opt-in draft data and strict publication rules."""
from collections.abc import Mapping
from invenio_rdm_records.services.schemas.record import RDMRecordSchema
from invenio_records_resources.services.custom_fields import CustomFieldsSchema
from marshmallow_utils.fields import NestedAttribute
from marshmallow import Schema, fields, validates_schema, ValidationError
from . import PROFILE_FIELD
from .models import BINDINGS, marshmallow_errors


class ScientificCustomFieldsSchema(CustomFieldsSchema):
    def __init__(self,*args,**kwargs):
        super().__init__('RDM_CUSTOM_FIELDS',*args,**kwargs)
        # Raw is intentionally restricted to explicitly profiled drafts. The
        # JSON Schema validator reports errors without discarding their values.
        definitions=dict(self.fields)
        for name in {*BINDINGS,PROFILE_FIELD}:definitions[name]=fields.Raw(allow_none=True)
        self._scientific_schema=Schema.from_dict(definitions)()
    def _deserialize(self,data,**kwargs):
        if isinstance(data,Mapping) and PROFILE_FIELD in data:
            return self._scientific_schema.load(data=data)
        return super()._deserialize(data,**kwargs)
    def _serialize(self,obj,**kwargs):
        if isinstance(obj,Mapping) and PROFILE_FIELD in obj:
            return self._scientific_schema.dump(obj)
        return super()._serialize(obj,**kwargs)


class ScientificRecordSchema(RDMRecordSchema):
    custom_fields=NestedAttribute(ScientificCustomFieldsSchema)
    @validates_schema(skip_on_field_errors=False)
    def scientific_profile(self,data,**kwargs):
        errors=marshmallow_errors(data.get('custom_fields') or {})
        if errors:raise ValidationError(errors)
