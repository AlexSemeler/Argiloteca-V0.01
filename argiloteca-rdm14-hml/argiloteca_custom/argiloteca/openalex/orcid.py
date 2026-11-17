"""ORCID suggestions and strictly additive, reviewed native creator updates."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
import zipfile

import requests
from flask import current_app
from invenio_db import db
from marshmallow import ValidationError
from sqlalchemy import text

from .adapters import digest
from .analytics import connect, creator_name, doi_of, name_key, path_for
from .duplicates import fingerprint, sha256_file
from .models import OpenAlexJob
from .orcid_messages import ERRORS
from .service import actor_identity, native_payload


class ReviewError(ValueError):
    def __init__(self, message, english=None):
        super().__init__(message)
        self.message_en = english or ERRORS[message]


def normalize_orcid(value):
    value = re.sub(r'^https?://orcid.org/', '', str(value or '').strip(), flags=re.I).upper()
    if not re.fullmatch(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]', value): return None
    digits=value.replace('-','');total=0
    for digit in digits[:-1]: total=(total+int(digit))*2
    check=(12-total%11)%11
    return value if digits[-1]==('X' if check==10 else str(check)) else None


def quote(value):
    value=str(value or '').strip()
    if len(value)>250 or any(ord(c)<32 for c in value): raise ReviewError('Consulta excede o limite ou contém controles.')
    return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'


def request_public(path, params=None):
    if not re.fullmatch(r'(?:expanded-search/|\d{4}-\d{4}-\d{4}-\d{3}[\dX]/(?:person|works))', path):
        raise ReviewError('Recurso ORCID inválido.')
    headers={'Accept':'application/json','User-Agent':'Argiloteca-ORCID-review/1.0'}
    token=current_app.config.get('ARGILOTECA_ORCID_READ_PUBLIC_TOKEN')
    if token: headers['Authorization']='Bearer '+token
    try:
        with requests.get('https://pub.orcid.org/v3.0/'+path,params=params,headers=headers,
                          timeout=(8,25),stream=True,allow_redirects=False) as response:
            if response.status_code in (401,403):
                raise ReviewError('ORCID exige autorização nesta consulta. Configure ARGILOTECA_ORCID_READ_PUBLIC_TOKEN no ambiente local ou use a busca no site oficial.')
            if response.status_code==429: raise ReviewError('Limite temporário do ORCID. Aguarde antes de tentar novamente.')
            if response.status_code!=200: raise ReviewError('ORCID indisponível ou perfil não encontrado. Tente novamente.')
            content=bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content)>8*1024*1024: raise ReviewError('Resposta ORCID excedeu 8 MiB. Refine a consulta.')
            return json.loads(content)
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise ReviewError('Não foi possível consultar o ORCID. A prévia local continua preservada.') from exc


def search(job):
    """Only names/affiliations/DOIs supplied in the admin search are transmitted."""
    p=job.params;clauses=[]
    if p.get('given'):clauses.append('given-names:'+quote(p['given']))
    if p.get('family'):clauses.append('family-name:'+quote(p['family']))
    if not clauses:raise ReviewError('Informe nome ou sobrenome para buscar.')
    if p.get('institution'):clauses.append('affiliation-org-name:'+quote(p['institution']))
    if p.get('doi'):clauses.append('digital-object-ids:'+quote(p['doi']))
    query=' AND '.join(clauses)
    raw=request_public('expanded-search/',{'q':query,'rows':20,'start':p.get('start',0)})
    candidates=[]
    for row in raw.get('expanded-result') or []:
        orcid=normalize_orcid(row.get('orcid-id'))
        if orcid:
            candidates.append({'orcid':orcid,'name':row.get('credit-name') or ' '.join(filter(None,[row.get('given-names'),row.get('family-names')])),
                'institutions':row.get('institution-name') or [],'method':'Busca pública ORCID; identidade exige revisão'})
    job.snapshot={'candidates':candidates,'query':query,'fetched_at':datetime.now(timezone.utc).isoformat()}
    job.result={'total':raw.get('num-found',0)};job.state='review'


def lookup(job):
    orcid=normalize_orcid(job.params.get('orcid'))
    if not orcid:raise ReviewError('ORCID inválido, incluindo dígito verificador.')
    person=request_public(orcid+'/person');name=person.get('name') or {}
    label=(name.get('credit-name') or {}).get('value') or ' '.join(filter(None,[(name.get('given-names') or {}).get('value'),(name.get('family-name') or {}).get('value')]))
    works=request_public(orcid+'/works');dois=set()
    for group in works.get('group') or []:
        for external in (group.get('external-ids') or {}).get('external-id') or []:
            if external.get('external-id-type')=='doi':
                dois.add(re.sub(r'^https?://(?:dx\.)?doi.org/','',str(external.get('external-id-value','')),flags=re.I).lower())
    job.snapshot={'candidates':[{'orcid':orcid,'name':label,'institutions':[],
        'dois':sorted(dois),'method':'Registro público ORCID; DOI pode apoiar a revisão'}],
        'fetched_at':datetime.now(timezone.utc).isoformat()}
    job.result={};job.state='review'


def add_identifier(creators, slots, orcid):
    """Update exactly existing slots; never append, rename, reorder or merge authors."""
    orcid=normalize_orcid(orcid)
    if not orcid:raise ReviewError('ORCID inválido.')
    result=deepcopy(creators)
    for slot in set(slots):
        if not isinstance(slot,int) or not 0<=slot<len(result):raise ReviewError('Autor não está mais nesta posição.')
        person=result[slot].get('person_or_org') or {}
        if person.get('type')!='personal':raise ReviewError('ORCID se aplica somente a pessoa.')
        old=[normalize_orcid(x.get('identifier')) for x in person.get('identifiers',[]) if x.get('scheme')=='orcid']
        if any(x!=orcid for x in old):raise ReviewError('O autor já possui outro ORCID. Nenhum identificador será substituído.')
        if not old:person.setdefault('identifiers',[]).append({'scheme':'orcid','identifier':orcid})
    # One ORCID cannot be assigned to two separate author slots in a record.
    for i,creator in enumerate(result):
        if i not in slots and any(normalize_orcid(x.get('identifier'))==orcid for x in creator.get('person_or_org',{}).get('identifiers',[]) if x.get('scheme')=='orcid'):
            raise ReviewError('Este ORCID já pertence a outro autor no mesmo registro. Revise a autoria sem duplicar vínculos.')
    if len(set(slots))>1:raise ReviewError('O mesmo ORCID não pode identificar dois autores no mesmo registro.')
    return result


def read_native(identity, rid, kind):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_rdm_records.records.models import RDMDraftMetadata
    result=(service.read if kind=='published' else service.read_draft)(identity,rid)
    record=result._record
    if kind=='published':
        if record.model.deletion_status.value!='P':raise ReviewError('Registro retirado ou excluído.')
        draft=db.session.get(RDMDraftMetadata,record.id)
        if draft and draft.json:raise ReviewError('Há uma edição em rascunho. Revise essa edição antes de alterar a publicação.')
    data=result.to_dict()
    if data.get('parent',{}).get('review'):raise ReviewError('Há revisão pendente neste registro.')
    return record,data,digest({'record':fingerprint(data),'raw':dict(record),'parent':dict(record.parent),'revision':record.revision_id,'parent_revision':record.parent.revision_id})


def prepare_plan(analysis, keys, orcid, evidence, actor):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from .analytics import file_hash
    if not keys or len(keys)>100 or len(set(keys))!=len(keys):raise ReviewError('Selecione de 1 a 100 ocorrências distintas.')
    if file_hash(path_for(analysis.id))!=analysis.snapshot['sha256']:raise ReviewError('Análise alterada. Atualize os autores.')
    identity=actor_identity(actor);records={};occurrences=[]
    with connect(analysis) as c:
        for key in keys:
            row=c.execute('SELECT * FROM occurrences WHERE key=?',(key,)).fetchone()
            if not row:raise ReviewError('Ocorrência fora da análise.')
            row=dict(row);pair=(row['rid'],row['kind'])
            if pair not in records:
                record,data,stamp=read_native(identity,*pair)
                records[pair]={'id':row['rid'],'kind':row['kind'],'uuid':str(record.id),'parent_uuid':str(record.parent.id),
                    'before':data,'raw':deepcopy(dict(record)),'parent_raw':deepcopy(dict(record.parent)),'fingerprint':stamp,'slots':[]}
            item=records[pair];creators=item['before']['metadata']['creators']
            if row['slot']>=len(creators) or creators[row['slot']]!=json.loads(row['creator']):raise ReviewError('A autoria mudou desde a análise. Atualize os autores.')
            item['slots'].append(row['slot']);occurrences.append(row)
    for item in records.values():
        item['after_creators']=add_identifier(item['before']['metadata']['creators'],item['slots'],orcid)
        item['changed']=item['after_creators']!=item['before']['metadata']['creators']
        # An already present ORCID is a no-op, even on an incomplete legacy draft.
        if not item['changed']:continue
        # Native schema validation, including checksum-valid ORCID identifier.
        payload=edit_payload(item['before'],item['after_creators'])
        service.require_permission(identity,'update_draft',record=service.record_cls.get_record(uuid.UUID(item['uuid'])) if item['kind']=='published' else service.draft_cls.get_record(uuid.UUID(item['uuid'])))
        try:
            service.schema.load(native_payload(service,payload),context={'identity':identity},raise_errors=True)
        except ValidationError as exc:
            raise ReviewError('Revise os metadados obrigatórios do registro '+item['id']+' antes de vincular ORCID: '+json.dumps(exc.messages,ensure_ascii=False,default=str),
                'Review required metadata for record '+item['id']+' before linking ORCID: '+json.dumps(exc.messages,ensure_ascii=False,default=str)) from exc
    return {'schema':1,'analysis':analysis.id,'orcid':normalize_orcid(orcid),'evidence':evidence,
        'records':list(records.values()),'occurrences':occurrences,'created_at':datetime.now(timezone.utc).isoformat()}


def edit_payload(before, creators):
    result={k:deepcopy(before[k]) for k in ('metadata','custom_fields') if k in before}
    result['metadata']['creators']=deepcopy(creators)
    for category in ('files','media_files'):
        result[category]={k:deepcopy(before.get(category,{}).get(k)) for k in ('enabled','default_preview') if k in before.get(category,{})}
    return result


def verify_addition(before,after,creators):
    from .publication import preserved
    expected=deepcopy(before);expected['metadata']['creators']=creators
    preserved(expected,after)
    if before.get('pids')!=after.get('pids'):raise ReviewError('Identificadores do registro mudaram inesperadamente.')


def backup_path(job_id):
    if not re.fullmatch('[0-9a-f]{32}',job_id):raise ReviewError('Backup inválido.')
    folder=Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])/'orcid-backups';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    return folder/(job_id+'.zip')


def backup(job,identity):
    path=backup_path(job.id);known=job.result.get('backup')
    if known:
        if not path.is_file() or path.is_symlink() or sha256_file(path)!=known['sha256']:raise ReviewError('Backup ausente ou alterado.')
        return known
    if path.exists():raise ReviewError('Há backup anterior sem confirmação. Prepare outra prévia.')
    fd,tmp=tempfile.mkstemp(prefix='.orcid-',dir=path.parent);manifest={'schema':1,'job':job.id,'plan_sha256':job.params['plan_sha256'],'plan':job.snapshot,'review':job.params.get('review'),'files':[]}
    try:
        with os.fdopen(fd,'w+b') as target,zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as z:
            for row in job.snapshot['records']:
                record,data,stamp=read_native(identity,row['id'],row['kind'])
                if stamp!=row['fingerprint']:raise ReviewError('Registro mudou antes do backup. Prepare outra prévia.')
                for category in ('files','media_files'):
                    for key,entry in data.get(category,{}).get('entries',{}).items():
                        algorithm,expected=entry['checksum'].split(':',1);checksum=hashlib.new(algorithm);size=0;name='files/'+str(len(manifest['files']))+'.bin'
                        with getattr(record,category)[key].open_stream('rb') as source,z.open(name,'w',force_zip64=True) as dest:
                            while chunk:=source.read(1048576):dest.write(chunk);checksum.update(chunk);size+=len(chunk)
                        if checksum.hexdigest()!=expected or size!=entry['size']:raise ReviewError('Arquivo diverge do checksum; nenhum vínculo aplicado.')
                        manifest['files'].append({'id':row['id'],'category':category,'key':key,'archive':name,'checksum':entry['checksum'],'size':size})
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,default=str))
        with open(tmp,'rb') as stream:os.fsync(stream.fileno())
        os.chmod(tmp,0o600)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip():raise ReviewError('Backup inválido.')
        os.replace(tmp,path)
        return {'filename':path.name,'sha256':sha256_file(path),'bytes':path.stat().st_size}
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def apply(job):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_rdm_records.records.models import RDMRecordMetadata,RDMDraftMetadata,RDMParentMetadata
    from invenio_records_resources.services.uow import UnitOfWork
    from .publication import validate
    plan=job.snapshot
    if digest(plan)!=job.params['plan_sha256']:raise ReviewError('Prévia alterada.')
    source=db.session.get(OpenAlexJob,job.params['preview_job'])
    if not source or source.actor!=job.actor or source.kind!='orcid_preview' or source.snapshot!=plan:raise ReviewError('Prévia de origem inválida.')
    identity=actor_identity(job.actor)
    job.result={**job.result,'backup':backup(job,identity)};db.session.commit()
    with UnitOfWork() as uow:
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
        for row in sorted(plan['records'],key=lambda r:r['uuid']):
            db.session.query(RDMParentMetadata).filter_by(id=uuid.UUID(row['parent_uuid'])).with_for_update().one()
            db.session.query(RDMRecordMetadata).filter_by(id=uuid.UUID(row['uuid'])).with_for_update().all()
            db.session.query(RDMDraftMetadata).filter_by(id=uuid.UUID(row['uuid'])).with_for_update().all()
        db.session.expire_all();db.session.refresh(source)
        if source.state!='review':raise ReviewError('Prévia já aplicada ou indisponível.')
        count=0
        for row in plan['records']:
            record,before,stamp=read_native(identity,row['id'],row['kind'])
            if stamp!=row['fingerprint']:raise ReviewError('Registro, autoria ou vínculos mudaram desde a prévia. Nenhuma alteração aplicada.')
            creators=add_identifier(before['metadata']['creators'],row['slots'],plan['orcid'])
            if creators!=row['after_creators']:raise ReviewError('Autoria difere da prévia.')
            if not row['changed']:continue
            draft=service.edit(identity,row['id'],uow=uow) if row['kind']=='published' else service.read_draft(identity,row['id'])
            updated=service.update_draft(identity,row['id'],native_payload(service,edit_payload(draft.to_dict(),creators)),revision_id=draft._record.revision_id,uow=uow)
            if updated.to_dict().get('errors'):raise ReviewError('Validação nativa recusou o ORCID.')
            if row['kind']=='published':
                validate(identity,updated._record,updated.to_dict())
                updated=service.publish(identity,row['id'],uow=uow)
            # Read through the native service so vocabulary labels resolve after update.
            after=(service.read if row['kind']=='published' else service.read_draft)(identity,row['id']).to_dict()
            verify_addition(before,after,creators)
            if after['id']!=row['id'] or str(updated._record.id)!=row['uuid']:raise ReviewError('Identificador nativo mudou.')
            count+=1
        job.result={**job.result,'updated_records':count,'orcid':plan['orcid'],'search_pending':True};job.state='completed'
        source.state='completed';source.result={'apply_job':job.id};db.session.add(job);db.session.add(source)
        uow.commit()
    refresh(job)


def refresh(job):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    # Index-only recovery after an already committed native transaction.
    for row in job.snapshot['records']:
        result=(service.read if row['kind']=='published' else service.read_draft)(actor_identity(job.actor),row['id'])
        record=result._record
        service.indexer.index(record)
        if row['kind']=='published':
            draft=service.draft_cls.get_record(uuid.UUID(row['uuid']),with_deleted=True)
            if draft.model.is_deleted:service.indexer.delete(draft,ignore=[404])
    job.result={**job.result,'search_pending':False};db.session.commit()
