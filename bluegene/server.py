from __future__ import annotations
import argparse, base64, csv, io, json, mimetypes, os, secrets, threading, time, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .store import Store, uid, now, dumps
from .ai import AI
from .seeds import ENTRIES, VERSION, TAXONOMY
from .recommend import recommend,filter_resources
from .gedcom import unpack
from .search import Search, ENGINES
ROOT=Path(__file__).resolve().parent.parent

def database_read(fn):
    def wrapper(self,*args,**kwargs):
        with self.store.lock:return fn(self,*args,**kwargs)
    return wrapper

class App:
    def __init__(self,data):
        self.data=Path(data).resolve();self.data.mkdir(parents=True,exist_ok=True)
        os.chmod(self.data,0o700)
        self.store=Store(self.data/'research.sqlite3');self.store.seed(ENTRIES,VERSION)
        self.ai=AI(self.store,self.data/'credentials.json');self.search=Search(self.store,self.ai);self.csrf=secrets.token_urlsafe(32);self.jobs={};self.stages={};self.restores={}
        if not self.store.projects():self.demo()
    def demo(self):
        stage=self.store.stage_import('fictional-demo.ged',(ROOT/'fixtures'/'fictional-demo.ged').read_bytes())
        p=self.store.commit_import(stage,'The Whitcomb notebook · fictional demo')['project']
        with self.store.db:self.store.db.execute('UPDATE projects SET demo=1 WHERE id=?',(p,))
        people=self.store.records(p,'person')['items'];person=next(r for r in people if r['data']['name']=='Eleanor Whitcomb')
        self.store.save(p,'question',{'title':'Who were Eleanor’s parents?','hypothesis':'A Whitcomb household in northern Worcester County may be related. This is a fictional exercise.','status':'open','planned_searches':'Compare birth, probate and census records.','record_types':['birth','probate','census'],'review':'tentative'},person['id'])
        self.store.save(p,'task',{'title':'Compare the two birth-date assertions','status':'open','notes':'Keep both dates until their sources can be assessed.'},person['id'])
    def job(self,fn):
        # At most 2 active jobs and 30 retained results; previews expire on restart.
        if sum(j['status']=='running' for j in self.jobs.values())>=2:raise ValueError('Two operations already running. Wait or cancel one.')
        for key in list(self.jobs):
            if len(self.jobs)<30:break
            if self.jobs[key]['status']!='running':self.jobs.pop(key)
        id=uid();j={'id':id,'status':'running','progress':'Starting','cancelled':False};self.jobs[id]=j
        def work():
            try:
                result=fn(lambda msg:j.update(progress=msg),lambda:j['cancelled'])
                j.update(status='complete',result=result,progress='Complete')
            except Exception as exc:
                # Never log request bodies, provider error bodies, credentials or research data.
                message=str(exc) if isinstance(exc,ValueError) else 'Operation failed. No successful completion was recorded.'
                j.update(status='cancelled' if j['cancelled'] else 'error',error=message)
        threading.Thread(target=work,daemon=True).start();return {'job':id}
    def stage(self,b,progress,cancel):
        files={}
        for f in b.get('media',[]):
            raw=base64.b64decode(f['data'],validate=True)
            if f['name'].lower().endswith('.zip'):
                for name,data in unpack(raw).items():
                    if name in files:raise ValueError('Duplicate media path.')
                    files[name]=data
            else:
                if f['name'] in files:raise ValueError('Duplicate media path.')
                files[f['name']]=raw
        stage=self.store.stage_import(b['filename'],base64.b64decode(b['data'],validate=True),files,b.get('project') or None,progress,cancel)
        if cancel():raise ValueError('Cancelled before preview.')
        if len(self.stages)>=4:raise ValueError('Discard an existing preview before staging another import.')
        id=uid();self.stages[id]=stage
        return {'stage':id,**{k:stage[k] for k in ['report','comparison','person_mappings','identity_notice','identical'] if k in stage}}
    @database_read
    def handle_get(self,path,q):
        s=self.store
        if path=='/api/bootstrap':return {'csrf':self.csrf,'projects':s.projects(),'directory':s.directory(),'preferences':self.ai.status()['preferences'],'storage':str(self.data),'version':'0.2.0','taxonomy':TAXONOMY}
        if path=='/api/search/draft':return self.search.draft(q['project'],q.get('person'),q.get('question'))
        if path=='/api/search/engines':return {'engines':ENGINES,'subscription_status':'No provider-approved API access configured'}
        if path=='/api/projects':return s.projects()
        if path=='/api/records':return s.records(q.get('project'),q.get('kind'),q.get('person'),q.get('q',''),q.get('offset',0),q.get('limit',100))
        if path=='/api/record':return s.get(q['id'])
        if path=='/api/history':return [dict(r) for r in s.db.execute('SELECT * FROM history WHERE entity=? ORDER BY id DESC',(q['id'],))]
        if path=='/api/counts':return {r[0]:r[1] for r in s.db.execute('SELECT kind,count(*) FROM entities WHERE project=? GROUP BY kind',(q.get('project'),))}
        if path=='/api/directory':return filter_resources(s.directory(),q)
        if path=='/api/recommend':
            p=s.get(q['person']);project=p['project'];question=s.get(q['question']) if q.get('question') else None
            if question and question['project']!=project:raise ValueError('Question belongs to another project.')
            return recommend(p,s.records(project,'assertion',p['id'],limit=1000)['items'],dict(question['data'],id=question['id']) if question else {},s.directory(),s.records(project,'log',p['id'],limit=1000)['items'],{**(s.setting('preferences') or {}).get('access',{}),**{k:v for k,v in q.items() if k in ('free','remote','type','language')}},s.records(project,'place',limit=1000)['items'])
        if path=='/api/imports':return [dict(r,report=json.loads(r['report'])) for r in s.db.execute('SELECT id,filename,created,revision,report FROM imports WHERE project=? ORDER BY created DESC',(q['project'],))]
        if path=='/api/provenance':
            r=s.get(q['id']);origin=r['data'].get('origin',{});imports=s.db.execute('SELECT id,raw,filename FROM imports WHERE project=? ORDER BY created DESC',(r['project'],))
            matches=[]
            for imp in imports:
                raw=json.loads(imp['raw']);nodes=[n for n in raw if n.get('xref')==origin.get('record')]
                if nodes:matches.append({'import_id':imp['id'],'filename':imp['filename'],'nodes':nodes})
            return {'normalized':r,'original_records':matches}
        if path=='/api/job':
            j=self.jobs.get(q['id'])
            if not j:raise ValueError('Operation not found or expired.')
            return j
        if path=='/api/ai/status':return self.ai.status()
        if path=='/api/attachments':return [dict(r) for r in s.db.execute('SELECT id,name,mime,hash FROM attachments WHERE project=?',(q['project'],))]
        raise ValueError('Unknown endpoint.')
    def handle_post(self,path,b):
        s=self.store
        if path=='/api/search/preview':return self.search.prepare(b)
        if path=='/api/search/run':return self.job(lambda progress,cancel:self.search.run(b['token'],b.get('consent',False),b.get('sensitive_ack',False),progress,cancel))
        if path=='/api/search/accept':return self.search.accept(b['run'],b['hit'],b.get('locator',''),b.get('note',''))
        if path=='/api/search/ocr':return self.job(lambda progress,cancel:self.search.ocr(b['run'],b['hit'],cancel))
        if path=='/api/project':return {'id':s.project(b['name'])}
        if path=='/api/save':
            if b['kind']=='search_run':raise ValueError('Search provenance is immutable through the generic editor; use reviewed result actions.')
            if b['kind']=='ai_artifact':
                old=s.get(b['id']);allowed={'review','rationale','corrected_transcript','acceptance_history'}
                if any(old['data'].get(k)!=b['data'].get(k) for k in (set(old['data'])|set(b['data']))-allowed):raise ValueError('Raw AI artifact and provenance are immutable.')
            return s.save(b['project'],b['kind'],b['data'],b.get('person'),b.get('id'))
        if path=='/api/attach':return s.attach(b['project'],b['name'],base64.b64decode(b['data'],validate=True))
        if path=='/api/directory':return {'id':s.save_directory(b['data'],b.get('id'))}
        if path=='/api/import/preview':return self.job(lambda progress,cancel:self.stage(b,progress,cancel))
        if path=='/api/import/commit':
            stage=self.stages.get(b['stage'])
            if not stage:raise ValueError('Preview expired. Upload again.')
            def commit(progress,cancel):
                result=s.commit_import(stage,b.get('name','Imported family'),b.get('identity_confirmed',False),progress,cancel)
                self.stages.pop(b['stage'],None);return result
            return self.job(commit)
        if path=='/api/import/discard':self.stages.pop(b['stage'],None);return {'discarded':True}
        if path=='/api/import/undo':return s.undo_import(b['id'])
        if path=='/api/job/cancel':
            j=self.jobs.get(b['id'])
            if j and j['status']=='running':j['cancelled']=True
            return {'requested':True,'note':'A committed operation cannot be cancelled. Remote charges may already have occurred.'}
        if path=='/api/backup/preview':
            def preview(progress,cancel):
                progress('Validating manifest, checksums and references');obj=s.inspect_backup(base64.b64decode(b['data'],validate=True))
                if cancel():raise ValueError('Cancelled')
                id=uid();self.restores[id]=obj
                return {'preview':id,'counts':{k:len(v) for k,v in obj['tables'].items()},'projects':[r['name'] for r in obj['tables']['projects']],'note':'Restore creates a separate database. Current work and credentials are not replaced.'}
            return self.job(preview)
        if path=='/api/backup/restore':
            obj=self.restores.get(b['preview'])
            if not obj:raise ValueError('Restore preview expired.')
            def restore(progress,cancel):
                if cancel():raise ValueError('Cancelled')
                progress('Restoring validated data to a separate destination')
                dest=self.data.parent/('bluegene-restored-'+uid()[:8]);dest.mkdir(mode=0o700)
                location=s.restore(obj,dest/'research.sqlite3');self.restores.pop(b['preview'],None)
                return {'path':location,'launch':'python3 -m bluegene --data "'+str(dest)+'" --port 8766'}
            return self.job(restore)
        if path=='/api/preferences':
            prefs=b['preferences']
            if set(prefs)-{'ai_enabled','provider','model','overrides','allow_sensitive','access'}:raise ValueError('Unknown preference fields; credentials must use the credential endpoint.')
            s.setting('preferences',prefs);return prefs
        if path=='/api/ai/configure':return self.ai.configure(b['provider'],b.get('key',''))
        if path=='/api/ai/models':return self.job(lambda progress,cancel:self.ai.models(b['provider']))
        if path=='/api/ai/test':return self.job(lambda progress,cancel:self.ai.test(b['provider'],b['model'],b.get('inference',False)))
        if path=='/api/ai/preview':return self.ai.prepare(b['project'],b['task'],b.get('record_ids',[]),b.get('attachment_ids',[]),b.get('provider'),b.get('model'),b.get('context'),b.get('limit',1500),b.get('effort'))
        if path=='/api/ai/run':return self.job(lambda progress,cancel:self.ai.run(b['token'],b.get('consent',False),cancel))
        raise ValueError('Unknown endpoint.')

class Handler(BaseHTTPRequestHandler):
    server_version='blueGene'
    def log_message(self,*args):pass
    def reply(self,data,status=200,mime='application/json',filename=None):
        if not isinstance(data,bytes):data=dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def valid_host(self):return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
    def do_GET(self):
        if not self.valid_host():return self.reply({'error':'Invalid Host'},403)
        if self.headers.get('Sec-Fetch-Site')=='cross-site':return self.reply({'error':'Cross-site access refused'},403)
        url=urlsplit(self.path);path=url.path;q={k:v[0] for k,v in parse_qs(url.query).items()}
        try:
            if path=='/api/backup':return self.reply(self.server.app.store.backup(),mime='application/zip',filename='bluegene-backup.zip')
            if path=='/api/export':return self.reply(self.server.app.store.export(),filename='bluegene-export.json')
            if path=='/api/csv':
                s=self.server.app.store;rows=s.directory() if q.get('kind')=='directory' else [dict(id=r['id'],**r['data']) for r in s.all_records(q['project']) if r['kind']=='log']
                buffer=io.StringIO();fields=sorted(set(k for r in rows for k in r));writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader()
                for row in rows:
                    safe={}
                    for k,v in row.items():
                        v=dumps(v) if isinstance(v,(dict,list)) else str(v or '')
                        safe[k]="'"+v if v.startswith(('=','+','-','@','\t','\r')) else v
                    writer.writerow(safe)
                return self.reply(buffer.getvalue().encode(),mime='text/csv; charset=utf-8',filename='bluegene-'+q.get('kind','log')+'.csv')
            if path=='/api/attachment':
                r=self.server.app.store.db.execute('SELECT * FROM attachments WHERE id=?',(q['id'],)).fetchone()
                if not r:raise ValueError('Attachment not found.')
                return self.reply(r['content'],mime='application/octet-stream',filename='attachment-'+r['id']+Path(r['name']).suffix)
            if path=='/api/original':
                r=self.server.app.store.db.execute('SELECT original FROM imports WHERE id=?',(q['id'],)).fetchone()
                if not r:raise ValueError('Import not found.')
                return self.reply(r['original'],mime='application/octet-stream',filename='original-import.bin')
            if path.startswith('/api/'):return self.reply(self.server.app.handle_get(path,q))
            files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/search.js':'search.js'}
            if path not in files:return self.reply({'error':'Not found'},404)
            file=ROOT/'static'/files[path];return self.reply(file.read_bytes(),mime=mimetypes.guess_type(file)[0] or 'text/plain')
        except (ValueError,KeyError,TypeError) as exc:return self.reply({'error':str(exc)},400)
        except Exception:return self.reply({'error':'Local operation failed. Research data remains local.'},500)
    def do_POST(self):
        app=self.server.app
        origin=self.headers.get('Origin');allowed={f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
        if not self.valid_host() or (origin and origin not in allowed) or self.headers.get('X-CSRF-Token')!=app.csrf:return self.reply({'error':'Unauthorized origin or missing session token.'},403)
        if self.headers.get_content_type()!='application/json':return self.reply({'error':'JSON required'},415)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=360*1024*1024:raise ValueError('Request size limit exceeded.')
            body=json.loads(self.rfile.read(length));self.reply(app.handle_post(urlsplit(self.path).path,body))
        except (ValueError,KeyError,TypeError) as exc:self.reply({'error':str(exc)},400)
        except Exception:self.reply({'error':'Local operation failed. No successful completion was recorded.'},500)

def serve():
    parser=argparse.ArgumentParser(description='blueGene — private genealogy research')
    parser.add_argument('--port',type=int,default=8877);parser.add_argument('--data',default=str(ROOT/'data'))
    args=parser.parse_args();app=App(args.data);server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.app=app
    print(f'blueGene: http://127.0.0.1:{args.port}\nLocal storage: {app.data}\nPress Ctrl-C to stop.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.store.db.close()
