"""Idempotent, additive homologation installation. Never rewrites record JSON."""
import json
from invenio_app.factory import create_ui
from invenio_access.permissions import system_identity
from invenio_db import db
from invenio_search import current_search_client
from invenio_vocabularies.proxies import current_service as vocabularies
from invenio_vocabularies.records.models import VocabularyType
from invenio_pidstore.errors import PIDDoesNotExistError
from . import PROFILE_FIELD, PROFILE_VERSION, SEARCH_FIELD

METHODS = {
 'drx':('X-ray diffraction','Difração de raios X'), 'xrd':('X-ray diffraction (XRD)','Difração de raios X (XRD)'),
 'geoquimica':('Geochemistry','Geoquímica'), 'frx':('X-ray fluorescence','Fluorescência de raios X'),
 'icp':('Inductively coupled plasma','Plasma indutivamente acoplado'), 'mev':('Scanning electron microscopy','Microscopia eletrônica de varredura'),
 'ftir':('Fourier transform infrared spectroscopy','Espectroscopia no infravermelho por transformada de Fourier'),
 'granulometria':('Particle size analysis','Granulometria'), 'extracao_pdf':('PDF extraction','Extração de PDF'), 'outro':('Other','Outro'),
}

def install(app):
    report={'profile_version':PROFILE_VERSION,'mappings':[],'vocabularies':[],'content_migration':'none'}
    fields={f.name:f for f in app.config['RDM_CUSTOM_FIELDS']}
    names=['arg:conexoes_cientificas','arg:termo_catalogo',PROFILE_FIELD,SEARCH_FIELD,'arg:pacotes_analiticos','arg:referencias_drx_webmineral']
    aliases=[app.config['SEARCH_INDEX_PREFIX']+cls.index._name for cls in [app.config['RDM_RECORD_CLS'],app.config['RDM_DRAFT_CLS']]]
    percolator=aliases[0]+'-percolators'
    if current_search_client.indices.exists(index=percolator):aliases.append(percolator)
    for alias in aliases:
        existing=current_search_client.indices.get_mapping(index=alias)
        for index,mapping in existing.items():
            properties=mapping['mappings']['properties'].get('custom_fields',{}).get('properties',{})
            updates={}
            for name in names:
                wanted=fields[name].mapping
                actual=properties.get(name)
                if name==PROFILE_FIELD and actual and actual.get('type') in {'keyword','text'}:
                    # An early disposable probe let OpenSearch infer text in the
                    # draft index. Keep it: exact filters use the nested projection.
                    continue
                if actual is None:updates[name]=wanted
                elif name in {'arg:conexoes_cientificas','arg:termo_catalogo','arg:pacotes_analiticos','arg:referencias_drx_webmineral'} and actual.get('enabled') is not False:raise RuntimeError('Expected unindexed object: '+name)
                elif name==SEARCH_FIELD and actual.get('type','object')!='object':raise RuntimeError('Incompatible scientific index; no destructive migration attempted.')
                elif name==SEARCH_FIELD:
                    if any(key not in actual.get('properties',{}) for key in ('catalog_slug','catalog_status')):
                        updates[name] = wanted
                    for branch in ['samples','analyses','minerals','chemistry']:
                        if actual.get('properties',{}).get(branch,{}).get('type')!='nested':raise RuntimeError('Expected nested scientific mapping: '+branch)
            if updates:current_search_client.indices.put_mapping(index=index,body={'properties':{'custom_fields':{'properties':updates}}})
            report['mappings'].append({'index':index,'added':list(updates),'verified':names})
    for type_id,pid_type,entries in [
        ('argprofiles','argpr',{PROFILE_VERSION:('Experimental scientific profile','Perfil científico experimental')}),
        ('argmethods','argmd',METHODS),
    ]:
        if db.session.get(VocabularyType,type_id) is None:
            vocabularies.create_type(system_identity,type_id,pid_type)
            db.session.commit()
        for id_,(en,pt) in entries.items():
            payload={'id':id_,'type':type_id,'title':{'en':en,'pt':pt}}
            try:item=vocabularies.read(system_identity,(type_id,id_))
            except PIDDoesNotExistError:
                vocabularies.create(system_identity,payload)
            else:
                if item.to_dict().get('title')!=payload['title']:
                    current=item.to_dict();current.update(payload)
                    vocabularies.update(system_identity,(type_id,id_),current)
        report['vocabularies'].append({'type':type_id,'count':len(entries)})
    return report

if __name__=='__main__':
    app=create_ui()
    with app.app_context():print(json.dumps(install(app),ensure_ascii=False,indent=2))
