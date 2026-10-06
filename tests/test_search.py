import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from bluegene.store import Store
from bluegene.search import Search,public_search,rank_hits,safe_url,ArchiveRedirect

class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'test.sqlite3');self.p=self.s.project('Test')
        self.calls=[]
        def transport(url,**kw):
            self.calls.append(url)
            return {'response':{'numFound':1,'docs':[{'identifier':'test-book','title':'Eleanor Example in Boston','description':'Public catalog entry'}]}}
        self.ai=SimpleNamespace(status=lambda:{'preferences':{'ai_enabled':True}},key=lambda p:'test-key',metadata=lambda p,m:{'id':m})
        self.search=Search(self.s,self.ai,transport)
    def tearDown(self):self.s.db.close();self.tmp.cleanup()
    def preview(self,**kw):return self.search.prepare(dict(project=self.p,queries=['"Eleanor Example"'],**kw))
    def run_search(self,**kw):return self.search.run(self.preview(**kw)['token'],True)
    def test_consent_cache_force_and_single_use(self):
        p=self.preview()
        with self.assertRaisesRegex(ValueError,'Consent'):self.search.run(p['token'])
        first=self.search.run(p['token'],True)
        with self.assertRaisesRegex(ValueError,'expired'):self.search.run(p['token'],True)
        second=self.run_search();self.assertTrue(second['cached']);self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.calls),1)
        self.run_search(force=True);self.assertEqual(len(self.calls),2)
    def test_living_scope_redaction(self):
        person=self.s.save(self.p,'person',{'name':'Eleanor Example','living':'unknown','notes':'PRIVATE'})
        p=self.preview(person=person['id']);self.assertNotIn('PRIVATE',str(p['outbound']));self.assertEqual(set(p['outbound']),{'queries'})
        with self.assertRaisesRegex(ValueError,'Explicitly'):self.search.run(p['token'],True)
        self.search.run(p['token'],True,True)
    def test_failures_not_negative_evidence(self):
        def failed(url):raise ValueError('HTTP 403 refused')
        self.search.transport=failed;r=self.s.get(self.run_search()['id'])
        self.assertEqual(r['data']['status'],'failed');self.assertEqual(self.s.records(self.p,'log')['items'][0]['data']['outcome'],'inaccessible')
    def test_accept_idempotent_and_backup(self):
        r=self.s.get(self.run_search()['id']);hit=r['data']['hits'][0]
        with self.assertRaisesRegex(ValueError,'locator'):self.search.accept(r['id'],hit['id'])
        first=self.search.accept(r['id'],hit['id'],'Catalog entry','Identity unconfirmed')
        second=self.search.accept(r['id'],hit['id'],'Catalog entry');self.assertTrue(second['existing'])
        self.assertEqual(first['citation_id'],second['citation_id']);self.assertEqual(self.s.records(self.p,'assertion')['total'],0)
        self.assertEqual(self.s.records(self.p,'source')['total'],1);self.assertTrue(self.s.inspect_backup(self.s.backup()))
    def test_invalid_schema_and_identifier(self):
        for data in ([],{}, {'response':{'docs':[]}}):
            with self.assertRaises(ValueError):public_search('archive','x',lambda _:data)
        hits,_,_=public_search('archive','x',lambda _:{'response':{'numFound':2,'docs':[{'identifier':'..'},None]}});self.assertEqual(hits,[])
    def test_rank_and_unsafe_links(self):
        h={'title':'Eleanor Example Boston','snippet':'','url':'https://archive.org/details/test','queries':['a']}
        hits=rank_hits([h,dict(h,queries=['b']),dict(h,url='javascript:alert(1)')],{'name':'Eleanor Example','hypotheses':[{'place':'Boston'}]})
        self.assertEqual(len(hits),1);self.assertEqual(hits[0]['score'],80);self.assertEqual(hits[0]['queries'],['a','b'])
        for url in ['http://127.0.0.1/a','http://localhost/a','https://user:pass@host.com/']:self.assertFalse(safe_url(url))
    def test_native_openai_citations_only(self):
        self.ai.transport=lambda *args:{'output':[{'type':'web_search_call','status':'completed','action':{'type':'search','query':'Example'}},{'type':'message','content':[{'type':'output_text','text':'Result https://invented.example','annotations':[{'type':'url_citation','url':'https://archive.org/details/test','title':'Verified tool citation','start_index':0,'end_index':6}]}]}]}
        r=self.s.get(self.run_search(engine='openai',model='test-model')['id']);self.assertEqual(len(r['data']['hits']),1)
        self.assertEqual(self.s.records(self.p,'log')['items'][0]['data']['outcome'],'possible match')
        self.assertNotIn('invented',r['data']['hits'][0]['url'])
    def test_no_tool_execution_is_failed(self):
        self.ai.transport=lambda *args:{'output':[]}
        r=self.s.get(self.run_search(engine='openai',model='test-model')['id']);self.assertEqual(r['data']['status'],'failed')
    def test_anthropic_results_and_partial(self):
        self.ai.transport=lambda *args:{'stop_reason':'pause_turn','content':[{'type':'server_tool_use','id':'a','name':'web_search','input':{'query':'Example'}},{'type':'web_search_tool_result','tool_use_id':'a','content':[{'type':'web_search_result','url':'https://archive.org/details/test','title':'Result'}]},{'type':'text','text':'Found','citations':[{'type':'web_search_result_location','url':'https://archive.org/details/test','cited_text':'Excerpt'}]}]}
        r=self.s.get(self.run_search(engine='anthropic',model='test-model')['id']);self.assertEqual(r['data']['status'],'partial');self.assertEqual(r['data']['hits'][0]['snippet'],'Excerpt')
    def test_ocr_retains_matches_without_assertions(self):
        r=self.s.get(self.run_search()['id']);hit=r['data']['hits'][0]
        self.search.transport=lambda url,**kw: 'Eleanor Example lived here' if kw.get('raw') else {'files':[{'format':'DjVuTXT','name':'book.txt','size':'30'}]}
        result=self.search.ocr(r['id'],hit['id']);self.assertEqual(result['matches'],1);self.assertEqual(self.s.records(self.p,'source')['total'],0)
        self.search.transport=lambda *a,**kw:{'metadata':{'access-restricted-item':'true'}}
        with self.assertRaisesRegex(ValueError,'restricted'):self.search.ocr(r['id'],hit['id'])
    def test_redirect_restrictions(self):
        from urllib.request import Request
        for url in ['https://evil.example/file','http://archive.org/file','https://archive.org.evil.example/file']:
            with self.assertRaises(ValueError):ArchiveRedirect().redirect_request(Request('https://archive.org/download/test'),None,302,'',{},url)
    def test_atomic_save_rollback(self):
        with self.assertRaises(ValueError):self.s.save_many([dict(p=self.p,kind='source',data={'title':'rollback'}),dict(p=self.p,kind='citation',data={'source_id':'missing','locator':'x'})])
        self.assertEqual(self.s.records(self.p,'source')['total'],0)
