"""Native set-query hook without dynamic percolation of full record payloads."""
from flask import current_app,g,request,Response
from lxml import etree
from invenio_oaiserver.proxies import current_oaiserver
from invenio_oaiserver.models import OAISet


def validate_prefix():
    """Use the protocol error for an unsupported format (native returns badArgument)."""
    if request.endpoint!='invenio_oaiserver.response':return None
    prefix=request.values.get('metadataPrefix')
    if request.values.get('verb') not in {'GetRecord','ListRecords','ListIdentifiers'}:return None
    if prefix and prefix not in current_app.config['OAISERVER_METADATA_FORMATS'] and not request.values.get('resumptionToken'):
        from invenio_oaiserver import response as xml
        return Response(etree.tostring(xml.error([('cannotDisseminateFormat','Unsupported metadata format.')])),status=422,mimetype='text/xml')


def sets_for_record(record):
    source=record.get('_source',record)
    if source.get('access',{}).get('record')!='public':return []
    if not hasattr(g,'argiloteca_oai_sets'):
        g.argiloteca_oai_sets=[row.spec for row in OAISet.query.order_by(OAISet.spec).all()]
    result=[]
    for spec in g.argiloteca_oai_sets:
        query=current_oaiserver.set_records_query_fetcher(spec)
        search=current_oaiserver.search_cls(index=current_app.config['OAISERVER_RECORD_INDEX'])
        if search.filter('term',id=source['id']).query(query).count():result.append(spec)
    return result
