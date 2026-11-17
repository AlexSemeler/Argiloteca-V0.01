"""Offline OAI, boolean queries, audit/resumption and private PDF download tests."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

PACKAGE=Path(__file__).resolve().parents[2]/'argiloteca/repositories'
spec=importlib.util.spec_from_file_location('oai_test_runtime',PACKAGE/'__init__.py',submodule_search_locations=[str(PACKAGE)])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from oai_test_runtime import client,network,pdfs
ROWS=[{'id':'kaolinite','title':{'pt':'Caulinita','en':'Kaolinite'}},{'id':'illite','title':{'pt':'Ilita','en':'Illite'}}]


def record(number=1970,title='Caulinita e cerâmica',deleted=False,repository='lume'):
    host='www.lume.ufrgs.br' if repository=='lume' else 'repositorio.ufsc.br';prefix='10183' if repository=='lume' else '123456789'
    return f'''<record><header{' status="deleted"' if deleted else ''}><identifier>oai:{host}:{prefix}/{number}</identifier><datestamp>2026-10-30T00:00:00Z</datestamp><setSpec>com_{prefix}_2</setSpec></header>{'' if deleted else f'<metadata><oai_dc:dc><dc:title>{title}</dc:title><dc:creator>Silva, Maria</dc:creator><dc:description>Observação de difração de raios X</dc:description><dc:subject>Argilominerais</dc:subject><dc:date>2024-10-01T00:00:00Z</dc:date><dc:date>2020</dc:date><dc:type>Tese</dc:type><dc:identifier>http://hdl.handle.net/{prefix}/{number}</dc:identifier><dc:language>por</dc:language><dc:rights>Open Access</dc:rights></oai_dc:dc></metadata>'}</record>'''


def page(records=None,token=None,error=None):
    inside=f'<error code="{error}">Source error</error>' if error else '<ListRecords>'+''.join(records if records is not None else [record()])+(f'<resumptionToken>{token}</resumptionToken>' if token is not None else '')+'</ListRecords>'
    return ('<OAI-PMH xmlns="'+client.OAI+'" xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:dc="'+client.DC+'">'+inside+'</OAI-PMH>').encode()


def params(**kwargs): return client.parameters({'term':'kaolinite','max_pages':1,**kwargs},ROWS)
def fetch(body): return (body,{'url':'https://lume.ufrgs.br/oai/request','content_type':'application/xml'})


class QueryTests(unittest.TestCase):
    def test_three_modes_bilingual_and_combination(self):
        for values,mode in [({'term':'kaolinite'},'vocabulary'),({'term':'','free_text':'XRD'},'free'),({'term':'kaolinite','free_text':'cerâmica'},'combined')]:
            self.assertEqual(params(**values)['search_mode'],mode)
        query=client.search_queries(params(free_text='cerâmica AND (XRD OR "difração de raios X")'),ROWS)[0]['query']
        node=client.expression(query)
        self.assertTrue(client.evaluate(node,client.fold('CAULINITA ceramica difração de raios X')))
        self.assertFalse(client.evaluate(node,client.fold('caulinita solo')))

    def test_not_precedence_phrase_prefix_and_boundaries(self):
        for query,text,expected in [('XRD OR clay AND ceramic','XRD',True),('clay NOT soil','clay soil',False),('argila*','argilas',True),('argila','argilas',False),('"raios X"','raios   X',True)]:
            self.assertEqual(client.evaluate(client.expression(query),client.fold(text)),expected)

    def test_invalid_grammar_and_limits(self):
        for q in ['(XRD','XRD AND','AND XRD','"unclosed','*','a*b','('*25+'x'+')'*25]:
            with self.subTest(q=q),self.assertRaises(ValueError):client.expression(q)
        for data in [{'repository':'unknown'},{'term':'unknown'},{'max_pages':101},{'offset':1},{'free_text':'x\n'},{'from_date':'2024-02-31'},{'catalog_cycle':0}]:
            with self.subTest(data=data),self.assertRaises(ValueError):params(**data)

    def test_scope_defaults_cycles_dates(self):
        self.assertEqual(params()['set_spec'],'com_10183_2')
        self.assertEqual(params(repository='ufsc')['set_spec'],'')
        self.assertEqual(params(set_spec='__all__')['set_spec'],'')
        self.assertNotEqual(client.catalog_path('/tmp',params()),client.catalog_path('/tmp',params(catalog_cycle=2)))

    def test_entire_lume_scope_survives_agent_revalidation_and_continuation(self):
        canonical=params(set_spec='__all__')
        self.assertEqual(canonical['set_spec'],'')
        self.assertEqual(client.parameters(canonical,ROWS),canonical)
        self.assertEqual(client.parameters(params(),ROWS)['set_spec'],'com_10183_2')

    def test_all_offset_and_exact_term(self):
        self.assertEqual(client.search_queries(params(term='__all__',offset=1),ROWS)[0]['term']['id'],'illite')


class OAITests(unittest.TestCase):
    def test_namespaces_header_and_raw_preserved(self):
        rows,token=client.parse_page(page(token='cursor+/=='),'lume')
        self.assertEqual(token,'cursor+/==');self.assertEqual(rows[0]['identifier'],'oai:www.lume.ufrgs.br:10183/1970')
        self.assertIn('Tese',rows[0]['xml'])
        self.assertEqual(client.parse_page(page([record(repository='ufsc')]),'ufsc')[0][0]['dc']['date'][-1],'2020')

    def test_deleted_record_preserved_but_not_importable(self):
        raw=client.parse_page(page([record(deleted=True)]),'lume')[0][0]
        self.assertTrue(raw['deleted'])
        with self.assertRaises(ValueError):client.build_payload(raw,'lume')

    def test_no_records_error_vs_bad_token_and_html(self):
        self.assertEqual(client.parse_page(page(error='noRecordsMatch'),'lume'),([],None))
        for body in [page(error='badResumptionToken'),page(error='badArgument'),b'<html>error</html>',page([]),b'<!DOCTYPE x><bad/>']:
            with self.assertRaises(ValueError):client.parse_page(body,'lume')

    def test_captcha_not_treated_as_empty_xml(self):
        with self.assertRaises(network.AccessBlocked):client.parse_page(b'<html><div class="cf-turnstile"></div></html>','ufsc')

    def test_identifier_mismatch_and_foreign_handle_rejected(self):
        body=page().replace(b'http://hdl.handle.net/10183/1970',b'http://hdl.handle.net/10183/9999')
        with self.assertRaises(ValueError):client.parse_page(body,'lume')
        with self.assertRaises(ValueError):client.parse_page(page([record(repository='ufsc')]),'lume')

    def test_only_declared_identifier_doi_is_primary(self):
        raw=client.parse_page(page(),'lume')[0][0]
        raw['dc']['description'].append('A citation DOI 10.1234/cited is not primary')
        self.assertFalse(any(v['scheme']=='doi' for v in client.build_payload(raw,'lume')[0]['metadata']['identifiers']))
        raw['dc']['identifier'].append('https://doi.org/10.1234/declared')
        self.assertIn({'scheme':'doi','identifier':'10.1234/declared'},client.build_payload(raw,'lume')[0]['metadata']['identifiers'])
        raw['dc']['identifier'].append('10.1234/another')
        self.assertIn('ambiguous_doi',[i['code'] for i in client.build_payload(raw,'lume')[1]])

    def test_source_date_ignores_accession_and_blocks_ambiguity(self):
        self.assertEqual(client.source_date(['2007-01-01T00:00:00Z','2001']),'2001')
        self.assertEqual(client.source_date(['2001','2002']),'')
        self.assertEqual(client.source_date(['2020-02-31']),'')

    def test_mapping_is_bibliographic_no_guessed_science_or_license(self):
        raw=client.parse_page(page(),'lume')[0][0];payload,issues=client.build_payload(raw,'lume')
        md=payload['metadata'];self.assertEqual(md['publication_date'],'2020');self.assertEqual(md['resource_type']['id'],'publication-dissertation')
        self.assertEqual(md['creators'][0]['person_or_org']['family_name'],'Silva')
        self.assertEqual(md['identifiers'][0],{'scheme':'handle','identifier':'10183/1970'})
        self.assertFalse(payload['files']['enabled']);self.assertNotIn('custom_fields',payload);self.assertNotIn('rights',md)
        self.assertIn('license_missing',[i['code'] for i in issues])


class HarvestTests(unittest.TestCase):
    def test_resume_uses_token_alone_and_records_catalogue_coverage(self):
        with tempfile.TemporaryDirectory() as base,patch.object(client,'fetch_bytes',side_effect=[fetch(page(token='a/b==')),fetch(page([record(1971)],token=''))]) as f:
            folder,s=client.harvest(base,params());self.assertFalse(s['complete']);self.assertEqual(s['available_records'],1)
            folder,s=client.harvest(base,params());self.assertTrue(s['complete']);self.assertEqual(s['available_records'],2)
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(f.call_args.args[0]).query)
            self.assertEqual(query,{'verb':['ListRecords'],'resumptionToken':['a/b==']})
            client.harvest(base,params());self.assertEqual(f.call_count,2)

    def test_source_cannot_ignore_requested_set(self):
        with tempfile.TemporaryDirectory() as base,patch.object(client,'fetch_bytes',return_value=fetch(page().replace(b'com_10183_2',b'com_10183_99'))):
            with self.assertRaises(ValueError):client.harvest(base,params())

    def test_repeated_token_cannot_loop(self):
        with tempfile.TemporaryDirectory() as base,patch.object(client,'fetch_bytes',side_effect=[fetch(page(token='a')),fetch(page([record(1971)],token='a'))]):
            client.harvest(base,params())
            with self.assertRaises(ValueError):client.harvest(base,params())

    def test_deleted_updates_catalogue_without_deleting_native_records(self):
        with tempfile.TemporaryDirectory() as base,patch.object(client,'fetch_bytes',side_effect=[fetch(page(token='a')),fetch(page([record(deleted=True)],token=''))]):
            client.harvest(base,params());_,s=client.harvest(base,params());self.assertEqual(s['available_records'],0);self.assertEqual(s['deleted'],1)

    def test_collect_searches_once_deduplicates_and_immutable_lot(self):
        with tempfile.TemporaryDirectory() as base,patch.object(client,'fetch_bytes',return_value=fetch(page())) as f:
            folder=Path(base)/'lotes'/('oai_'+'a'*32)
            r=client.collect(folder,params(free_text='cerâmica'),ROWS);self.assertEqual(r['payloads'],1);self.assertFalse(r['partial'])
            self.assertTrue(all(client.sha(folder/n)==h for n,h in r['input_hashes'].items()))
            client.collect(folder,params(free_text='cerâmica'),ROWS);self.assertEqual(f.call_count,1)
            (folder/'records.json').write_text('[]')
            with self.assertRaises(ValueError):client.collect(folder,params(free_text='cerâmica'),ROWS)

    def test_cache_only_search_no_network_and_explicit_partial(self):
        with tempfile.TemporaryDirectory() as base,patch.object(client,'fetch_bytes') as f:
            r=client.collect(Path(base)/'lotes'/('oai_'+'a'*32),params(max_pages=0),ROWS)
            self.assertEqual(r['payloads'],0);self.assertTrue(r['partial']);f.assert_not_called()

    def test_failed_fetch_retains_checkpoint(self):
        with tempfile.TemporaryDirectory() as base,patch.object(client,'fetch_bytes',side_effect=[fetch(page(token='a')),OSError('offline')]):
            client.harvest(base,params())
            with self.assertRaises(OSError):client.harvest(base,params())
            state=json.loads((client.catalog_path(base,params())/'status.json').read_text());self.assertEqual(state['cursor'],'a')


class Response(BytesIO):
    def __init__(self,body,url='https://lume.ufrgs.br/bitstream/10183/1970/1/test.pdf',content_type='application/pdf',length=None):
        super().__init__(body);self.url=url;self.headers={'Content-Type':content_type,'Content-Length':str(len(body) if length is None else length)}
PDF=b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'


class PDFTests(unittest.TestCase):
    def test_only_same_repository_and_same_handle_pdf_links(self):
        base='https://lume.ufrgs.br/handle/10183/1970'
        self.assertTrue(pdfs.linked_pdf('/bitstream/handle/10183/1970/test.pdf?sequence=1','lume','10183/1970',base))
        for value in ['https://evil.example/test.pdf','/bitstream/10183/9999/1/test.pdf','/bitstream/10183/1970/1/test.pdf.txt','http://127.0.0.1/test.pdf','/bitstream/10183/1970/../../9999/a.pdf']:
            self.assertIsNone(pdfs.linked_pdf(value,'lume','10183/1970',base))

    def test_download_signature_eof_hash_and_existing_content(self):
        with tempfile.TemporaryDirectory() as base,patch.object(pdfs,'open_public',side_effect=lambda u:Response(PDF)):
            result=pdfs.download('https://lume.ufrgs.br/bitstream/10183/1970/1/test.pdf',base,1000)
            self.assertEqual(result['sha256'],hashlib.sha256(PDF).hexdigest());self.assertEqual(result['bytes'],len(PDF))
            self.assertEqual(pdfs.download(result['source_url'],base,1000)['sha256'],result['sha256'])
            (Path(base)/result['filename']).write_bytes(b'tamper')
            with self.assertRaises(ValueError):pdfs.download(result['source_url'],base,1000)

    def test_html_truncation_mime_and_size_limits_rejected(self):
        for body,mime,length,budget in [(b'<html>login</html>','text/html',None,1000),(b'%PDF-1.4\ntruncated','application/pdf',None,1000),(PDF,'text/html',None,1000),(PDF,'application/pdf',999,1000),(PDF,'application/pdf',None,2)]:
            with tempfile.TemporaryDirectory() as base,patch.object(pdfs,'open_public',side_effect=lambda u:Response(body,content_type=mime,length=length)):
                with self.assertRaises(ValueError):pdfs.download('https://lume.ufrgs.br/test.pdf',base,budget)
                self.assertEqual(list(Path(base).iterdir()),[])

    def test_no_login_captcha_bypass_and_redirect_allowlist(self):
        for url in ['https://evil.example/','http://127.0.0.1/','https://lume.ufrgs.br:8080/','https://user@lume.ufrgs.br/']:
            with self.assertRaises(ValueError):network.safe_url(url)
        request=__import__('urllib.request',fromlist=['Request']).Request('https://lume.ufrgs.br/handle/10183/1970')
        for url in ['https://evil.example/x','https://repositorio.ufsc.br/x','https://lume.ufrgs.br/login']:
            with self.assertRaises(ValueError):network.Redirects().redirect_request(request,None,302,'',{},url)

    def test_restricted_source_not_downloaded(self):
        with self.assertRaises(network.AccessBlocked):pdfs.discover({'repository':'lume','handle':'10183/1970','url':'https://lume.ufrgs.br/handle/10183/1970','rights':['info:eu-repo/semantics/restrictedAccess']})

    def test_manifest_and_completed_blobs_are_verified(self):
        row={'key':'one','title':'Thesis','repository':'lume','handle':'10183/1970','url':'https://lume.ufrgs.br/handle/10183/1970','source_metadata_sha256':'x','rights':[]}
        url='https://lume.ufrgs.br/bitstream/10183/1970/1/test.pdf'
        with tempfile.TemporaryDirectory() as base,patch.object(pdfs,'discover',return_value=([url],{'pdf_links_found':1})),patch.object(pdfs,'open_public',side_effect=lambda u:Response(PDF)):
            r=pdfs.collect(base,'a'*32,[row]);self.assertTrue(r['complete']);self.assertEqual(r['summary']['downloaded'],1)
            pdfs.collect(base,'a'*32,[row])
            blob=Path(base)/'pdfs/blobs'/r['items']['one']['files'][0]['filename'];blob.write_bytes(b'changed')
            with self.assertRaises(ValueError):pdfs.collect(base,'a'*32,[row])


if __name__=='__main__':unittest.main()
