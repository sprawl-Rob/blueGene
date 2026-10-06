from __future__ import annotations
import sqlite3, json, uuid, datetime, io, zipfile, base64, threading, functools
from pathlib import Path
from .gedcom import digest, parse, normalize, unpack, safe_path, attachment_type, date_value

KINDS = {'search_run','person','assertion','relationship','source','citation','question','log','task','bookmark','place','repository','media','ai_artifact','lead','conclusion'}
STATES = {'unreviewed','tentative','accepted by user','disputed','rejected'}
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def uid(): return uuid.uuid4().hex
def dumps(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def validate(kind, data):
    if kind not in KINDS or not isinstance(data,dict): raise ValueError('Invalid record kind or fields.')
    if len(dumps(data)) > 2_000_000: raise ValueError('Record exceeds 2 MB.')
    if data.get('review','unreviewed') not in STATES: raise ValueError('Invalid review state.')
    required={'person':'name','source':'title','question':'title','log':'query','assertion':'type','task':'title'}
    field=required.get(kind)
    if field and not str(data.get(field,'')).strip(): raise ValueError(field+' is required.')
    if kind=='person' and data.get('living','unknown') not in ('yes','no','unknown'): raise ValueError('Invalid living status.')
    if kind=='assertion' and isinstance(data.get('date'),str): data['date']=date_value(data['date'])
    if kind=='log' and data.get('outcome') not in ('useful finding','possible match','no result','inaccessible','follow-up needed'): raise ValueError('Choose a search outcome.')
    if kind=='relationship' and data.get('type') not in ('biological','adoptive','foster','step','unspecified','partner','associate','witness','neighbor','household'): raise ValueError('Invalid relationship type.')
    return data

def locked(fn):
    @functools.wraps(fn)
    def wrapper(self,*args,**kwargs):
        with self.lock:return fn(self,*args,**kwargs)
    return wrapper

class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False); self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON'); self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied TEXT);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,demo INTEGER DEFAULT 0,revision INTEGER DEFAULT 0,created TEXT);
        CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,project TEXT REFERENCES projects(id) ON DELETE CASCADE,kind TEXT NOT NULL,person TEXT,data TEXT NOT NULL,modified TEXT);
        CREATE INDEX IF NOT EXISTS entity_kind ON entities(project,kind);
        CREATE INDEX IF NOT EXISTS entity_person ON entities(project,person);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,entity TEXT,project TEXT REFERENCES projects(id) ON DELETE CASCADE,before_data TEXT,after_data TEXT,changed TEXT);
        CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,project TEXT REFERENCES projects(id) ON DELETE CASCADE,hash TEXT,report TEXT,snapshot TEXT,raw TEXT,original BLOB,filename TEXT,revision INTEGER,undo TEXT,created TEXT, UNIQUE(project,hash));
        CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY,project TEXT REFERENCES projects(id) ON DELETE CASCADE,name TEXT,mime TEXT,hash TEXT,content BLOB);
        CREATE TABLE IF NOT EXISTS directory(id TEXT PRIMARY KEY,data TEXT,seed TEXT,version INTEGER);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        INSERT OR IGNORE INTO migrations VALUES(1,datetime('now'));
        '''); self.db.commit()
    def project(self,name,demo=False):
        if not name.strip(): raise ValueError('Project name is required.')
        id=uid()
        with self.lock,self.db: self.db.execute('INSERT INTO projects VALUES(?,?,?,0,?)',(id,name,bool(demo),now()))
        return id
    @locked
    def projects(self): return [dict(r) for r in self.db.execute('SELECT * FROM projects ORDER BY demo,name')]
    @locked
    def revision(self,project):
        row=self.db.execute('SELECT revision FROM projects WHERE id=?',(project,)).fetchone()
        if not row: raise ValueError('Project not found.')
        return row[0]
    def bump(self,p): self.db.execute('UPDATE projects SET revision=revision+1 WHERE id=?',(p,))
    @locked
    def get(self,id):
        r=self.db.execute('SELECT * FROM entities WHERE id=?',(id,)).fetchone()
        if not r: raise ValueError('Record not found.')
        return dict(r, data=json.loads(r['data']))
    @locked
    def records(self,p,kind=None,person=None,q='',offset=0,limit=100):
        sql='SELECT * FROM entities WHERE project=?'; args=[p]
        if kind: sql+=' AND kind=?';args.append(kind)
        if person: sql+=' AND person=?';args.append(person)
        if q: sql+=' AND lower(data) LIKE ?';args.append('%'+q.lower()+'%')
        count=self.db.execute(sql.replace('SELECT *','SELECT count(*)'),args).fetchone()[0]
        sql+=' ORDER BY kind,modified,id LIMIT ? OFFSET ?';args += [min(max(1,int(limit)),1000),max(0,int(offset))]
        return dict(total=count,items=[dict(r,data=json.loads(r['data'])) for r in self.db.execute(sql,args)])
    @locked
    def all_records(self,p): return [dict(r,data=json.loads(r['data'])) for r in self.db.execute('SELECT * FROM entities WHERE project=?',(p,))]
    def _refs(self,project,data,person=None):
        refs=[]
        if person: refs.append((person,'person'))
        for field,kind in [('search_run_id','search_run'),('source_id','source'),('from_id','person'),('to_id','person'),('question_id','question'),('assertion_id','assertion'),('person_id','person')]:
            if data.get(field): refs.append((data[field],kind))
        for id in data.get('citation_ids',[]): refs.append((id,'citation'))
        for id in data.get('contradicting_ids',[]): refs.append((id,'citation'))
        for id in data.get('people_ids',[])+data.get('participant_ids',[]): refs.append((id,'person'))
        for id in data.get('repository_ids',[]): refs.append((id,'repository'))
        if data.get('owner_id'):
            owner=self.db.execute('SELECT project FROM entities WHERE id=?',(data['owner_id'],)).fetchone()
            if not owner or owner['project']!=project:raise ValueError('Missing or cross-project owner reference.')
        for id,kind in refs:
            r=self.db.execute('SELECT project,kind FROM entities WHERE id=?',(id,)).fetchone()
            if not r or r['project']!=project or r['kind']!=kind: raise ValueError('Invalid cross-project or missing '+kind+' reference: '+str(id))
        for id in data.get('attachment_ids',[]):
            if not self.db.execute('SELECT 1 FROM attachments WHERE id=? AND project=?',(id,project)).fetchone(): raise ValueError('Attachment is not in this project.')
    def save(self,p,kind,data,person=None,id=None):
        with self.lock,self.db:return self._save(p,kind,data,person,id)
    def save_many(self,records):
        with self.lock,self.db:
            return [self._save(**record) for record in records]
    def _save(self,p,kind,data,person=None,id=None):
        self.revision(p); data=validate(kind,dict(data)); self._refs(p,data,person)
        id=id or uid(); old=self.db.execute('SELECT * FROM entities WHERE id=?',(id,)).fetchone()
        if old and (old['project']!=p or old['kind']!=kind): raise ValueError('Cannot change record project or kind.')
        self.db.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?)',(id,p,kind,person,dumps(data),now()))
        self.db.execute('INSERT INTO history(entity,project,before_data,after_data,changed) VALUES(?,?,?,?,?)',(id,p,old['data'] if old else None,dumps(data),now()));self.bump(p)
        return self.get(id)
    def attach(self,p,name,data):
        self.revision(p); name=safe_path(name);mime=attachment_type(data,name);id=uid()
        with self.lock,self.db:
            self.db.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?)',(id,p,name,mime,digest(data),data));self.bump(p)
        return dict(id=id,name=name,mime=mime,hash=digest(data))
    @locked
    def setting(self,key,value=None):
        if value is not None:
            with self.lock,self.db: self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,dumps(value)))
        r=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return json.loads(r[0]) if r else None
    def seed(self,entries,version=1):
        with self.lock,self.db:
            for entry in entries:
                id=entry['id']; incoming={k:v for k,v in entry.items() if k!='id'}
                row=self.db.execute('SELECT * FROM directory WHERE id=?',(id,)).fetchone()
                if not row: self.db.execute('INSERT INTO directory VALUES(?,?,?,?)',(id,dumps(incoming),dumps(incoming),version));continue
                if row['version']>=version: continue
                old=json.loads(row['seed']);current=json.loads(row['data']);conflicts=[]
                for k in set(old)|set(incoming):
                    if current.get(k)==old.get(k):
                        if k in incoming:current[k]=incoming[k]
                        else:current.pop(k,None)
                    elif incoming.get(k)!=old.get(k):conflicts.append(dict(field=k,local=current.get(k),incoming=incoming.get(k)))
                if conflicts: current['seed_conflicts']=conflicts
                self.db.execute('UPDATE directory SET data=?,seed=?,version=? WHERE id=?',(dumps(current),dumps(incoming),version,id))
    @locked
    def directory(self): return [dict(id=r['id'],**json.loads(r['data'])) for r in self.db.execute('SELECT * FROM directory ORDER BY id')]
    def save_directory(self,data,id=None):
        data=dict(data);id=id or uid();data.pop('id',None)
        if not data.get('name') or not data.get('url','').startswith(('https://','http://')): raise ValueError('Directory name and HTTP(S) URL required.')
        if data.get('kind') not in ('provider','collection','repository','guidance'):raise ValueError('Invalid directory type.')
        with self.lock,self.db:
            row=self.db.execute('SELECT 1 FROM directory WHERE id=?',(id,)).fetchone()
            if row:self.db.execute('UPDATE directory SET data=? WHERE id=?',(dumps(data),id))
            else:self.db.execute('INSERT INTO directory VALUES(?,?,?,0)',(id,dumps(data),'{}'))
        return id

    @locked
    def stage_import(self,filename,data,media_files=None,project=None,progress=lambda x:None,cancel=lambda:False):
        progress('Validating upload')
        if len(data)>64*1024*1024:raise ValueError('Import exceeds 64 MiB.')
        files={};container='GEDCOM'
        if data.startswith(b'PK'):
            files=unpack(data);geds=[n for n in files if n.lower().endswith('.ged')]
            if len(geds)!=1:raise ValueError('Archive must contain exactly one GEDCOM file.')
            gedname=geds[0];ged=files.pop(gedname);container='GEDZIP' if filename.lower().endswith('.gdz') else 'ordinary ZIP'
            if container=='GEDZIP' and gedname!='gedcom.ged':raise ValueError('GEDZIP requires gedcom.ged at the archive root.')
        else:ged=data;gedname=filename
        for name,content in (media_files or {}).items():
            name=safe_path(name)
            if name in files:raise ValueError('Duplicate supplied media path.')
            files[name]=content
        if sum(map(len,files.values()))>256*1024*1024:raise ValueError('Media total exceeds 256 MiB.')
        if cancel():raise ValueError('Cancelled')
        progress('Parsing hierarchy and preserving raw records');parsed=parse(ged)
        if container=='GEDZIP' and not parsed['version'].startswith('7'):raise ValueError('GEDZIP requires GEDCOM 7.')
        progress('Mapping people, assertions and citations');entities,report=normalize(parsed);report['container']=container
        report['uninterpreted_policy']='All raw fields retained; supported semantic fields listed in docs/import-compatibility.md.'
        matched={};used_files=set();report['missing_files']=[];report['ambiguous_files']=[];report['unsafe_media']=[]
        for e in entities:
            if cancel():raise ValueError('Cancelled')
            if e['kind']!='media':continue
            d=e['data'];path=d['path']
            if d['status']=='remote reference':continue
            try:path=safe_path(path)
            except ValueError:report['unsafe_media'].append(path);continue
            # Compare full relative paths only, including GEDCOM parent when packaged.
            parent=str(Path(gedname).parent)
            candidates=[n for n in files if n.casefold() in {path.casefold(),(parent+'/'+path).casefold()}]
            if len(candidates)>1:d['status']='ambiguous';report['ambiguous_files'].append(path)
            elif len(candidates)==1:
                content=files[candidates[0]]
                try:mime=attachment_type(content,path)
                except ValueError as exc:report['warnings'].append(str(exc)+' '+path);continue
                content_hash=digest(content)
                existing=self.db.execute('SELECT id FROM attachments WHERE project=? AND name=? AND hash=?',(project,path,content_hash)).fetchone() if project else None
                aid=existing['id'] if existing else next((k for k,v in matched.items() if v['hash']==content_hash and v['name']==path),None) or uid()
                if not existing:matched[aid]=dict(name=path,mime=mime,hash=content_hash,content=content)
                used_files.add(candidates[0])
                d['attachment']=aid;d['attachment_ids']=[aid];d['status']='matched'
            else:report['missing_files'].append(path)
        report['matched_files']=len(used_files)
        report['unused_files']=[n for n in files if n not in used_files]
        bundle_hash=digest(data) if not files else digest((digest(data)+dumps({name:digest(content) for name,content in sorted(files.items())})).encode())
        report['original_file_hash']=digest(data);report['bundle_hash']=bundle_hash
        stage=dict(filename=filename,original=data,ged_hash=parsed['hash'],hash=bundle_hash,raw=parsed['roots'],entities=entities,report=report,attachments=matched,project=project,revision=self.revision(project) if project else None)
        if project:
            same=self.db.execute('SELECT id FROM imports WHERE project=? AND hash=?',(project,stage['hash'])).fetchone()
            stage['identical']=bool(same)
            prior=self.db.execute('SELECT snapshot FROM imports WHERE project=? ORDER BY created DESC LIMIT 1',(project,)).fetchone()
            if not prior:raise ValueError('Select an imported lineage, or create a separate project.')
            stage['prior']=json.loads(prior[0]); old=stage['prior']; stage['comparison']=[]
            # A unique, syntactically valid GEDCOM UID can propose a renumbered
            # identity. It still requires the same explicit identity review as xrefs.
            def uuids(values):
                out=set()
                for value in values:
                    try:out.add(str(uuid.UUID(value)))
                    except (ValueError,AttributeError):pass
                return out
            prior_uids={}
            for key,prev in old.items():
                for value in uuids(prev['imported'].get('persistent_ids',[])):
                    prior_uids.setdefault(value,{})[prev['id']]=key
            incoming_uids={}
            for e in entities:
                if e['kind']=='person':
                    for value in uuids(e['data'].get('persistent_ids',[])):incoming_uids.setdefault(value,[]).append(e['key'])
            aliases={};identity_evidence={}
            for e in entities:
                if e['kind']!='person':continue
                values=uuids(e['data'].get('persistent_ids',[]));prev=old.get(e['key'])
                if prev:
                    previous=uuids(prev['imported'].get('persistent_ids',[]))
                    if values and previous and values.isdisjoint(previous):
                        raise ValueError('Persistent identity conflicts with reused '+e['key']+'. Import separately for manual comparison; this lineage was not changed.')
                else:
                    candidates={next(iter(prior_uids[v])) for v in values if len(prior_uids.get(v,{}))==1 and len(incoming_uids[v])==1}
                    if len(candidates)==1:
                        match=next(iter(candidates));oldkey=next(k for k,v in old.items() if v['id']==match)
                        aliases[e['key']]=oldkey;identity_evidence[e['key']]='Unique persistent UUID match; confirm identity before commit.'
            for e in entities:
                prior_key=e['key']
                for new_key,old_key in aliases.items():prior_key=prior_key.replace(new_key,old_key)
                if prior_key!=e['key'] and prior_key in old:old[e['key']]=old[prior_key]
            preview_ids={e['key']:old[e['key']]['id'] if e['key'] in old else 'new:'+e['key'] for e in entities}
            for e in entities:
                incoming=self.map_edges(e['data'],preview_ids)
                prev=old.get(e['key']); status='addition' if prev is None else ('unchanged' if prev['imported']==incoming else 'change')
                local=self.get(prev['id'])['data'] if prev else None
                if prev and local!=prev['imported'] and local!=incoming:status='conflict'
                if status!='unchanged':stage['comparison'].append(dict(key=e['key'],kind=e['kind'],status=status,before=prev['imported'] if prev else None,local=local,incoming=incoming))
            stage['identity_notice']='Identifiers may be reused or renumbered. Nothing is merged automatically. Review each proposed person mapping; use a separate project if identity is uncertain.'
            stage['person_mappings']=[dict(key=e['key'],incoming=e['data'].get('name'),previous=old[e['key']]['imported'].get('name'),basis=identity_evidence.get(e['key'],'Same lineage cross-reference; identity requires user review.')) for e in entities if e['kind']=='person' and e['key'] in old]
        progress('Ready for review');return stage

    @staticmethod
    def map_edges(data,ids):
        d=dict(data)
        for field in ['source','from','to','owner']:
            if d.get(field+'_key') in ids:d[field+'_id']=ids[d[field+'_key']]
        for field in ['citation','repository','participant']:
            if field+'_keys' in d:d[field+'_ids']=[ids[k] for k in d[field+'_keys'] if k in ids]
        return d

    def commit_import(self,stage,name,identity_confirmed=False,progress=lambda x:None,cancel=lambda:False):
        with self.lock,self.db:
            if stage.get('project'):
                p=stage['project']
                if self.revision(p)!=stage['revision']:raise ValueError('Project changed during preview. Preview again before importing.')
                if stage.get('identical'):return dict(project=p,identical=True)
                if stage.get('person_mappings') and not identity_confirmed:raise ValueError('Review all person identifier mappings before updating this lineage, or import separately.')
            else:
                if not name.strip():raise ValueError('Project name required.')
                p=uid();self.db.execute('INSERT INTO projects VALUES(?,?,0,0,?)',(p,name,now()))
            old=stage.get('prior',{}); snapshot={}; ids={e['key']:old[e['key']]['id'] if e['key'] in old else uid() for e in stage['entities']}
            undo=dict(new=not bool(stage.get('project')),entities=[],attachments=list(stage['attachments']))
            # Convert explicit imported edges to stable local IDs. Missing edges remain in raw keys.
            for i,e in enumerate(stage['entities']):
                if i%1000==0:
                    if cancel():raise ValueError('Cancelled; no changes committed.')
                    progress(f'Committing {i:,} / {len(stage["entities"]):,} records')
                key=e['key'];id=ids[key];d=dict(e['data']);person=ids.get(e['person'])
                d=self.map_edges(d,ids)
                prev=old.get(key);existing=self.db.execute('SELECT * FROM entities WHERE id=?',(id,)).fetchone()
                current=json.loads(existing['data']) if existing else None
                # Three-way field merge: retain user changes and record incoming conflict, never replace a local edit.
                if prev and current:
                    result=dict(current);conflicts=[]
                    for field in set(d)|set(prev['imported']):
                        base=prev['imported'].get(field)
                        if current.get(field)==base:
                            if field in d:result[field]=d[field]
                            else:result.pop(field,None)
                        elif d.get(field)!=base and d.get(field)!=current.get(field):conflicts.append(dict(field=field,local=current.get(field),incoming=d.get(field),previous=base))
                    if conflicts:result['import_conflicts']=conflicts
                else:result=d
                undo['entities'].append(dict(id=id,before=dict(existing) if existing else None))
                self.db.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?)',(id,p,e['kind'],person,dumps(result),now()))
                snapshot[key]=dict(id=id,imported=d)
            # Keep absent prior records and their matching provenance; never delete them.
            for key,value in old.items():snapshot.setdefault(key,value)
            for id,a in stage['attachments'].items():self.db.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?)',(id,p,a['name'],a['mime'],a['hash'],a['content']))
            progress('Validating imported record links')
            for key in ids:
                record=self.get(ids[key]);validate(record['kind'],record['data']);self._refs(p,record['data'],record['person'])
            if cancel():raise ValueError('Cancelled; no changes committed.')
            self.bump(p);iid=uid();report=dict(stage['report'],review_required=True)
            self.db.execute('INSERT INTO imports VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,p,stage['hash'],dumps(report),dumps(snapshot),dumps(stage['raw']),stage['original'],stage['filename'],self.revision(p),dumps(undo),now()))
            return dict(project=p,import_id=iid,report=report)
    def undo_import(self,id):
        with self.lock,self.db:
            row=self.db.execute('SELECT * FROM imports WHERE id=?',(id,)).fetchone()
            if not row:raise ValueError('Import not found.')
            if self.revision(row['project'])!=row['revision']:raise ValueError('Later edits exist. Undo is blocked to protect that work. Restore a backup into a separate project instead.')
            undo=json.loads(row['undo'])
            if undo['new']:self.db.execute('DELETE FROM projects WHERE id=?',(row['project'],))
            else:
                for item in undo['entities']:
                    if item['before']:
                        r=item['before'];self.db.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?)',tuple(r[k] for k in ['id','project','kind','person','data','modified']))
                    else:self.db.execute('DELETE FROM entities WHERE id=?',(item['id'],))
                for aid in undo['attachments']:self.db.execute('DELETE FROM attachments WHERE id=?',(aid,))
                self.db.execute('DELETE FROM imports WHERE id=?',(id,));self.bump(row['project'])
            return dict(undone=True)
    def export(self):
        with self.lock:
            out={'format':'bluegene','version':1,'created':now(),'tables':{}}
            for table in ['projects','entities','history','imports','attachments','directory','settings','migrations']:
                rows=[]
                for r in self.db.execute('SELECT * FROM '+table):
                    row=dict(r)
                    if table=='settings' and not (row['key']=='preferences' or row['key'].startswith('models:')):continue
                    for k,v in row.items():
                        if isinstance(v,bytes):row[k]={'base64':base64.b64encode(v).decode(),'sha256':digest(v)}
                    rows.append(row)
                out['tables'][table]=rows
            return out
    def backup(self):
        export=self.export();blobs={}
        for table,col in [('imports','original'),('attachments','content')]:
            for row in export['tables'][table]:
                value=row[col];path='blobs/'+value['sha256'];blobs[path]=base64.b64decode(value['base64']);row[col]={'path':path,'sha256':value['sha256']}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json',dumps(export))
            for name,value in blobs.items():z.writestr(name,value)
        return buffer.getvalue()
    @staticmethod
    def inspect_backup(data):
        if len(data)>64*1024*1024:raise ValueError('Backup exceeds 64 MiB compressed/import size limit.')
        files=unpack(data,max_file=256*1024*1024,max_expanded=512*1024*1024) if data.startswith(b'PK') else {}
        try:obj=json.loads(files.get('manifest.json',data))
        except (ValueError,UnicodeError):raise ValueError('Invalid backup manifest.')
        if obj.get('format')!='bluegene' or obj.get('version')!=1:raise ValueError('Unsupported backup version.')
        allowed={'projects','entities','history','imports','attachments','directory','settings','migrations'}
        if set(obj.get('tables',{}))!=allowed:raise ValueError('Backup has missing or unexpected tables.')
        for table,col in [('imports','original'),('attachments','content')]:
            for row in obj['tables'][table]:
                value=row[col]
                if 'path' in value:
                    path=safe_path(value['path'])
                    if path not in files:raise ValueError('Missing attachment/import blob.')
                    raw=files[path]
                else:raw=base64.b64decode(value['base64'],validate=True)
                if digest(raw)!=value['sha256']:raise ValueError('Backup checksum mismatch.')
                row[col]=raw
        # Validate in a disposable database, including the actual cross-record relationships.
        test=Store(':memory:')
        try:
            with test.db:
                for table in ['projects','entities','history','imports','attachments','directory','settings']:
                    columns={r['name'] for r in test.db.execute('PRAGMA table_info('+table+')')}
                    for row in obj['tables'][table]:
                        if set(row)!=columns:raise ValueError('Invalid backup columns for '+table)
                        if table=='settings' and row['key']!='preferences' and not row['key'].startswith('models:'):raise ValueError('Backup contains unexpected settings.')
                        test.db.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',list(row.values()))
                for r in test.db.execute('SELECT * FROM entities'):
                    d=validate(r['kind'],json.loads(r['data']));test._refs(r['project'],d,r['person'])
                if test.db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Broken backup references.')
        finally:test.db.close()
        return obj
    def restore(self,obj,destination):
        # Always a new sibling database; original never overwritten.
        destination=Path(destination)
        if destination.exists():raise ValueError('Restore destination already exists.')
        target=Store(destination)
        try:
            with target.db:
                for table in ['projects','entities','history','imports','attachments','directory','settings']:
                    for row in obj['tables'][table]:target.db.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',list(row.values()))
        except Exception:
            target.db.close();destination.unlink(missing_ok=True);raise
        target.db.close();return str(destination)
