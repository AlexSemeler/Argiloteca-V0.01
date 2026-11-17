"""Reviewed administrative removal: native record services, backups and audit."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path

from flask import current_app
from invenio_db import db
from sqlalchemy import text
from invenio_rdm_records.proxies import current_rdm_records_service as service,current_rdm_records as rdm_extension
from invenio_rdm_records.records.models import RDMRecordMetadata,RDMDraftMetadata
from invenio_records_resources.services.uow import UnitOfWork,RecordCommitOp
from invenio_rdm_records.services.communities.service import ParentRecordCommitOp
from .adapters import digest
from .models import OpenAlexJob,OpenAlexClaim,OpenAlexAnalyticHead
from .service import actor_identity
from .duplicates import record_snapshot,file_plan,write_backup,backup_path
from . import maintenance_files

ACTIVE={'queued','running','waiting_host'}
RECORD_ACTIONS={'purge_published','delete_draft','withdraw_record','restore_record','remove_community','remove_connection','remove_drx','clear_coordinates','remove_orcid','remove_drx_many'}
JOB_ACTIONS={'archive_job','restore_job','delete_job','exclude_candidates'}
LOT_ACTIONS={'archive_lot','restore_lot','delete_lot'}


def now():return datetime.now(timezone.utc).isoformat()

def visible_jobs(query):
    return query.filter(OpenAlexJob.params['admin_archived'].as_boolean().isnot(True))


def job_data(job):
    return {'id':job.id,'kind':job.kind,'state':job.state,'actor':job.actor,
        'params':deepcopy(job.params),'snapshot':deepcopy(job.snapshot),'result':deepcopy(job.result),
        'created':job.created.isoformat(),'updated':job.updated.isoformat()}


def archived_jobs_for_lot(lot,exclude=None):
    blockers=[]
    query=db.session.query(OpenAlexJob.id,OpenAlexJob.state,OpenAlexJob.params,OpenAlexJob.snapshot['source'].as_string()).filter(~OpenAlexJob.kind.like('clean_%'))
    for jid,state,params,source in query.yield_per(25):
        if jid==exclude:continue
        source=params.get('lot') or Path(source or '').name
        if source==lot and (state in ACTIVE or (state=='review' and not params.get('admin_archived'))):
            blockers.append(jid)
    return blockers


def pending_lot_maintenance(lot):
    return db.session.query(OpenAlexJob.id).filter(OpenAlexJob.kind=='clean_apply',OpenAlexJob.state.in_(ACTIVE),
        OpenAlexJob.snapshot['plan']['target'].as_string()==lot,OpenAlexJob.snapshot['plan']['kind'].as_string()=='lot').first() is not None


def references(value,ids):
    if isinstance(value,dict):return any(references(v,ids) for v in value.values())
    if isinstance(value,list):return any(references(v,ids) for v in value)
    return isinstance(value,str) and (value in ids or value.rstrip('/').rsplit('/',1)[-1] in ids)


def result_status(row,kind):
    return db.session.get(RDMRecordMetadata,row['uuid']).deletion_status.value if kind=='published' else 'draft'


def record_state(identity,pid,kind):
    if kind not in {'published','draft'}:raise ValueError('Selecione publicado ou rascunho.')
    row=record_snapshot(identity,{'id':pid,'kind':kind},include_deleted=True)
    from ..scientific.drx_links import DRXRecordLink,link_dict
    row['status']=result_status(row,kind)
    row['drx_links']=[dict(link_dict(link),id=link.id) for link in DRXRecordLink.query.filter_by(record_id=pid)]
    row['versions']=[{'uuid':str(r.id),'kind':k,'raw':deepcopy(r.json),'revision':r.version_id,'status':r.deletion_status.value if k=='published' else 'draft'} for cls,k in ((RDMRecordMetadata,'published'),(RDMDraftMetadata,'draft')) for r in cls.query.filter_by(parent_id=row['parent_uuid'])]
    row['versions'].sort(key=lambda v:(v['kind'],v['uuid']))
    row['state_sha256']=digest({k:row[k] for k in ('raw','parent_raw','drx_links','versions','status','fingerprint')})
    return row


def removal_dependencies(row):
    blockers=[];pid=row['id']
    from ..scientific.connections import FIELD
    if row['data'].get('custom_fields',{}).get(FIELD):blockers.append('Remova primeiro as conexões científicas de saída.')
    if any(l['state']!='removed' for l in row['drx_links']):blockers.append('Remova primeiro os vínculos DRX ativos.')
    for model in (RDMRecordMetadata,RDMDraftMetadata):
        query=db.session.query(model.json).filter(model.json.isnot(None),model.parent_id!=row['parent_uuid'])
        if model is RDMRecordMetadata:query=query.filter(model.deletion_status=='P')
        for (data,) in query.yield_per(25):
            if references(data,{pid,row['parent_uuid']}):
                blockers.append('Outro registro referencia este item: '+str(data.get('id','')))
    from invenio_requests.records.models import RequestMetadata
    if any(references(data or {},{pid,row['parent_uuid']}) for (data,) in db.session.query(RequestMetadata.json).yield_per(25)):
        blockers.append('Há solicitações vinculadas. Resolva-as antes de remover o registro.')
    return list(dict.fromkeys(blockers))


def plan(identity,actor,kind,target,action,*,record_kind='',selection='',reason='',archived=False):
    if action in {'remove_orcid','remove_drx_many','exclude_candidates','delete_raw'} and not current_app.config.get('ARGILOTECA_ADMIN_ONTOLOGY_ENABLED'):
        raise ValueError('Ações em lote desativadas neste ambiente. / Bulk actions are disabled in this environment.')
    reason=str(reason).strip()
    if not 5<=len(reason)<=500:raise ValueError('Informe uma justificativa de 5 a 500 caracteres.')
    result={'schema':1,'actor':int(actor),'kind':kind,'target':target,'action':action,
        'reason':reason,'selection':selection,'created':now(),'blockers':[],'permanent':False}
    if kind=='raw' and action=='delete_raw':
        from ..scientific.raw_removal import snapshot
        result['raw']=snapshot(identity,json.loads(selection))
        result.update(title='RAW · '+str(len(result['raw']['rows'])),files=[],permanent=True)
        result['blockers']=result['raw']['blockers']
        result['effect']='Excluir os arquivos RAW anônimos selecionados e suas cópias no módulo DRX, após verificar o backup. Remover todos os vínculos ativos desses arquivos. Preservar registros, resultados históricos, originais privados e backups.'
    elif kind=='record' and action in RECORD_ACTIONS:
        row=record_state(identity,target,record_kind);result['record']=row
        record=(service.read(identity,target,include_deleted=True) if record_kind=='published' else service.read_draft(identity,target))._record
        result['title']=row['data'].get('metadata',{}).get('title',target)
        status=record.model.deletion_status.value if record_kind=='published' else 'draft'
        if action in {'purge_published','delete_draft','withdraw_record','restore_record'}:
            permission='purge' if action=='purge_published' else 'delete_draft' if action=='delete_draft' else 'delete'
            service.require_permission(identity,permission,record=record)
            if action=='purge_published':
                if record_kind!='published' or status not in {'P','D','X'}:raise ValueError('Selecione uma versão publicada ou retirada para excluir definitivamente.')
                from .published_purge import snapshot
                result['purge']=snapshot(row);result['blockers']+=result['purge']['blockers']
                result['permanent']=True
                result['effect']='Excluir definitivamente esta versão publicada, seus metadados, revisões e arquivos exclusivos. Não há restauração pela interface. Backups, auditoria e identificadores reservados permanecem. Arquivos compartilhados e DOI externos são preservados.'
            elif action=='delete_draft':
                if record_kind!='draft':raise ValueError('A exclusão definitiva nativa aplica-se a rascunhos.')
                result['permanent']=True;result['effect']='Excluir definitivamente este rascunho e seus arquivos exclusivos. O publicado, quando existente, permanece.'
            elif action=='withdraw_record':
                if record_kind!='published' or status!='P':raise ValueError('Selecione uma publicação ativa para retirar.')
                result['effect']='Retirar esta versão publicada, preservando identificador, metadados e arquivos para restauração.'
                if row['pending_edit']:result['blockers'].append('Existe edição em rascunho. Descarte ou conclua essa edição antes da retirada.')
            else:
                if record_kind!='published' or status!='D':raise ValueError('Só publicações retiradas podem ser restauradas.')
                result['effect']='Restaurar a publicação retirada com o mesmo identificador e os dados preservados.'
            discarding_edit=action=='delete_draft' and any(v['kind']=='published' and v['uuid']==row['uuid'] for v in row['versions'])
            if action!='restore_record' and not discarding_edit:result['blockers']+=removal_dependencies(row)
        else:
            if status not in {'P','draft'}:raise ValueError('Restaure o registro antes de alterar seus vínculos.')
            service.require_permission(identity,'edit' if record_kind=='published' else 'update_draft',record=record)
            if record_kind=='published' and row['pending_edit']:result['blockers'].append('Há edição em rascunho; conclua-a antes desta manutenção.')
            if action=='remove_community':
                if selection not in row['data']['parent'].get('communities',{}).get('ids',[]):raise ValueError('Comunidade não vinculada.')
                if record_kind=='published':rdm_extension.record_communities_service.require_permission(identity,'remove_community_from_record',record=record,community_id=selection)
                result['effect']='Remover somente a comunidade selecionada; arquivos, metadados e demais vínculos permanecem. Se for a padrão, a definição de padrão será retirada.'
                result['selected_label']=selection
            elif action=='remove_connection':
                from ..scientific.connections import FIELD
                link=next((l for l in row['raw'].get('custom_fields',{}).get(FIELD,[]) if l['record_id']==selection),None)
                if not link:raise ValueError('Conexão científica não encontrada.')
                result['connection']=link;result['effect']='Remover somente esta conexão e a referência criada por ela; preservar citações anteriores e o registro de destino.'
            elif action=='remove_drx_many':
                try:raw_ids=json.loads(selection)
                except (ValueError,TypeError):raise ValueError('Seleção DRX inválida / Invalid DRX selection') from None
                if record_kind!='published' or not isinstance(raw_ids,list) or not raw_ids or len(raw_ids)>100 or any(not isinstance(r,str) for r in raw_ids):raise ValueError('Seleção DRX inválida / Invalid DRX selection')
                links=[link for link in row['drx_links'] if link['raw_id'] in raw_ids and link['state']!='removed']
                if len(links)!=len(set(raw_ids)):raise ValueError('Vínculos DRX alterados. Atualize a lista. / DRX links changed; refresh the list.')
                result['drx_links']=links;result['effect']='Remover os vínculos DRX selecionados deste registro. Preservar os RAWs e as análises. / Remove selected DRX links; preserve RAW files and analyses.'
            elif action=='remove_drx':
                if record_kind!='published':raise ValueError('Vínculos DRX são mantidos na publicação.')
                link=next((l for l in row['drx_links'] if l['raw_id']==selection and l['state']!='removed'),None)
                if not link:raise ValueError('Vínculo DRX ativo não encontrado.')
                result['drx_link']=link;result['effect']='Marcar somente o vínculo DRX como removido e atualizar o pacote de metadados. O RAW e suas análises não serão apagados.'
            elif action=='remove_orcid':
                remove_orcid(row['raw'].get('metadata',{}),selection)
                choices=json.loads(selection);choices=[choices] if isinstance(choices,dict) else choices
                from .analytics import creator_name
                result['orcid_removals']=[dict(slot=choice['slot'],name=creator_name(row['raw']['metadata']['creators'][choice['slot']]),orcid=[entry['identifier'] for entry in row['raw']['metadata']['creators'][choice['slot']]['person_or_org'].get('identifiers',[]) if entry.get('scheme')=='orcid']) for choice in choices]
                result['effect']='Remover somente o identificador ORCID da ocorrência selecionada. Preservar o autor, os demais identificadores e as publicações. / Remove only the selected ORCID association; preserve the author and publications.'
            else:
                clear_coordinates(row['raw'].get('custom_fields',{}),selection)
                result['effect']='Remover latitude e longitude somente do item selecionado; preservar dados científicos e demais localizações.'
        result['files']=file_plan([row],row['id']) if action in {'purge_published','delete_draft','withdraw_record'} else []
    elif kind=='job' and action in JOB_ACTIONS:
        job=db.session.get(OpenAlexJob,target)
        if not job or job.kind.startswith('clean_'):raise ValueError('Tarefa inexistente ou registro de auditoria protegido.')
        saved=job_data(job);result['job']=saved;result['state_sha256']=digest(saved)
        result['title']=job.kind+' · '+job.id;result['files']=[]
        if job.state in ACTIVE:result['blockers'].append('A tarefa está ativa. Aguarde sua conclusão antes de remover.')
        if action=='delete_job':
            head=db.session.get(OpenAlexAnalyticHead,1)
            population=OpenAlexJob.query.filter_by(kind='stats_scan',state='completed').filter(OpenAlexJob.snapshot['population'].isnot(None)).order_by(OpenAlexJob.created.desc()).first()
            if (head and head.version==target) or (population and population.id==target):result['blockers'].append('Este retrato alimenta as estatísticas e autorias atuais. Atualize o retrato antes de excluir ou use arquivamento. / This snapshot supplies current statistics and authors; refresh it before deletion or archive it.')
            result['permanent']=True;result['effect']='Excluir definitivamente a tarefa e seu snapshot do histórico. Registros importados, arquivos de origem e claims de identidade não serão apagados.'
            children=[jid for jid,params in db.session.query(OpenAlexJob.id,OpenAlexJob.params).filter(~OpenAlexJob.kind.like('clean_%'),OpenAlexJob.id!=target).yield_per(25) if references(params,{target})]
            if children:result['blockers'].append('Outras tarefas dependem deste histórico: '+', '.join(children[:8]))
            if OpenAlexClaim.query.filter_by(job_id=target).count():result['blockers'].append('Claims DOI/OpenAlex dependem desta tarefa; arquive para preservar a proteção contra duplicados.')
            if saved['result'].get('backup'):result['blockers'].append('Esta tarefa mantém um backup de consolidação. Use arquivamento para preservar o acesso.')
        elif action=='exclude_candidates':
            from .preview import iter_records
            keys=json.loads(selection)
            if not isinstance(keys,list) or not keys or len(keys)>100 or any(not isinstance(key,str) for key in keys):raise ValueError('Seleção inválida / Invalid selection')
            if job.kind not in {'prepare','import','pan_prepare','pan_import','men_prepare','men_import','oai_prepare','oai_import'} or job.state not in {'review','completed'}:raise ValueError('Esta tarefa não está disponível para revisar metadados. / Job unavailable for metadata review.')
            rows=list(iter_records(job.snapshot,set(keys)))
            if len(rows)!=len(set(keys)):raise ValueError('A seleção mudou. Atualize a revisão. / Selection changed; refresh the review.')
            excluded=set(job.snapshot.get('admin_excluded_records',[]))|set(keys)
            if len(excluded)>1000:raise ValueError('Limite de 1.000 exclusões por revisão. Prepare outra revisão. / Limit of 1,000 exclusions per review; prepare a new review.')
            result['excluded_candidates']=[{'key':row['key'],'title':row['payload']['metadata'].get('title',row['key']),'status':row['status']} for row in rows]
            if any(references(params,{target}) for _,params in db.session.query(OpenAlexJob.id,OpenAlexJob.params).filter(OpenAlexJob.kind.notlike('clean_%'),OpenAlexJob.state.in_(ACTIVE))):result['blockers'].append('Uma tarefa ativa usa esta revisão. Aguarde sua conclusão. / An active task uses this review; wait for completion.')
            result['effect']='Excluir somente as linhas selecionadas desta revisão e impedir sua importação por esta revisão. Preservar arquivos originais, registros já importados e histórico com backup. / Exclude selected rows from this review and its import; preserve source files, existing records and backed-up history.'
        elif action=='archive_job':
            if job.params.get('admin_archived'):raise ValueError('Esta tarefa já está arquivada.')
            result['effect']='Remover a tarefa das listas correntes. O histórico, a proveniência e os registros importados permanecem; pode restaurar depois.'
        else:
            if not job.params.get('admin_archived'):raise ValueError('Esta tarefa não está arquivada.')
            result['effect']='Restaurar a tarefa às listas correntes, sem executar novamente a importação.'
    elif kind=='lot' and action in LOT_ACTIONS:
        result.update(archived=bool(archived),files=[])
        current=maintenance_files.manifest(current_app.config['ARGILOTECA_OPENALEX_ROOT'],target,archived)
        result.update(lot_manifest=current,lot_sha256=maintenance_files.fingerprint(current),title=target)
        expected=action=='restore_lot'
        if action!='delete_lot' and bool(archived)!=expected:raise ValueError('A situação atual do lote não corresponde à operação.')
        blockers=archived_jobs_for_lot(target)
        if blockers:result['blockers'].append('Arquive as revisões pendentes e aguarde tarefas ativas deste lote: '+', '.join(blockers[:8]))
        result['permanent']=action=='delete_lot'
        result['effect']={'archive_lot':'Retirar o lote das coletas disponíveis e preservá-lo para restauração.',
            'restore_lot':'Restaurar o lote arquivado às coletas disponíveis.',
            'delete_lot':'Excluir definitivamente os arquivos deste lote no Mac. Registros já importados permanecem. O backup administrativo continua disponível.'}[action]
    else:raise ValueError('Operação de manutenção inválida.')
    return result


def clear_coordinates(fields,selection):
    from ..scientific.catalog_views import coordinate_targets
    if selection not in {t[0] for t in coordinate_targets(fields)}:raise ValueError('Localização indisponível.')
    result=deepcopy(fields)
    if selection=='legacy':
        for k in ('arg:amostra_latitude','arg:amostra_longitude'):result.pop(k,None)
    else:
        name,index=selection.rsplit('/',1)
        for k in ('latitude','longitude'):result[name][int(index)].pop(k,None)
    return result


def remove_orcid(metadata, selection):
    """Remove reviewed occurrences' ORCIDs without touching people or other IDs."""
    try:
        choices=json.loads(selection)
        if isinstance(choices,dict):choices=[choices]
        if not isinstance(choices,list) or not 1<=len(choices)<=100:raise ValueError()
        for choice in choices:
            slot=choice['slot']
            if isinstance(slot,bool) or not isinstance(slot,int) or slot<0:raise ValueError()
            creator=metadata['creators'][slot]
            if digest(creator)!=choice['creator_sha256']:raise ValueError()
            person=creator['person_or_org']
            if person.get('type')!='personal' or not any(x.get('scheme')=='orcid' for x in person.get('identifiers',[])):raise ValueError()
    except (KeyError,IndexError,TypeError,ValueError):
        raise ValueError('O vínculo ORCID mudou ou não existe. Atualize a lista. / ORCID association changed or is absent; refresh the list.') from None
    result=deepcopy(metadata)
    for choice in choices:
        person=result['creators'][choice['slot']]['person_or_org']
        identifiers=[entry for entry in person['identifiers'] if entry.get('scheme')!='orcid']
        if identifiers:person['identifiers']=identifiers
        else:person.pop('identifiers',None)
    return result


def current_plan(identity,approved):
    fresh=plan(identity,approved['actor'],approved['kind'],approved['target'],approved['action'],
        record_kind=approved.get('record',{}).get('kind',''),selection=approved['selection'],reason=approved['reason'],archived=approved.get('archived',False))
    fresh['created']=approved['created']
    if fresh['kind']=='record' and fresh['record']['state_sha256']==approved['record']['state_sha256']:
        fresh['record']=deepcopy(approved['record'])
    if digest(fresh)!=digest(approved):raise ValueError('Os dados ou as dependências mudaram após a prévia. Prepare outra revisão.')
    if fresh['blockers']:raise ValueError('Há dependências que impedem esta operação. Resolva-as e gere outra prévia.')
    return fresh


def run_job(job):
    """Back up before any change; checkpoint audit and native writes atomically."""
    approved=job.snapshot['plan'];identity=actor_identity(job.actor)
    source=db.session.get(OpenAlexJob,job.params['source_job'])
    if not source or source.kind!='clean_preview' or source.actor!=job.actor or digest(source.snapshot['plan'])!=job.params['plan_sha256'] or digest(approved)!=job.params['plan_sha256']:
        raise ValueError('A prévia não corresponde à confirmação.')
    if approved['kind']=='raw':
        from ..scientific.raw_removal import run
        return run(job,identity,approved,source)
    if job.result.get('purge',{}).get('phase')=='cleanup':
        from .published_purge import finish
        return finish(job)
    if approved['kind']=='lot':return lot_job(job,identity,approved)
    with UnitOfWork(db.session) as uow:
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
        if approved['kind']=='record':
            model=RDMRecordMetadata if approved['record']['kind']=='published' else RDMDraftMetadata
            model.query.filter_by(id=approved['record']['uuid']).with_for_update().one()
            from invenio_rdm_records.records.models import RDMParentMetadata
            RDMParentMetadata.query.filter_by(id=approved['record']['parent_uuid']).with_for_update().one()
        else:OpenAlexJob.query.filter_by(id=approved['target']).with_for_update().one()
        db.session.expire_all();approved=current_plan(identity,approved)
        purging=approved['action']=='purge_published'
        if purging:
            from .published_purge import write_backup as purge_backup
            info=purge_backup(job,approved,identity)
        else:info=write_backup(job,{'plan':approved,'records':[approved['record']] if approved['kind']=='record' else [],'files':approved['files']},identity)
        job.result={'backup':info};db.session.add(job)
        if approved['kind']=='record':
            preserve_removed_identities(job,approved)
            if purging:
                from .published_purge import remove_metadata
                cleanup=remove_metadata(identity,approved,uow)
            else:apply_record(identity,approved,uow)
        else:
            item=db.session.get(OpenAlexJob,approved['target']);params=deepcopy(item.params)
            if approved['action']=='delete_job':db.session.delete(item)
            elif approved['action']=='exclude_candidates':
                updated=deepcopy(item.snapshot)
                updated['admin_excluded_records']=sorted(set(updated.get('admin_excluded_records',[]))|{row['key'] for row in approved['excluded_candidates']})
                summary=updated.get('summary',{})
                for row in approved['excluded_candidates']:
                    for key in ('total',row['status']):
                        if key in summary:summary[key]=max(0,summary[key]-1)
                item.snapshot=updated;db.session.add(item)
            else:
                if approved['action']=='archive_job':params['admin_archived']=True
                else:params.pop('admin_archived',None)
                item.params=params;db.session.add(item)
        job.state='completed';job.result={'backup':info,'completed_at':now(),'action':approved['action'],'target':approved['target']}
        if purging:
            job.state='queued';job.result={**job.result,'purge':cleanup,'metadata_removed_at':now()}
        source.state='completed';source.result={'apply_job':job.id}
        db.session.add(source);db.session.add(job);uow.commit()
    if approved['action']=='delete_job':
        descriptor=approved.get('job',{}).get('snapshot',{}).get('record_store')
        if descriptor:
            # The complete SQLite file was included in the verified ZIP before
            # deleting the journal. Remove only that exact private artifact.
            from .preview import store_path
            store_path(descriptor).unlink()
    if purging:
        from .published_purge import finish
        finish(job)


def preserve_removed_identities(job,approved):
    """Legacy imports may have identifiers without an existing import claim."""
    if approved['action'] not in {'purge_published','delete_draft','withdraw_record'}:return
    from .adapters import converter
    from .service import tokens
    metadata=converter(current_app.config['ARGILOTECA_OPENALEX_ROOT'])[0]
    for token in tokens(approved['record']['data'],metadata):
        if db.session.get(OpenAlexClaim,token) is None:
            db.session.add(OpenAlexClaim(token=token,draft_id=approved['target'],job_id=job.id,
                payload_sha256=digest(approved['record']['raw'])))


def apply_record(identity,p,uow):
    rid=p['target'];kind=p['record']['kind'];action=p['action'];revision=p['record']['data']['revision_id']
    if action=='delete_draft':return service.delete_draft(identity,rid,revision_id=revision,uow=uow)
    if action=='withdraw_record':return service.delete_record(identity,rid,{'removal_reason':{'id':'retracted'},'is_visible':True,
        'note':p['reason'],'citation_text':p['title']},revision_id=revision,uow=uow)
    if action=='restore_record':return service.restore_record(identity,rid,uow=uow)
    item=(service.read if kind=='published' else service.read_draft)(identity,rid);record=item._record
    if action=='remove_community':
        before=deepcopy(dict(record.parent));cid=p['selection']
        if kind=='published':
            processed,errors=rdm_extension.record_communities_service.remove(identity,rid,{'communities':[{'id':cid}]},uow=uow)
            if errors or not processed:raise ValueError('A remoção nativa recusou esta comunidade: '+str(errors))
        else:
            record.parent.communities.remove(cid)
            uow.register(ParentRecordCommitOp(record.parent,indexer_context={'service':service},bulk_index=False))
        # The public community service resolves its own parent API object.
        # Read its flushed JSON rather than our earlier API object's cache.
        from invenio_rdm_records.records.models import RDMParentMetadata
        after=db.session.query(RDMParentMetadata.json).filter_by(id=record.parent.id).scalar()
        expected=set(before.get('communities',{}).get('ids',[]))-{cid}
        if set(after.get('communities',{}).get('ids',[]))!=expected or after.get('access')!=before.get('access'):
            raise ValueError('A remoção alterou vínculos ou acesso além da prévia.')
        return
    fields=deepcopy(record.get('custom_fields',{}));metadata=deepcopy(record.get('metadata',{}))
    if action=='remove_connection':
        from ..scientific.connections import FIELD,reconcile_native_relations,validate_links
        old=fields.get(FIELD,[]);links=[l for l in old if l['record_id']!=p['selection']]
        validate_links(identity,rid,links,old);metadata,links=reconcile_native_relations(metadata,old,links);fields[FIELD]=links
    elif action=='clear_coordinates':fields=clear_coordinates(fields,p['selection'])
    elif action=='remove_orcid':metadata=remove_orcid(metadata,p['selection'])
    else:
        from ..scientific.drx_links import set_link,sync_metadata
        from ..scientific.admin_raw_views import store
        for link in p['drx_links'] if action=='remove_drx_many' else [p['drx_link']]:
            set_link(identity,{'id':link['raw_id'],'sha256':link['sha256']},rid,state='removed',evidence=p['reason'],expected_revision=link['revision'],actor=identity.id)
        native=sync_metadata(identity,rid,{r['id']:r for r in store().rows()})
        uow.register(RecordCommitOp(native,indexer=service.indexer,index_refresh=True));return
    if kind=='draft':service.update_draft(identity,rid,{'metadata':metadata,'custom_fields':fields},revision_id=revision,uow=uow)
    else:
        record['metadata']=metadata;record['custom_fields']=fields
        uow.register(RecordCommitOp(record,indexer=service.indexer,index_refresh=True))


def lot_job(job,identity,approved):
    from .tasks import atomic_json
    queue=Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE']);response=queue/(job.id+'.result.json')
    if response.exists():
        from .adapters import read_json
        result=read_json(response,queue)
        if result.get('state')!='completed':raise ValueError(result.get('message','Falha no agente do Mac.'))
        job.state='completed';job.result=result
        source=db.session.get(OpenAlexJob,job.params['source_job']);source.state='completed';source.result={'apply_job':job.id}
        db.session.commit();return
    request=queue/(job.id+'.request.json')
    if request.exists():
        # Once dispatched the Mac may already have renamed/deleted the source.
        # Poll the durable outcome; never rebuild/replay the destructive request.
        job.state='waiting_host';db.session.commit();return
    import time
    if not (queue/'heartbeat.json').exists() or time.time()-(queue/'heartbeat.json').stat().st_mtime>30:raise ValueError('O agente do Mac está offline. Inicie-o e gere outra prévia.')
    with UnitOfWork(db.session) as uow:
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
        others=db.session.query(OpenAlexJob.id).filter(OpenAlexJob.kind=='clean_apply',OpenAlexJob.state.in_(ACTIVE),OpenAlexJob.id!=job.id,
            OpenAlexJob.snapshot['plan']['kind'].as_string()=='lot',OpenAlexJob.snapshot['plan']['target'].as_string()==approved['target'])
        if others.first():
            raise ValueError('Outra manutenção deste lote está ativa. Aguarde e gere outra prévia.')
        approved=current_plan(identity,approved)
        info=maintenance_files.backup(current_app.config['ARGILOTECA_OPENALEX_ROOT'],queue,job.id,approved)
        job.result={'backup':info,'message':'Manutenção aguardando ou em execução no Mac.'};job.state='waiting_host';db.session.add(job);uow.commit()
    # Commit the durable audit/outbox before the Mac can see a destructive
    # request. Recovery fills the dispatch gap if the worker stops here.
    atomic_json(request,{'version':1,'id':job.id,'operation':'maintenance_lot','params':{'plan':approved,'backup':info}})
