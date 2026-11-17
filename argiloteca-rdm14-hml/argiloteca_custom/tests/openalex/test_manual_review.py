"""Manual curation invariants: additive links, reviewed decisions, guarded plans."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
from argiloteca.openalex.manual_review import topic_hash,is_reviewed,verify_parent,build_plan,selected_targets


class ManualReviewTests(unittest.TestCase):
    def parent(self):
        return {'access':{'owned_by':{'user':'4'}},'communities':{'ids':['one'],'default':'one'}}

    def test_additive_parent_retains_default_access_and_owner(self):
        before=self.parent();after=deepcopy(before);after['communities']['ids'].append('two')
        verify_parent(before,after,['one','two'])
        self.assertEqual(before,self.parent())

    def test_removed_links_duplicates_default_or_access_changes_fail(self):
        before=self.parent()
        for after in ({'access':before['access'],'communities':{'ids':['two'],'default':'two'}},
                      {'access':before['access'],'communities':{'ids':['one','two','two'],'default':'one'}},
                      {'access':before['access'],'communities':{'ids':['one','two'],'default':'two'}},
                      {'access':{'owned_by':{'user':'5'}},'communities':{'ids':['one','two'],'default':'one'}}):
            with self.assertRaises(ValueError):verify_parent(before,after,['one','two'])

    def test_first_native_default_is_allowed_without_prior_links(self):
        verify_parent({'access':{}},{'access':{},'communities':{'ids':['two'],'default':'two'}},['two'])

    def test_completed_decision_reopens_when_terms_or_links_change(self):
        metadata={'title':'A title','description':'A description','subjects':[]}
        decision={'topic_sha256':topic_hash(metadata),'confirmed_ids':['one','two']}
        self.assertTrue(is_reviewed(metadata,{'one','two','three'},[decision]))
        self.assertFalse(is_reviewed(metadata,{'one'},[decision]))
        self.assertFalse(is_reviewed({**metadata,'title':'Changed title'},{'one','two'},[decision]))
        self.assertTrue(is_reviewed({**metadata,'publisher':'Changed publisher'},{'one','two'},[decision]))

    def test_no_decision_never_counts_as_reviewed(self):
        self.assertFalse(is_reviewed({'title':'Study'},set(),[]))

    def test_empty_oversized_or_ambiguous_keep_selection_rejected(self):
        row={'current_ids':[]}
        for selected,keep,note in (([],False,''),([],True,''),(['one'],True,''),(['one'],False,'a'*2001)):
            with self.assertRaises(ValueError):build_plan(None,row,selected,note,keep)

    def test_unknown_or_unpermitted_community_is_rejected_before_resolution(self):
        for catalog in ({},{'one':{'id':'one','allowed':False}}):
            with self.assertRaises(ValueError):selected_targets(None,['one'],catalog)

    def test_keep_current_plan_does_not_propose_removals_or_new_links(self):
        row={'current_ids':['one'],'kind':'published','raw':{'access':{'record':'restricted'}}}
        ext=Mock()
        with patch('argiloteca.openalex.manual_review.community_catalog',return_value={}),patch('argiloteca.openalex.manual_review.extension',new=ext):
            plan=build_plan(None,row,[],'Curadoria conferida',True)
        self.assertEqual(plan['confirmed_ids'],['one']);self.assertEqual(plan['additions'],[])
        self.assertEqual(plan['row'],row)
        ext.record_communities_service.require_permission.assert_called_once_with(None,'bulk_add')


if __name__=='__main__':unittest.main()
