"""Private curated-draft transfer; never invokes publication or changes a classifier."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from argiloteca.scientific import admin_raw_curation as curation
from test_admin_raw_library import store, inputs
from argiloteca.scientific.admin_raw_service import submit_trio


def form():
    return {'title':'Curated trio', 'family_name':'Curator', 'given_name':'Test',
        'publication_date':'2026-10-20', 'license':'cc-by-4.0', 'description':'A < B',
        'confirm_links':'yes','confirm_anonymity':'yes','confirm_rights':'yes'}


def native():
    service=MagicMock()
    service.create.return_value.to_dict.return_value={'id':'test-draft'}
    service.draft_files.set_file_content.return_value.to_dict.return_value={}
    entries=[]
    def capture(identity,draft_id,name,stream,**kwargs):
        content=stream.getvalue()
        entries.append({'key':name,'status':'completed','size':len(content),'checksum':'md5:'+hashlib.md5(content).hexdigest()})
        return SimpleNamespace(to_dict=lambda:{})
    service.draft_files.set_file_content.side_effect=capture
    service.draft_files.list_files.return_value.to_dict.side_effect=lambda:{'entries':entries}
    uow=MagicMock();uow.__enter__.return_value=uow
    return service,uow


def test_native_draft_uses_only_anonymous_derivatives_and_is_idempotent(store,tmp_path):
    submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    row=store.rows()[0];before=deepcopy(store.rows());service,uow=native()
    links=curation.CurationLinks(tmp_path/'links');identity=SimpleNamespace(id='caller')
    result=curation.prepare_draft(store,row,links,form(),identity,service=service,uow_factory=lambda:uow)
    assert result['draft_id']=='test-draft'
    assert links.read(row['sample_code'])==result
    assert links.path(row['sample_code']).stat().st_mode&0o777==0o600
    assert service.create.call_args.args[0] is identity
    assert service.create.call_args.args[1]['metadata']['resource_type']['id']=='dataset'
    assert service.create.call_args.args[1]['metadata']['description']=='<p>A &lt; B</p>'
    assert service.draft_files.commit_file.call_count==3
    for call in service.draft_files.set_file_content.call_args_list:
        assert call.args[0] is identity and call.args[2].startswith('ARC-')
        assert b'PRIVATE-ID' not in call.args[3].getvalue()
    uow.commit.assert_called_once()
    assert curation.prepare_draft(store,row,links,form(),identity,service=service,uow_factory=lambda:uow)==result
    service.create.assert_called_once();service.publish.assert_not_called()
    assert store.rows()==before


@pytest.mark.parametrize('reason',['missing','duplicate_role','test','corrupt','public'])
def test_ineligible_trio_cannot_create_draft(store,tmp_path,reason):
    submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    rows=store.rows();row=rows[0];service,uow=native()
    if reason=='missing':rows.pop()
    elif reason=='duplicate_role':rows[1]['preparation']=rows[0]['preparation']
    elif reason=='test':rows[0]['test_only']=True
    elif reason=='public':rows[0]['access']='public_snapshot'
    else:(store.uploads/row['sample_code']/'files'/row['filename']).write_bytes(b'corrupt')
    store.rows=lambda:rows
    assert not curation.eligibility(store,row)['eligible']
    with pytest.raises(curation.CurationBlocked):
        curation.prepare_draft(store,row,curation.CurationLinks(tmp_path/'links'),form(),None,service=service,uow_factory=lambda:uow)
    service.create.assert_not_called();service.publish.assert_not_called()


@pytest.mark.parametrize('key,value',[('family_name',''),('publication_date','invalid'),('license','unreviewed'),('confirm_links',''),('confirm_anonymity',''),('confirm_rights','')])
def test_missing_metadata_or_curatorial_confirmation_is_blocked(key,value):
    data=form();data[key]=value
    with pytest.raises(curation.CurationBlocked):curation.draft_metadata(data)


def test_failed_file_transfer_rolls_back_before_commit(store,tmp_path):
    submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    service,uow=native();service.draft_files.set_file_content.side_effect=None;service.draft_files.set_file_content.return_value.to_dict.return_value={'errors':['failed']}
    links=curation.CurationLinks(tmp_path/'links')
    with pytest.raises(curation.CurationBlocked,match='transfer'):
        curation.prepare_draft(store,store.rows()[0],links,form(),SimpleNamespace(id='caller'),service=service,uow_factory=lambda:uow)
    uow.commit.assert_not_called();assert uow.__exit__.call_args.args[0] is curation.CurationBlocked
    service.publish.assert_not_called();assert links.read(store.rows()[0]['sample_code']) is None


def test_existing_link_failure_does_not_duplicate_draft(store,tmp_path):
    submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    row=store.rows()[0];service,uow=native();links=curation.CurationLinks(tmp_path/'links')
    identity=SimpleNamespace(id='caller')
    curation.prepare_draft(store,row,links,form(),identity,service=service,uow_factory=lambda:uow)
    service.read_draft.side_effect=RuntimeError('deleted or no access')
    with pytest.raises(RuntimeError):curation.prepare_draft(store,row,links,form(),identity,service=service,uow_factory=lambda:uow)
    service.create.assert_called_once();service.publish.assert_not_called()


def test_manual_native_publication_and_deleted_draft_have_explicit_states():
    service,_=native();link={'draft_id':'test-draft'}
    assert curation.linked_state(None,None,service) is None
    service.read.side_effect=KeyError('not published')
    assert curation.linked_state(link,None,service)=='draft'
    service.read_draft.side_effect=KeyError('deleted')
    assert curation.linked_state(link,None,service)=='unavailable'
    service.read.side_effect=None;service.read.return_value.to_dict.return_value={'is_published':True}
    assert curation.linked_state(link,None,service)=='published'
    service.publish.assert_not_called()


def test_native_pending_authorship_and_date_can_be_saved_without_fabrication(store,tmp_path):
    submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    service,uow=native();identity=SimpleNamespace(id='caller')
    service.create.return_value.to_dict.return_value={'id':'test-draft','errors':[
        {'field':'metadata.creators','messages':['Missing data']},
        {'field':'metadata.publication_date','messages':['Missing data']}]}
    pending={'title':'Pending metadata','confirm_links':'yes','confirm_anonymity':'yes'}
    result=curation.prepare_draft(store,store.rows()[0],curation.CurationLinks(tmp_path/'links'),pending,identity,service=service,uow_factory=lambda:uow)
    payload=service.create.call_args.args[1]
    assert payload['metadata']=={'title':'Pending metadata','resource_type':{'id':'dataset'}}
    assert result['pending_metadata']==['metadata.creators','metadata.publication_date','metadata.rights']
    service.publish.assert_not_called();uow.commit.assert_called_once()
