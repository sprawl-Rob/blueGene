import unittest,tempfile,io,zipfile,json,base64,os
from pathlib import Path
from unittest.mock import patch
from bluegene.store import Store
from bluegene.gedcom import parse,normalize,date_value,unpack,attachment_type,safe_path
from bluegene.recommend import recommend,filter_resources,overlap
from bluegene.seeds import ENTRIES
from bluegene.ai import AI,SCHEMA
FIXTURE=(Path(__file__).parent.parent/'fixtures/fictional-demo.ged').read_bytes()

def archive(files):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():z.writestr(name,content)
    return b.getvalue()
class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'research.sqlite3')
    def tearDown(self):self.s.db.close();self.tmp.cleanup()
    def imported(self,data=FIXTURE,media=None):
        st=self.s.stage_import('test.ged',data,media);result=self.s.commit_import(st,'Test family');return result['project'],result,st
    def test_later_media_for_same_gedcom_does_not_duplicate_people(self):
        p,_,_=self.imported()
        stage=self.s.stage_import('test.ged',FIXTURE,{'media/notebook.txt':b'Fictional notebook'},project=p)
        self.assertFalse(stage['identical'])
        self.s.commit_import(stage,'ignored',identity_confirmed=True)
        self.assertEqual(self.s.records(p,'person')['total'],6)
        self.assertEqual(self.s.records(p,'media')['items'][0]['data']['status'],'matched')
        repeat=self.s.stage_import('test.ged',FIXTURE,{'media/notebook.txt':b'Fictional notebook'},project=p)
        self.assertTrue(repeat['identical'])
    def test_synthetic_exporter_fixtures_and_gedzip(self):
        root=Path(__file__).parent.parent/'fixtures'
        for name in ['synthetic-rootsmagic.ged','synthetic-family-tree-maker.ged','synthetic-gedcom7.gdz']:
            stage=self.s.stage_import(name,(root/name).read_bytes())
            result=self.s.commit_import(stage,name)
            self.assertEqual(self.s.records(result['project'],'person')['total'],6)
            if name.endswith('.gdz'):
                self.assertEqual(stage['report']['container'],'GEDZIP');self.assertEqual(stage['report']['matched_files'],1)
        self.assertIsNone(date_value('a story around 1840')['interval'])
        with self.assertRaisesRegex(ValueError,'ANSEL'):parse(FIXTURE.replace(b'UTF-8',b'ANSEL'))
    def test_concurrent_directory_and_record_reads(self):
        from concurrent.futures import ThreadPoolExecutor
        p,_,_=self.imported()
        def read(i):
            return self.s.records(p,'person')['total'],len(self.s.projects()),self.s.records(p,'assertion')['total']
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(read,range(200)))
        self.assertTrue(all(x[0]==6 and x[1]==1 and x[2]>0 for x in results))
    def test_renumbered_persistent_uid_needs_review(self):
        identifier=b'839a21b9-766b-444b-b272-3d8a001503e5'
        fixture=FIXTURE.replace(b'0 @I1@ INDI',b'0 @I1@ INDI\n1 UID '+identifier)
        p,_,_=self.imported(fixture)
        updated=fixture.replace(b'@I1@',b'@I101@')
        stage=self.s.stage_import('renumbered.ged',updated,project=p)
        self.assertTrue(any('UUID' in x['basis'] for x in stage['person_mappings']))
        with self.assertRaisesRegex(ValueError,'Review all'):self.s.commit_import(stage,'ignored')
        self.s.commit_import(stage,'ignored',identity_confirmed=True)
        self.assertEqual(self.s.records(p,'person')['total'],6)
        conflicting=updated.replace(identifier,b'739a21b9-766b-444b-b272-3d8a001503e5')
        with self.assertRaisesRegex(ValueError,'Persistent identity conflicts'):self.s.stage_import('bad.ged',conflicting,project=p)
    def test_import_field_accounting_and_stable_media(self):
        fixture=FIXTURE.replace(b'1 NAME Eleanor',b'1 SEX F\n1 NAME Eleanor',1)
        p,_,stage=self.imported(fixture,{'media/notebook.txt':b'Fictional media'})
        report=stage['report']['field_accounting']
        self.assertTrue(any(x['tag']=='SEX' for x in report['raw_only']))
        self.assertGreater(report['interpreted_nodes'],0)
        count=self.s.db.execute('SELECT count(*) FROM attachments').fetchone()[0]
        updated=fixture.replace(b'BLUEGENE',b'BLUEGENE_NEW')
        # Header-only changes must not fabricate linked-entity conflicts.
        st=self.s.stage_import('updated.ged',updated,{'media/notebook.txt':b'Fictional media'},project=p)
        self.assertFalse(st['comparison']);self.assertFalse(st['attachments'])
        self.s.commit_import(st,'ignored',identity_confirmed=True)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM attachments').fetchone()[0],count)
        restored=self.s.inspect_backup(self.s.backup());self.assertTrue(restored)
    def test_dates_preserve_uncertainty(self):
        self.assertEqual(date_value('ABT 1840')['interval'],[1835,1845]);self.assertEqual(date_value('BEF 1850')['interval'],[None,1849]);self.assertEqual(date_value('BET 1840 AND 1845')['interval'],[1840,1845]);self.assertIsNone(date_value('@#DHEBREW@ 2 TSH 5600')['interval']);self.assertIsNone(date_value('1731/32')['interval'])
    def test_grammar_hierarchy_versions_encoding(self):
        p=parse(FIXTURE);self.assertEqual(p['version'],'5.5.1');self.assertTrue(p['unsupported']);self.assertEqual(p['roots'][1]['xref'],'@I1@')
        for version in ('5.5','7.0'):
            self.assertEqual(parse(FIXTURE.replace(b'5.5.1',version.encode()))['version'],version)
        with self.assertRaisesRegex(ValueError,'Unrecognized'):parse(FIXTURE.replace(b'5.5.1',b'8.0'))
        with self.assertRaisesRegex(ValueError,'level jump'):parse(FIXTURE.replace(b'1 NAME Eleanor',b'4 NAME Eleanor'))
        with self.assertRaisesRegex(ValueError,'Duplicate cross'):parse(FIXTURE.replace(b'0 @I2@',b'0 @I1@'))
        bad=parse(FIXTURE.replace(b'Eleanor',b'Elea\xffnor',1));self.assertTrue(any('Undecodable' in x for x in bad['warnings']))
        utf16=FIXTURE.decode().replace('UTF-8','UNICODE').encode('utf-16');self.assertEqual(parse(utf16)['encoding'],'utf-16')
    def test_import_citation_links_raw_and_relationships(self):
        p,result,stage=self.imported();people=self.s.records(p,'person')['items'];eleanor=next(x for x in people if x['data']['name']=='Eleanor Whitcomb')
        assertions=self.s.records(p,'assertion',eleanor['id'])['items'];birth=[x for x in assertions if x['data']['type']=='BIRT'];self.assertEqual(len(birth),2)
        self.assertEqual({x['data']['date']['original'] for x in birth},{'ABT 1840','1842'})
        citation=self.s.get(birth[0]['data']['citation_ids'][0]);source=self.s.get(citation['data']['source_id']);self.assertEqual(source['kind'],'source');self.assertTrue(citation['data']['locator'])
        types={r['data']['type'] for r in self.s.records(p,'relationship')['items']};self.assertTrue({'adoptive','unspecified','partner'}<=types)
        raw=self.s.db.execute('SELECT raw,original FROM imports').fetchone();self.assertEqual(raw['original'],FIXTURE);self.assertIn('_CUSTOM',raw['raw']);self.assertIn('<script>',raw['raw']);self.assertEqual(birth[0]['data']['origin']['record'],'@I1@')
    def test_repeat_identical_and_local_edit_conflict(self):
        p,result,stage=self.imported();count=len(self.s.all_records(p));st=self.s.stage_import('test.ged',FIXTURE,project=p);self.assertTrue(st['identical']);self.s.commit_import(st,'ignored');self.assertEqual(count,len(self.s.all_records(p)))
        el=next(x for x in self.s.records(p,'person')['items'] if x['data']['name']=='Eleanor Whitcomb');self.s.save(p,'person',{**el['data'],'name':'My local Eleanor'},id=el['id'],person=el['id'])
        changed=FIXTURE.replace(b'Eleanor /Whitcomb/',b'Ellen /Whitcomb/');st=self.s.stage_import('updated.ged',changed,project=p)
        self.assertTrue(any(x['status']=='conflict' for x in st['comparison']))
        with self.assertRaisesRegex(ValueError,'Review all person'):self.s.commit_import(st,'ignored')
        self.s.commit_import(st,'ignored',True);local=self.s.get(el['id']);self.assertEqual(local['data']['name'],'My local Eleanor');self.assertTrue(local['data']['import_conflicts']);self.assertEqual(count,len(self.s.all_records(p)))
    def test_new_tree_identifiers_separate(self):
        p,_,_=self.imported();q,_,_=self.imported();self.assertNotEqual(p,q);self.assertFalse({r['id'] for r in self.s.all_records(p)}&{r['id'] for r in self.s.all_records(q)})
    def test_undo_and_stale_preview_guard(self):
        p,r,st=self.imported();self.s.save(p,'person',{'name':'Later person'})
        with self.assertRaisesRegex(ValueError,'Later edits'):self.s.undo_import(r['import_id'])
        p2,r2,_=self.imported();self.s.undo_import(r2['import_id']);self.assertFalse(self.s.records(p2,'person')['items'])
        st=self.s.stage_import('x.ged',FIXTURE.replace(b'1842',b'1843'),project=p);self.s.save(p,'task',{'title':'New work'})
        with self.assertRaisesRegex(ValueError,'Project changed'):self.s.commit_import(st,'x',True)
    def test_cancel_transaction_atomic(self):
        st=self.s.stage_import('x.ged',FIXTURE)
        with self.assertRaisesRegex(ValueError,'Cancelled'):self.s.commit_import(st,'Never appears',cancel=lambda:True)
        self.assertEqual(self.s.projects(),[]);self.assertEqual(self.s.db.execute('SELECT count(*) FROM attachments').fetchone()[0],0)
    def test_media_exact_path_and_zip(self):
        st=self.s.stage_import('tree.zip',archive({'tree.ged':FIXTURE,'media/notebook.txt':b'Fictional document'}));self.assertEqual(st['report']['matched_files'],1)
        result=self.s.commit_import(st,'media');media=self.s.records(result['project'],'media')['items'][0];self.assertEqual(media['data']['status'],'matched');self.assertTrue(media['data']['attachment_ids'])
        st=self.s.stage_import('x.ged',FIXTURE,{'other/notebook.txt':b'wrong'});self.assertEqual(st['report']['matched_files'],0)
        gdz=archive({'gedcom.ged':FIXTURE.replace(b'5.5.1',b'7.0'),'media/notebook.txt':b'data'});self.assertEqual(self.s.stage_import('tree.gdz',gdz)['report']['container'],'GEDZIP')
        with self.assertRaisesRegex(ValueError,'root'):self.s.stage_import('bad.gdz',archive({'tree.ged':FIXTURE}))
    def test_archive_traversal_symlink_limits_and_content(self):
        for path in ('../x','/tmp/x','a/../../x','C:\\test.txt'):
            with self.assertRaises(ValueError):unpack(archive({path:b'bad'}))
        with self.assertRaisesRegex(ValueError,'compression ratio'):unpack(archive({'big.txt':b'a'*2_000_000}))
        with patch('bluegene.gedcom.MAX_EXPANDED',10):
            with self.assertRaisesRegex(ValueError,'expansion'):unpack(archive({'a.txt':b'abc'*10}))
        with self.assertRaises(ValueError):attachment_type(b'<script>','bad.jpg')
        with self.assertRaises(ValueError):attachment_type(b'<svg>','bad.svg')
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            i=zipfile.ZipInfo('link');i.external_attr=(0o120777<<16);z.writestr(i,'/etc/passwd')
        with self.assertRaisesRegex(ValueError,'symlink'):unpack(b.getvalue())
    def test_backup_roundtrip_and_link_integrity(self):
        p,_,_=self.imported(media={'media/notebook.txt':b'fictional media'});self.s.seed(ENTRIES);self.s.setting('preferences',{'ai_enabled':False})
        person=self.s.records(p,'person')['items'][0];q=self.s.save(p,'question',{'title':'Where did they live?'},person['id']);self.s.save(p,'log',{'query':'A query','question_id':q['id'],'outcome':'no result'},person['id'])
        raw=self.s.backup();obj=self.s.inspect_backup(raw);dest=Path(self.tmp.name)/'restored.sqlite3';self.s.restore(obj,dest);r=Store(dest)
        self.assertEqual(self.s.all_records(p),r.all_records(p));self.assertEqual(self.s.export()['tables']['attachments'],r.export()['tables']['attachments']);r.db.close()
        jsondata=json.dumps(self.s.export()).encode();self.s.inspect_backup(jsondata)
        x=self.s.export();x['tables']['attachments'][0]['content']['sha256']='bad'
        with self.assertRaisesRegex(ValueError,'checksum'):self.s.inspect_backup(json.dumps(x).encode())
        x=self.s.export();e=next(r for r in x['tables']['entities'] if r['kind']=='citation');d=json.loads(e['data']);d['source_id']='nonexistent';e['data']=json.dumps(d)
        with self.assertRaisesRegex(ValueError,'reference'):self.s.inspect_backup(json.dumps(x).encode())
    def test_evidence_many_to_many_and_cross_project_validation(self):
        p=self.s.project('p');person=self.s.save(p,'person',{'name':'A'});source=self.s.save(p,'source',{'title':'A source'});c=self.s.save(p,'citation',{'source_id':source['id'],'locator':'p 2'});a=self.s.save(p,'assertion',{'type':'BIRT','date':'ABT 1840','citation_ids':[c['id']]},person['id']);b=self.s.save(p,'assertion',{'type':'BIRT','date':'1842','contradicting_ids':[c['id']]},person['id']);self.assertNotEqual(a['id'],b['id'])
        q=self.s.project('q')
        with self.assertRaisesRegex(ValueError,'reference'):self.s.save(q,'citation',{'source_id':source['id']})
    def test_seed_updates_keep_overrides_archive_conflicts(self):
        e={'id':'a','name':'A','kind':'collection','url':'https://example.com','description':'old','archived':False};self.s.seed([e],1)
        self.s.save_directory({**e,'description':'user edit','archived':True},'a');self.s.seed([{**e,'description':'new seed','name':'New name'}],2);r=self.s.directory()[0];self.assertTrue(r['archived']);self.assertEqual(r['description'],'user edit');self.assertEqual(r['name'],'New name');self.assertTrue(r['seed_conflicts']);self.s.seed([e],1);self.assertEqual(r,self.s.directory()[0])
    def test_directory_breadth_and_filter(self):
        cols=[e for e in ENTRIES if e['kind']=='collection'];repos=[e for e in ENTRIES if e['kind']=='repository'];self.assertGreaterEqual(len(cols),20);self.assertGreaterEqual(len({e['provider'] for e in cols}),5);self.assertGreaterEqual(len(repos),8)
        result=filter_resources(ENTRIES,{'place':'Vermont, United States','start':1850,'end':1900,'type':'birth','free':True});self.assertTrue(any(e['id']=='fs-1784223' for e in result))
        self.assertEqual(overlap([1850,1900],[[1880,1920]]),'partial');self.assertEqual(overlap([1850,1900],[]),'unknown')
    def test_recommendation_hypotheses_history_and_stability(self):
        p={'id':'p','data':{'name':'A Person','aliases':['A. Person']}};a=[{'id':'a','data':{'date':date_value('1850'),'place':'Massachusetts, United States'}}];q={'id':'q','title':'Who are the parents?'}
        e=next(x for x in ENTRIES if x['id']=='ma-vitals');r=recommend(p,a,q,[e],[]);self.assertEqual(r,recommend(p,a,q,[e],[]));self.assertEqual(r['items'][0]['band'],'known')
        query=r['items'][0]['query'];logs=[{'person':'p','data':{'question_id':'q','collection_id':e['id'],'query':query,'coverage':'1850','outcome':'no result'}}];second=recommend(p,a,q,[e],logs);self.assertLess(second['items'][0]['score'],r['items'][0]['score']);self.assertTrue(second['items'][0]['alternatives'])
        changed=recommend(p,a,q,[e],[{'person':'p','data':{**logs[0]['data'],'query':'different'}}]);self.assertEqual(changed['items'][0]['score'],r['items'][0]['score'])
        conflict=recommend(p,a+[{'id':'b','data':{'date':date_value('2000'),'place':'Massachusetts, United States'}}],q,[e],[]);self.assertTrue(any('Multiple' in t for t in conflict['items'][0]['uncertainty']))
    def test_offline_persistence(self):
        with patch('socket.socket',side_effect=AssertionError('Network forbidden')):
            p,_,_=self.imported();self.s.seed(ENTRIES);raw=self.s.backup();self.s.inspect_backup(raw);self.s.db.close();self.s=Store(Path(self.tmp.name)/'research.sqlite3');self.assertEqual(self.s.records(p,'person')['total'],6)

class AITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db');self.p=self.s.project('AI fixtures');self.calls=[]
        self.output={'summary':'Research aid','extracted':[],'inferences':['Try a variant'], 'uncertainties':['Unverified'],'transcript':'','translation':''}
        def transport(provider,key,path,payload=None):
            self.calls.append((provider,path,payload))
            if path.startswith('/models'):return {'data':[{'id':'test-model','capabilities':{'image_input':{'supported':False}}}]} if path=='/models' else {'id':'test-model'}
            raw=json.dumps(self.output);return {'content':[{'type':'text','text':raw}],'output':[{'content':[{'type':'output_text','text':raw}]}],'usage':{'output_tokens':10}}
        self.ai=AI(self.s,Path(self.tmp.name)/'credentials.json',transport)
        for provider in ('openai','anthropic'):self.ai.configure(provider,'fake-private-key')
        self.s.setting('preferences',{'ai_enabled':True,'provider':'openai','model':'test-model','allow_sensitive':False})
    def tearDown(self):self.s.db.close();self.tmp.cleanup()
    def test_both_providers_all_workflows_and_no_mutation(self):
        for provider in ['openai','anthropic']:
            for task in ['planning','query','transcription','comparison','summary']:
                preview=self.ai.prepare(self.p,task,[],[],provider,'test-model');out=self.ai.run(preview['token'],True);self.assertEqual(out['data']['provider'],provider);self.assertEqual(out['kind'],'ai_artifact')
        self.assertEqual(self.s.records(self.p,'assertion')['total'],0);self.assertEqual(self.s.records(self.p,'ai_artifact')['total'],10)
        self.assertEqual({c[1] for c in self.calls},{'/models/test-model','/responses','/messages'})
    def test_cache_preferences_and_no_call_on_settings(self):
        self.ai.status();self.assertFalse(self.calls);cache=self.ai.models('openai');self.assertTrue(cache['refreshed']);self.assertEqual(self.ai.status()['providers']['openai']['cache'],cache)
        self.assertEqual(self.s.setting('preferences')['model'],'test-model')
    def test_citation_validation_and_schema(self):
        source=self.s.save(self.p,'source',{'title':'Fixture'});c=self.s.save(self.p,'citation',{'source_id':source['id'],'locator':'p 2','excerpt':'sample'})
        self.output['extracted']=[{'text':'claim','citation_id':'hallucination','locator':'p 2'}];p=self.ai.prepare(self.p,'comparison',[c['id']],[])
        with self.assertRaisesRegex(ValueError,'nonexistent'):self.ai.run(p['token'],True)
        self.assertEqual(self.s.records(self.p,'ai_artifact')['total'],0)
        self.output['extracted'][0]['citation_id']=c['id'];p=self.ai.prepare(self.p,'comparison',[c['id']],[]);r=self.ai.run(p['token'],True);self.assertEqual(r['data']['output']['extracted'][0]['locator'],'p 2')
    def test_consent_disabled_sensitive_and_duplicate_guard(self):
        person=self.s.save(self.p,'person',{'name':'Possibly living'})
        with self.assertRaisesRegex(ValueError,'Living'):self.ai.prepare(self.p,'planning',[person['id']],[])
        p=self.ai.prepare(self.p,'planning',[],[])
        with self.assertRaisesRegex(ValueError,'consent'):self.ai.run(p['token'])
        self.ai.run(p['token'],True)
        with self.assertRaisesRegex(ValueError,'already'):self.ai.run(p['token'],True)
        self.s.setting('preferences',{'ai_enabled':False})
        with self.assertRaisesRegex(ValueError,'disabled'):self.ai.prepare(self.p,'query',[],[])
    def test_failure_cancel_no_fallback(self):
        def failing(*args):raise ValueError('Rate or quota limit')
        self.ai.transport=failing;p=self.ai.prepare(self.p,'query',[],[])
        with self.assertRaisesRegex(ValueError,'Rate'):self.ai.run(p['token'],True)
        p=self.ai.prepare(self.p,'query',[],[])
        with self.assertRaisesRegex(ValueError,'Cancelled'):self.ai.run(p['token'],True,cancel=lambda:True)
        self.assertFalse(self.calls)
    def test_task_override_and_capabilities(self):
        self.s.setting('preferences',{'ai_enabled':True,'provider':'openai','model':'test-model','allow_sensitive':True,'overrides':{'query':{'provider':'anthropic','model':'override'}}})
        p=self.ai.prepare(self.p,'query',[],[]);self.assertEqual(p['provider'],'anthropic');self.assertEqual(p['model'],'override')
        self.ai.models('anthropic');a=self.s.attach(self.p,'test.png',b'\x89PNG\r\n\x1a\nfixture')
        with self.assertRaisesRegex(ValueError,'image_input'):self.ai.prepare(self.p,'transcription',[],[a['id']],'anthropic','test-model')
    def test_effort_controls_and_permission_revocation(self):
        self.s.setting('models:anthropic',{'models':[{'id':'test-model','capabilities':{'effort':{'supported':True,'low':{'supported':True}}}}]})
        def transport(p,key,path,payload=None):
            if payload is None:return {'id':'test-model','capabilities':{'effort':{'supported':True,'low':{'supported':True}}}}
            self.assertEqual(payload['output_config']['effort'],'low')
            return {'content':[{'type':'text','text':json.dumps(self.output)}]}
        self.ai.transport=transport
        preview=self.ai.prepare(self.p,'planning',[],[],'anthropic','test-model',effort='low')
        self.assertEqual(self.ai.run(preview['token'],True)['data']['effort'],'low')
        with self.assertRaisesRegex(ValueError,'Effort is not verified'):self.ai.prepare(self.p,'planning',[],[],'openai','test-model',effort='low')
        self.s.setting('preferences',{'ai_enabled':True,'allow_sensitive':True,'provider':'openai','model':'test-model'})
        r=self.s.save(self.p,'person',{'name':'Living fixture','living':'yes'})
        preview=self.ai.prepare(self.p,'planning',[r['id']],[])
        self.s.setting('preferences',{'ai_enabled':True,'allow_sensitive':False})
        with self.assertRaisesRegex(ValueError,'revoked'):self.ai.run(preview['token'],True)
    def test_transport_errors_are_actionable_and_private(self):
        import urllib.error
        from bluegene.ai import request
        for status,expected in [(401,'Credential'),(403,'access'),(404,'unavailable'),(429,'quota'),(413,'large'),(503,'unavailable')]:
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect=urllib.error.HTTPError('https://example.invalid',status,'secret provider body',{},None)
                with self.assertRaisesRegex(ValueError,expected) as caught:request('openai','private-key','/models')
                self.assertNotIn('secret',str(caught.exception));self.assertNotIn('private-key',str(caught.exception))
    def test_secrets_excluded(self):
        raw=json.dumps(self.s.export());self.assertNotIn('fake-private-key',raw);self.assertNotIn('credentials',raw);self.assertEqual(os.stat(self.ai.secrets).st_mode&0o777,0o600)
        for value in unpack(self.s.backup()).values():self.assertNotIn(b'fake-private-key',value)
if __name__=='__main__':unittest.main()
