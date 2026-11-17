"""Topic routing uses controlled terms, explicit evidence and reviewed targets."""
from copy import deepcopy
import os
import unittest
from argiloteca.openalex.classification import load_vocabulary,classify,attach_communities


class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vocabulary,cls.version=load_vocabulary(os.environ['ARGILOTECA_OPENALEX_ROOT'])
        slugs={t['slug'] for t in cls.vocabulary if t['slug']}
        cls.catalog={s:{'id':s,'slug':s,'title':s,'allowed':True} for s in slugs}

    def row(self,title,description='',subjects=None):
        return {'payload':{'metadata':{'title':title,'description':description,'subjects':subjects or []}},'provenance':[]}

    def classify(self,row,catalog=None):
        return classify(row,self.vocabulary,self.catalog if catalog is None else catalog,self.version)

    def test_english_and_portuguese_names_route_to_same_existing_collection(self):
        for title in ('Kaolinite surface chemistry','Química de superfície da caulinita'):
            result=self.classify(self.row(title))
            self.assertEqual([c['slug'] for c in result['communities']],['caulim-serpentina'])
            self.assertEqual(result['evidence'][0]['source'],'title')

    def test_mixed_layer_name_beats_embedded_generic_terms(self):
        result=self.classify(self.row('Illite-smectite structural properties'))
        self.assertEqual([c['slug'] for c in result['communities']],['argilominerais-interestratificados'])
        self.assertEqual([h['term'] for h in result['evidence']],['illite-smectite'])

    def test_multiple_independent_topics_can_have_multiple_communities(self):
        result=self.classify(self.row('Kaolinite and montmorillonite interactions'))
        self.assertEqual({c['slug'] for c in result['communities']},{'caulim-serpentina','esmectitas'})

    def test_word_boundaries_and_unknown_topics_do_not_guess_destinations(self):
        for title in ('unusualkaoliniteword','General environmental study'):
            result=self.classify(self.row(title))
            self.assertEqual(result['communities'],[])
            self.assertEqual(result['state'],'needs_review')

    def test_retired_or_unauthorized_community_stays_unassigned(self):
        result=self.classify(self.row('kaolinite'),{})
        self.assertEqual(result['unavailable'],['caulim-serpentina'])
        self.assertEqual(result['communities'],[])

    def test_extraction_term_is_explicit_fallback_evidence(self):
        row=self.row('A generic bibliographic title')
        row['provenance']=[{'origin':{'termo_en':'Kaolinite','termo_pt':'Caulinita'}}]
        result=self.classify(row)
        self.assertEqual(result['evidence'][0]['source'],'extraction_term')
        self.assertEqual(result['communities'][0]['slug'],'caulim-serpentina')

    def test_original_payload_and_science_are_never_modified(self):
        row=self.row('kaolinite');before=deepcopy(row)
        self.classify(row)
        self.assertEqual(row,before)
        self.assertNotIn('custom_fields',row['payload'])

    def test_tampered_classification_and_unreviewed_target_are_rejected(self):
        result=self.classify(self.row('kaolinite'))
        changed=deepcopy(result);changed['communities'][0]['id']='invented'
        with self.assertRaises(ValueError):attach_communities(None,None,changed,[],None)
        with self.assertRaises(ValueError):attach_communities(None,None,result,['invented'],None)


class ClassificationReportTests(unittest.TestCase):
    def test_completed_import_shows_confirmed_destinations_only(self):
        from jinja2 import Environment
        from pathlib import Path
        from types import SimpleNamespace
        template=Path(__file__).resolve().parents[2]/'argiloteca/templates/semantic-ui/argiloteca/admin_openalex_job.html'
        source=template.read_text().split('<td data-label="{{ oa_t(\'Comunidades\', \'Communities\') }}">',1)[1].split('</td>',1)[0]
        render=Environment().from_string(source).render
        confirmed={'id':'one','title':'Caulim','slug':'caulim-serpentina'}
        proposed={'id':'two','title':'Esmectitas','slug':'esmectitas'}
        context={'oa_t':lambda pt,en:pt,'job':SimpleNamespace(kind='import',state='completed'),
                 'row':{'classification':{'communities':[confirmed,proposed]}}}
        html=render(**context,outcome={'state':'updated','communities':[confirmed]})
        self.assertIn('Confirmadas nesta importação',html)
        self.assertIn('Caulim',html)
        self.assertNotIn('Esmectitas',html)
        html=render(**context,outcome={'state':'updated'})
        self.assertIn('Vínculos anteriores preservados',html)
        self.assertNotIn('/communities/',html)


if __name__=='__main__':unittest.main()
