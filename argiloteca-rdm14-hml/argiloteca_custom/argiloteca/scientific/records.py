"""Native record subclasses with a reversible index-only scientific projection."""
from copy import copy,deepcopy
from invenio_records.systemfields import DictField
from invenio_records.dictutils import clear_none
from invenio_rdm_records.records.api import RDMRecord, RDMDraft
from invenio_records.dumpers import SearchDumperExt
from . import SEARCH_FIELD, PROFILE_FIELD
from .models import projection, BINDINGS


class ScienceDumperExt(SearchDumperExt):
    def dump(self,record,data):
        original=record.get('custom_fields') or {}
        target=data.setdefault('custom_fields',{})
        if PROFILE_FIELD in original:
            for name in BINDINGS:target.pop(name,None)
            # Only the explicitly mapped projection is searchable. Scientific
            # originals live in SQL, avoiding dynamic-field explosion and type
            # conflicts in historical indices. Native reads/XML use SQL.
            if not isinstance(original.get(PROFILE_FIELD),str):target.pop(PROFILE_FIELD,None)
        target[SEARCH_FIELD]=projection(original)
    def load(self,data,record_cls):
        (data.get('custom_fields') or {}).pop(SEARCH_FIELD,None)


def scientific_dumper(original):
    # Keep every extension and model field from the installed native dumper.
    dumper=copy(original)
    dumper._extensions=[*original._extensions,ScienceDumperExt()]
    return dumper


class ScientificFields(DictField):
    def __init__(self):super().__init__(clear_none=False,create_if_missing=True)
    def __set__(self,record,value):
        value=deepcopy(value)
        if PROFILE_FIELD not in value:clear_none(value)
        super().__set__(record,value)


class ScientificValues:
    def clear_none(self,key=None):
        fields=self.get('custom_fields') or {}
        preserved=deepcopy(fields) if PROFILE_FIELD in fields and key in {None,'custom_fields'} else None
        super().clear_none(key)
        if preserved is not None:self['custom_fields']=preserved


class ScientificRecord(ScientificValues,RDMRecord):
    custom_fields=ScientificFields()
    dumper=scientific_dumper(RDMRecord.dumper)


class ScientificDraft(ScientificValues,RDMDraft):
    custom_fields=ScientificFields()
    dumper=scientific_dumper(RDMDraft.dumper)
