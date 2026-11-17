"""Reviewed consolidation: database inventory, immutable plans and verified backups."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

from flask import current_app
from invenio_db import db
from sqlalchemy import text

from .adapters import converter, digest
from .models import OpenAlexClaim, OpenAlexJob
from .service import actor_identity, tokens


def meaningful(value):
    if isinstance(value, dict):
        return sum(meaningful(v) for v in value.values())
    if isinstance(value, list):
        return sum(meaningful(v) for v in value)
    return int(value not in (None, '', False))


def list_key(value):
    if not isinstance(value, dict):
        return digest(value)
    person = value.get('person_or_org', {})
    if person.get('name'):
        return 'person:'+str(person['name']).casefold()+':'+str(value.get('role',{}).get('id',''))
    for key in ('external_uri','codigo_amostra','campanha_id','id','identifier','subject','nome'):
        if value.get(key):
            return key+':'+str(value[key]).casefold()
    return digest(value)


def compatible_items(left,right):
    if not isinstance(left,dict) or not isinstance(right,dict):
        return True
    def orcids(value):
        return {i.get('identifier') for i in value.get('person_or_org',{}).get('identifiers',[])
                if i.get('scheme')=='orcid' and i.get('identifier')}
    left_ids,right_ids=orcids(left),orcids(right)
    return not (left_ids and right_ids and left_ids!=right_ids)


def merge_values(left, right, path='', changes=None, choices=None):
    """Fill gaps, union ordered lists and expose every competing scalar value."""
    changes = changes if changes is not None else {}
    choices = choices or {}
    if left == right or right in (None, '', [], {}):
        return deepcopy(left)
    if left in (None, '', [], {}):
        return deepcopy(right)
    if isinstance(left, dict) and isinstance(right, dict):
        result = deepcopy(left)
        for key, value in right.items():
            pointer = path+'/'+key.replace('~','~0').replace('/','~1')
            result[key] = merge_values(result.get(key),value,pointer,changes,choices)
        return result
    if isinstance(left, list) and isinstance(right, list):
        result = deepcopy(left)
        positions = defaultdict(list)
        for i,item in enumerate(result):
            positions[list_key(item)].append(i)
        for value in right:
            key = list_key(value)
            i = next((i for i in positions[key] if compatible_items(result[i],value)),None)
            if i is not None:
                result[i] = merge_values(result[i],value,path+'/'+str(i),changes,choices)
            else:
                positions[key].append(len(result))
                result.append(deepcopy(value))
        return result
    # Strings use the more informative text as a suggestion, never erase an
    # alternative: the reviewer can choose any competing value in the preview.
    options = changes.setdefault(path, {'path':path,'values':[]})['values']
    for candidate in (left,right):
        if candidate not in options:
            options.append(deepcopy(candidate))
    suggested = right if isinstance(right,str) and isinstance(left,str) and len(right)>len(left) else left
    selected = choices.get(path, suggested)
    if selected not in options:
        raise ValueError('Uma escolha não pertence às alternativas da prévia.')
    changes[path]['selected'] = deepcopy(selected)
    return deepcopy(selected)


def file_plan(records, canonical):
    """Preserve all distinct contents; rename collisions rather than replace."""
    result = []
    for category in ('files','media_files'):
        occupied = {}
        ordered = sorted(records,key=lambda r:r['id'] != canonical)
        for record in ordered:
            for key, entry in sorted(record['data'].get(category,{}).get('entries',{}).items()):
                target = key
                action = 'keep' if record['id']==canonical else 'copy'
                signature = (entry.get('checksum'),entry.get('size'))
                if key in occupied:
                    if occupied[key] == signature and signature[0]:
                        action = 'same_content'
                    else:
                        suffix = PurePosixPath(key).suffix
                        stem = key[:-len(suffix)] if suffix else key
                        target = stem+'__'+record['id']+suffix
                        number = 2
                        while target in occupied:
                            target = stem+'__'+record['id']+'_'+str(number)+suffix
                            number += 1
                        action = 'rename'
                if action != 'same_content':
                    occupied[target] = signature
                result.append({'source':record['id'],'kind':record['kind'],'category':category,
                               'key':key,'destination':target,'action':action,
                               'checksum':entry.get('checksum'),'size':entry.get('size'),
                               'metadata':deepcopy(entry.get('metadata',{}))})
    return result


def fingerprint(data):
    # Stats and generated links are volatile. Revisions, access, parent links,
    # metadata and exact file versions must all still match at confirmation.
    return digest({k:data.get(k) for k in ('id','revision_id','metadata','custom_fields',
        'access','parent','pids','versions','files','media_files','deletion_status')})


def plan_fingerprint(group):
    stable = {k:v for k,v in group.items() if k!='records'}
    stable['records'] = [{k:r.get(k) for k in ('id','kind','fingerprint','pending_edit')} for r in group['records']]
    return digest(stable)


def read_record(identity, rid, kind):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    return (service.read if kind=='published' else service.read_draft)(identity,rid)


def inventory_groups(metadata):
    """Union exact DOI/OpenAlex identities across independent native parents."""
    from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
    from invenio_pidstore.models import PersistentIdentifier
    published = {str(r.id):r for r in RDMRecordMetadata.query.all()}
    pids = {p.pid_value for p in PersistentIdentifier.query.filter_by(pid_type='recid')
            if p.status.value in ('N','R')}
    parents = defaultdict(list)
    by_token = defaultdict(set)
    for model,kind in ((RDMRecordMetadata,'published'),(RDMDraftMetadata,'draft')):
        for row in model.query.yield_per(300):
            data = row.json
            if not data or str(data.get('id','')) not in pids:
                continue
            original = published.get(str(row.id))
            if original and original.deletion_status.value != 'P':
                continue
            parent = str(row.parent_id)
            item = {'id':str(data['id']),'kind':kind,'index':row.index,'tokens':sorted(tokens(data,metadata))}
            parents[parent].append(item)
            for token in item['tokens']:
                by_token[token].add(parent)
    leaders = {pid:pid for pid in parents}
    def root(value):
        while leaders[value] != value:
            leaders[value] = leaders[leaders[value]]
            value = leaders[value]
        return value
    for members in by_token.values():
        members = sorted(members)
        for member in members[1:]:
            leaders[root(member)] = root(members[0])
    groups = defaultdict(list)
    for parent in parents:
        groups[root(parent)].append(parent)
    result = []
    for members in groups.values():
        if len(members)>1:
            result.append([max(parents[p],key=lambda r:(r['kind']=='published',r['index'])) for p in members])
    return sorted(result,key=lambda g:sorted(r['id'] for r in g)), len(parents)


def record_snapshot(identity, item, *, include_deleted=False):
    from invenio_rdm_records.records.models import RDMDraftMetadata
    if include_deleted and item['kind']=='published':
        from invenio_rdm_records.proxies import current_rdm_records_service as service
        result=service.read(identity,item['id'],include_deleted=True)
    else:
        result = read_record(identity,item['id'],item['kind'])
    record = result._record
    draft = db.session.get(RDMDraftMetadata,record.id)
    data = result.to_dict()
    return {**item,'data':data,'fingerprint':fingerprint(data),
            'uuid':str(record.id),'parent_uuid':str(record.parent.id),
            'raw':deepcopy(dict(record)), 'parent_raw':deepcopy(dict(record.parent)),
            'pending_edit':item['kind']=='published' and bool(draft and draft.json)}


def choose_canonical(records):
    def score(row):
        data = row['data']
        native_doi = data.get('pids',{}).get('doi',{}).get('provider') not in (None,'external')
        return (row['kind']=='published',native_doi,
                len(data.get('parent',{}).get('communities',{}).get('ids',[])),
                sum(data.get(c,{}).get('count',0) for c in ('files','media_files')),
                meaningful(data.get('metadata',{}))+meaningful(data.get('custom_fields',{})))
    ordered = sorted(records,key=lambda r:(r['data'].get('created',''),r['id']))
    return max(ordered,key=score)['id']


def plan_group(records, canonical=None, choices=None):
    canonical = canonical or choose_canonical(records)
    keep = next((r for r in records if r['id']==canonical),None)
    if not keep:
        raise ValueError('Registro principal fora do grupo.')
    ordered = [keep]+sorted([r for r in records if r['id']!=canonical],key=lambda r:r['id'])
    payload = {'metadata':deepcopy(keep['data']['metadata']),
               'custom_fields':deepcopy(keep['data'].get('custom_fields',{}))}
    conflicts = {}
    # Choices are applied after collecting every alternative, for 3+ sources.
    for row in ordered[1:]:
        payload = merge_values(payload,{'metadata':row['data']['metadata'],
            'custom_fields':row['data'].get('custom_fields',{})},changes=conflicts)
    for path,value in (choices or {}).items():
        if path not in conflicts or value not in conflicts[path]['values']:
            raise ValueError('Escolha inválida; gere outra prévia.')
        parts = [p.replace('~1','/').replace('~0','~') for p in path.split('/')[1:]]
        cursor = payload
        for part in parts[:-1]:
            cursor = cursor[int(part)] if isinstance(cursor,list) else cursor[part]
        if isinstance(cursor,list):
            cursor[int(parts[-1])] = deepcopy(value)
        else:
            cursor[parts[-1]] = deepcopy(value)
        conflicts[path]['selected'] = deepcopy(value)
    blockers = []
    identities = sorted({t for r in records for t in r['tokens']})
    if len({t for t in identities if t.startswith('doi:')})>1:
        blockers.append('DOIs distintos no mesmo grupo. Corrija os identificadores antes de consolidar.')
    if keep['kind']=='draft' and any(r['kind']=='published' for r in records):
        blockers.append('Escolha como principal um registro já publicado.')
    def access_policy(data):
        return {k:data.get('access',{}).get(k) for k in ('record','files','embargo')}
    access = access_policy(keep['data'])
    owners = keep['data']['parent'].get('access',{})
    communities = set(keep['data']['parent'].get('communities',{}).get('ids',[]))
    for row in records:
        data = row['data']
        if row.get('pending_edit') or data.get('versions',{}).get('index',1)>1:
            blockers.append('O registro '+row['id']+' tem edição pendente ou histórico de versões. Revise-o no depósito nativo.')
        if access_policy(data) != access or data['parent'].get('access',{}) != owners:
            blockers.append('Acesso, embargo ou responsáveis diferentes em '+row['id']+'. Ajuste-os antes para preservar as permissões.')
        if not set(data['parent'].get('communities',{}).get('ids',[])).issubset(communities):
            blockers.append('O principal deve conter as comunidades de '+row['id']+'. Revise os vínculos ou escolha outro principal.')
        if row['id']!=canonical and data.get('pids',{}).get('doi',{}).get('provider') not in (None,'external'):
            blockers.append('O registro '+row['id']+' possui DOI gerenciado. Mantenha-o como principal.')
    files = file_plan(records,canonical)
    for f in files:
        if not f['checksum'] or not isinstance(f['size'],int) or f['size']<0:
            blockers.append('Arquivo incompleto em '+f['source']+': '+f['key'])
        if f['action']=='rename' and f['key'].lower().endswith('.raw'):
            blockers.append('Arquivos RAW com o mesmo nome e conteúdos diferentes exigem revisão no painel DRX para preservar a nomenclatura e a proveniência.')
    # Keep the main access and file defaults. File merging never replaces bytes.
    for category in ('files','media_files'):
        existing = keep['data'].get(category,{})
        payload[category] = {k:deepcopy(existing[k]) for k in ('enabled','default_preview') if k in existing}
        payload[category]['enabled'] = bool(existing.get('enabled') or any(f['category']==category for f in files))
    # Preserve aliases even when they originate in a native DOI PID.
    identifiers = payload['metadata'].setdefault('identifiers',[])
    for token in identities:
        item = {'scheme':'doi','identifier':token[4:]} if token.startswith('doi:') else {
            'scheme':'url','identifier':'https://openalex.org/'+token.split(':',1)[1]}
        if item not in identifiers:
            identifiers.append(item)
    changes = []
    for section in ('metadata','custom_fields'):
        for key,value in payload[section].items():
            previous = keep['data'].get(section,{}).get(key)
            if previous != value:
                changes.append({'path':section+'/'+key,'before':previous,'after':value})
    return {'id':digest(sorted(r['id'] for r in records))[:20],'records':records,
            'canonical':canonical,'identities':identities,'payload':payload,'choices':choices or {},
            'conflicts':list(conflicts.values()),'changes':changes,'files':files,
            'blockers':list(dict.fromkeys(blockers)),'published':keep['kind']=='published'}


def reference_blockers(group):
    """Never silently orphan links or requests owned by other modules."""
    from invenio_requests.records.models import RequestMetadata
    from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
    donors = [r for r in group['records'] if r['id']!=group['canonical']]
    ids = {r['id'] for r in donors}
    references = ids | {r['data']['parent']['id'] for r in donors}
    for row in RequestMetadata.query.yield_per(300):
        if any(value in json.dumps(row.json or {}) for value in references):
            group['blockers'].append('Há solicitações vinculadas à duplicata. Resolva-as antes de consolidar.')
            break
    for model in (RDMRecordMetadata,RDMDraftMetadata):
        for row in model.query.yield_per(300):
            data = row.json or {}
            if data.get('id') not in {r['id'] for r in group['records']} and any(
                value in json.dumps(data) for value in references):
                group['blockers'].append('Outros registros referenciam a duplicata. Atualize esses vínculos antes de consolidar.')
                break
    # DRX links remain under their dedicated review flow; do not rewrite its
    # scientific state or audit trail from bibliographic administration.
    from ..scientific.drx_links import DRXRecordLink
    if DRXRecordLink.query.filter(DRXRecordLink.record_id.in_(ids)).count():
        group['blockers'].append('Há vínculos DRX na duplicata. Revise-os no painel DRX antes de consolidar.')
    group['blockers'] = list(dict.fromkeys(group['blockers']))
    return group


def scan_job(job):
    identity = actor_identity(job.actor)
    metadata = converter(current_app.config['ARGILOTECA_OPENALEX_ROOT'])[0]
    groups,total = inventory_groups(metadata)
    plans = [reference_blockers(plan_group([record_snapshot(identity,r) for r in group])) for group in groups]
    job.snapshot = {'schema':1,'scanned_at':datetime.now(timezone.utc).isoformat(),
                    'independent_records':total,'groups':plans}
    job.state = 'review'
    job.result = {'groups':len(plans),'extra_records':sum(len(g['records'])-1 for g in plans)}


def backup_path(job_id):
    if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Identificador de backup inválido.')
    return Path(current_app.config['ARGILOTECA_OPENALEX_BACKUPS'])/(job_id+'.zip')


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def write_backup(job, group, identity):
    """Complete snapshots + each original binary, fsynced before any mutation."""
    path = backup_path(job.id)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    manifest = {'schema':1,'job':job.id,'actor':job.actor,'group':group,'files':[]}
    fd,temporary = tempfile.mkstemp(prefix='.backup-',dir=path.parent)
    try:
        with os.fdopen(fd,'w+b') as target, zipfile.ZipFile(target,'w',allowZip64=True) as archive:
            for i,item in enumerate(group['files']):
                record = read_record(identity,item['source'],item['kind'])._record
                file = getattr(record,item['category'])[item['key']]
                algorithm,expected = item['checksum'].split(':',1)
                checksum = hashlib.new(algorithm)
                sha = hashlib.sha256()
                size = 0
                name = 'files/'+str(i)+'.bin'
                with file.open_stream('rb') as source, archive.open(name,'w',force_zip64=True) as destination:
                    while chunk := source.read(1024*1024):
                        destination.write(chunk);checksum.update(chunk);sha.update(chunk);size+=len(chunk)
                if checksum.hexdigest()!=expected or size!=item['size']:
                    raise ValueError('Conteúdo ou checksum divergente; nenhum registro foi consolidado: '+item['key'])
                manifest['files'].append({**item,'archive':name,'sha256':sha.hexdigest()})
            destinations = {}
            for item in manifest['files']:
                key = (item['category'],item['destination'])
                previous = destinations.setdefault(key,item['sha256'])
                if previous != item['sha256']:
                    raise ValueError('Arquivos distintos têm o mesmo checksum legado. Revise o grupo; nenhum conteúdo foi substituído.')
            descriptor = group.get('plan', {}).get('job', {}).get('snapshot', {}).get('record_store')
            if descriptor:
                from .preview import store_path
                source = store_path(descriptor)
                archive.write(source, 'preview.sqlite')
                manifest['preview_store'] = {**descriptor, 'archive': 'preview.sqlite'}
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2,default=str))
        with open(temporary,'rb') as stream:
            os.fsync(stream.fileno())
        os.chmod(temporary,0o600)
        os.replace(temporary,path)
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError('Falha na validação do backup. Consolidação interrompida.')
        return {'filename':path.name,'sha256':sha256_file(path),'bytes':path.stat().st_size,
                'binary_files':len(manifest['files'])}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def copy_files(identity, group, draft, uow):
    """Native ObjectVersion copies retain the exact FileInstance and all tags."""
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_records_resources.services.uow import RecordCommitOp
    for category in ('files','media_files'):
        additions = [f for f in group['files'] if f['category']==category and f['action'] in ('copy','rename')]
        if not additions:
            continue
        # Native file management permission is required in addition to admin.
        service.require_permission(identity,'manage_files',record=draft)
        destination = getattr(draft,category)
        destination.enabled = True
        if not destination.bucket:
            destination.create_bucket()
        destination.unlock()
        for item in additions:
            source = read_record(identity,item['source'],item['kind'])._record
            original = getattr(source,category)[item['key']]
            if item['destination'] in destination or not original.object_version:
                raise ValueError('Destino ocupado ou arquivo de origem indisponível: '+item['key'])
            obj = original.object_version.copy(bucket=destination.bucket,key=item['destination'])
            destination.create(item['destination'],obj=obj,data=deepcopy(dict(original)))
            destination.commit(item['destination'])
    uow.register(RecordCommitOp(draft,indexer=service.indexer))


def consolidate_job(job):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata, RDMParentMetadata
    from invenio_records_resources.services.uow import UnitOfWork
    identity = actor_identity(job.actor)
    approved = deepcopy(job.snapshot['group'])
    if approved['blockers']:
        raise ValueError('Grupo bloqueado. Gere outra prévia após resolver os impedimentos.')
    if job.params.get('plan_sha256') != digest(approved):
        raise ValueError('A prévia foi alterada. Gere outra revisão.')
    metadata = converter(current_app.config['ARGILOTECA_OPENALEX_ROOT'])[0]
    with UnitOfWork() as uow:
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
        # Native records/parents are locked in a stable order. Revisions also
        # protect against edits made outside this administrative module.
        import uuid
        for row in sorted(approved['records'],key=lambda r:r['uuid']):
            model = RDMRecordMetadata if row['kind']=='published' else RDMDraftMetadata
            db.session.query(RDMParentMetadata).filter_by(id=uuid.UUID(row['parent_uuid'])).with_for_update().one()
            db.session.query(model).filter_by(id=uuid.UUID(row['uuid'])).with_for_update().one()
        current = [record_snapshot(identity,r) for r in approved['records']]
        if any(row['fingerprint']!=old['fingerprint'] or row['pending_edit']!=old['pending_edit']
               for row,old in zip(current,approved['records'])):
            raise ValueError('Um registro mudou desde a prévia. Verifique novamente; nenhuma consolidação foi feita.')
        groups,_ = inventory_groups(metadata)
        actual = next((g for g in groups if any(r['id']==approved['canonical'] for r in g)),[])
        if {r['id'] for r in actual}!={r['id'] for r in current}:
            raise ValueError('O grupo de duplicatas mudou. Execute outra verificação.')
        fresh = reference_blockers(plan_group(current,approved['canonical'],approved['choices']))
        if fresh['blockers'] or plan_fingerprint(fresh)!=plan_fingerprint(approved):
            raise ValueError('A proposta mudou ou há novos vínculos. Gere outra prévia antes de consolidar.')
        # Historical claims may be transferred only within this reviewed group.
        ids = {r['id'] for r in current}
        for claim in OpenAlexClaim.query.filter(OpenAlexClaim.token.in_(approved['identities'])):
            if claim.draft_id not in ids:
                raise ValueError('Uma identidade está reservada para outro registro. Resolva o conflito antes de consolidar.')
        backup = write_backup(job,approved,identity)
        if sha256_file(backup_path(job.id)) != backup['sha256']:
            raise ValueError('Backup divergente. Nenhum registro foi consolidado.')
        keep = next(r for r in current if r['id']==approved['canonical'])
        editable = service.edit(identity,keep['id'],uow=uow) if keep['kind']=='published' else service.read_draft(identity,keep['id'])
        updated = service.update_draft(identity,keep['id'],deepcopy(approved['payload']),
            revision_id=editable._record.revision_id,uow=uow)
        copy_files(identity,approved,updated._record,uow)
        if approved['published']:
            result = service.publish(identity,keep['id'],uow=uow)
        else:
            result = service.read_draft(identity,keep['id'])
        after = result.to_dict()
        if after.get('errors'):
            raise ValueError('A união dos metadados não passou na validação nativa. Consulte a prévia e corrija os registros.')
        for item in approved['files']:
            target = after[item['category']]['entries'].get(item['destination'],{})
            if target.get('checksum')!=item['checksum'] or target.get('size')!=item['size']:
                raise ValueError('Falha ao conferir arquivo no principal. Consolidação desfeita.')
        removed = []
        for row in current:
            if row['id']==keep['id']:
                continue
            if row['kind']=='published':
                service.delete_record(identity,row['id'],{
                    'removal_reason':{'id':'duplicate'},'is_visible':True,
                    'note':'Registro consolidado em '+current_app.config.get('SITE_UI_URL','').rstrip('/')+
                        '/records/'+keep['id']+'. Backup administrativo: '+job.id+'.',
                    'citation_text':after['metadata']['title']+' — '+keep['id'],
                },revision_id=row['data']['revision_id'],uow=uow)
            else:
                service.delete_draft(identity,row['id'],revision_id=row['data']['revision_id'],uow=uow)
            removed.append({'id':row['id'],'kind':row['kind']})
        for claim in OpenAlexClaim.query.filter(OpenAlexClaim.draft_id.in_(ids)):
            if claim.token not in approved['identities']:
                raise ValueError('Claim histórico não incluído na prévia. Consolidação desfeita.')
            claim.draft_id = keep['id']
        for token in approved['identities']:
            claim = db.session.get(OpenAlexClaim,token)
            if not claim:
                db.session.add(OpenAlexClaim(token=token,draft_id=keep['id'],job_id=job.id,
                    payload_sha256=digest(approved['payload'])))
        job.state = 'completed'
        job.result = {'canonical':keep['id'],'published':approved['published'],'removed':removed,
                      'backup':backup,'after':after,'completed_at':datetime.now(timezone.utc).isoformat()}
        source_job = db.session.get(OpenAlexJob,job.params.get('source_job')) if job.params.get('source_job') else None
        if source_job and source_job.kind=='dedup_preview':
            source_job.state = 'completed'
            source_job.result = {'merge_job':job.id}
            db.session.add(source_job)
        db.session.add(job)
        uow.commit()
