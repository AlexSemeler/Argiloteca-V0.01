"""Scientific native-service filters keep correlated values within the same item."""
from invenio_drafts_resources.services.records.components import ServiceComponent
from invenio_search.engine import dsl
from . import SEARCH_FIELD


class ScientificSearchComponent(ServiceComponent):
    def search(self,identity,search,params):
        base='custom_fields.'+SEARCH_FIELD
        profile=params.get('arg_profile')
        if profile:search=search.filter('term',**{base+'.profile_version':profile})
        for branch,keys in [('samples',{'arg_sample':'code','arg_campaign':'campaign'}),('analyses',{'arg_method':'method','arg_laboratory':'laboratory'}),('minerals',{'arg_mineral':'name','arg_mineral_sample':'sample','arg_mineral_latitude':'latitude'})]:
            must=[dsl.Q('term',**{base+'.'+branch+'.'+target:params[key]}) for key,target in keys.items() if params.get(key) is not None and params[key]!='']
            if must:search=search.filter('nested',path=base+'.'+branch,query=dsl.Q('bool',must=must))
        for branch,field in [('samples','campaign'),('analyses','method'),('minerals','name')]:
            search.aggs.bucket('arg_'+branch,'nested',path=base+'.'+branch).bucket('values','terms',field=base+'.'+branch+'.'+field,size=30)
        return search
    def search_drafts(self,identity,search,params):return self.search(identity,search,params)
