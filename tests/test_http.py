"""Exercise the real request handlers with in-memory HTTP streams (no network)."""
import io,json,tempfile,unittest
from email.message import Message
from types import SimpleNamespace
from bluegene.server import App,Handler

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=App(self.temp.name)
    def tearDown(self):self.app.store.db.close();self.temp.cleanup()
    def send(self,path,body=None,headers=None):
        h=Handler.__new__(Handler);h.server=SimpleNamespace(app=self.app,server_port=8877)
        h.path=path;h.command='GET' if body is None else 'POST';h.request_version='HTTP/1.1';h.requestline=h.command+' '+path+' HTTP/1.1';h.close_connection=True
        raw=json.dumps(body).encode() if body is not None else b''
        h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO();h.headers=Message()
        for k,v in {'Host':'127.0.0.1:8877','Content-Type':'application/json','Content-Length':str(len(raw)),**(headers or {})}.items():h.headers[k]=v
        getattr(h,'do_'+h.command)();head,data=h.wfile.getvalue().split(b'\r\n\r\n',1)
        return int(head.split(b' ')[1]),head.decode(),data
    def test_host_origin_csrf(self):
        self.assertEqual(self.send('/api/bootstrap',headers={'Host':'evil.invalid:8877'})[0],403)
        self.assertEqual(self.send('/api/bootstrap',headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.send('/api/project',{'name':'blocked'})[0],403)
        self.assertEqual(self.send('/api/project',{'name':'blocked'},{'X-CSRF-Token':self.app.csrf,'Origin':'https://evil.invalid'})[0],403)
        code,_,data=self.send('/api/project',{'name':'Created by handler test'},{'X-CSRF-Token':self.app.csrf,'Origin':'http://127.0.0.1:8877'})
        self.assertEqual(code,200);self.assertTrue(json.loads(data)['id'])
    def test_static_security_and_downloads(self):
        code,headers,_=self.send('/');self.assertEqual(code,200);self.assertIn("object-src 'none'",headers);self.assertIn('nosniff',headers)
        self.assertEqual(self.send('/../bluegene/ai.py')[0],404)
        _,headers,_=self.send('/api/backup');self.assertIn('attachment;',headers)
    def test_artifact_provenance_immutable(self):
        p=self.app.store.project('Fixture');r=self.app.store.save(p,'ai_artifact',{'raw_output':'original','input_context':[],'review':'unreviewed'})
        code,_,_=self.send('/api/save',{'id':r['id'],'project':p,'kind':'ai_artifact','data':{'review':'tentative'}},{'X-CSRF-Token':self.app.csrf})
        self.assertEqual(code,400);self.assertEqual(self.app.store.get(r['id'])['data']['raw_output'],'original')

    def test_search_preview_and_immutable_history(self):
        p=self.app.store.project('Search handler test');headers={'X-CSRF-Token':self.app.csrf}
        code,_,body=self.send('/api/search/preview',{'project':p,'queries':['"Public historical name"'],'engine':'archive'},headers)
        self.assertEqual(code,200);self.assertEqual(json.loads(body)['outbound'],{'queries':['"Public historical name"']})
        self.assertEqual(self.send('/search.js')[0],200)
        self.assertEqual(self.send('/api/save',{'project':p,'kind':'search_run','data':{'title':'fake'}},headers)[0],400)
