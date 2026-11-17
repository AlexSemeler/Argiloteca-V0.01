"""Additive fields only; the original 46 field definitions are retained."""
from marshmallow import fields
from invenio_records_resources.services.custom_fields import BaseListCF
from . import PROFILE_FIELD, SEARCH_FIELD


class ProfileCF(BaseListCF):
    def __init__(self):super().__init__(PROFILE_FIELD,field_cls=fields.String)
    @property
    def mapping(self):return {'type':'keyword'}


class ProjectionCF(BaseListCF):
    def __init__(self):super().__init__(SEARCH_FIELD,field_cls=fields.Dict,field_args={'dump_only':True})
    @property
    def mapping(self):
        def nested(names):return {'type':'nested','dynamic':'strict','properties':{name:{'type':kind} for name,kind in names}}
        return {'type':'object','dynamic':'strict','properties':{
            'profile_version':{'type':'keyword'},
            'catalog_slug':{'type':'keyword'},
            'catalog_status':{'type':'keyword'},
            'samples':nested([('code','keyword'),('campaign','keyword'),('latitude','double'),('longitude','double')]),
            'analyses':nested([('id','keyword'),('sample','keyword'),('method','keyword'),('laboratory','keyword')]),
            'minerals':nested([('name','keyword'),('sample','keyword'),('group','keyword'),('latitude','double'),('longitude','double')]),
            'chemistry':nested([('sample','keyword'),('oxide','keyword'),('value','double')]),
        }}
