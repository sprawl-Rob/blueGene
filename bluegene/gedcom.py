"""Lossless line tokenizer + hierarchy parser, followed by explicit semantic mapping.
No remote fetches. Unsupported syntax is rejected, unsupported structures preserved.
"""
from __future__ import annotations
import hashlib, io, re, stat, zipfile, unicodedata
from pathlib import PurePosixPath

MAX_FILE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_ENTRIES = 2000
EVENTS = set('BIRT CHR BAPM DEAT BURI CREM ADOP RESI CENS EMIG IMMI NATU OCCU EDUC RELI EVEN FACT MARR DIV ENGA PROB WILL GRAD RETI'.split())
KNOWN = set('HEAD SOUR VERS NAME CORP ADDR CONT CONC PHON EMAIL WWW DEST DATE TIME SUBM FILE COPR GEDC FORM CHAR LANG PLAC TRLR INDI FAM HUSB WIFE CHIL FAMC FAMS PEDI STAT SEX GIVN SURN NICK NPFX NSFX SPFX TYPE NOTE SNOTE REPO OBJE TITL AUTH PUBL TEXT PAGE DATA QUAY ABBR CALN MEDI RESN RIN REFN CHAN MAP LATI LONG AGE CAUS ASSO RELA ALIA UID EXID'.split()) | EVENTS

def digest(data): return hashlib.sha256(data).hexdigest()

def safe_path(name):
    name = name.replace('\\', '/')
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or ':' in name or '\x00' in name:
        raise ValueError('Unsafe archive or media path. Use relative paths inside the supplied folder.')
    return str(p)

def unpack(data, max_file=None, max_expanded=None):
    max_file = MAX_FILE if max_file is None else max_file
    max_expanded = MAX_EXPANDED if max_expanded is None else max_expanded
    if len(data) > MAX_FILE: raise ValueError('Upload exceeds 64 MiB.')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc: raise ValueError('Not a valid ZIP archive.') from exc
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES: raise ValueError('Archive exceeds 2,000 entries.')
    total, out = 0, {}
    for info in infos:
        name = safe_path(info.filename)
        if stat.S_ISLNK(info.external_attr >> 16): raise ValueError('Archive symlinks are not allowed.')
        if info.flag_bits & 1: raise ValueError('Encrypted ZIP entries are not supported.')
        total += info.file_size
        if total > max_expanded or info.file_size > max_file: raise ValueError('Archive expansion limit exceeded.')
        if info.file_size > 1024 * 1024 and info.file_size / max(1, info.compress_size) > 200:
            raise ValueError('Archive compression ratio exceeds 200:1.')
        if not info.is_dir():
            if name.casefold() in {n.casefold() for n in out}: raise ValueError('Duplicate or ambiguous ZIP paths.')
            out[name] = z.read(info)
    return out

def attachment_type(data, name):
    if len(data) > MAX_FILE: raise ValueError('Attachment exceeds 64 MiB.')
    ext = PurePosixPath(name).suffix.lower()
    signatures = {'.png': (b'\x89PNG\r\n\x1a\n', 'image/png'), '.jpg': (b'\xff\xd8\xff', 'image/jpeg'), '.jpeg': (b'\xff\xd8\xff', 'image/jpeg'), '.pdf': (b'%PDF-', 'application/pdf')}
    if ext in signatures:
        sig, mime = signatures[ext]
        if not data.startswith(sig): raise ValueError('Attachment content does not match its extension.')
        return mime
    if ext == '.txt':
        try: data.decode('utf-8')
        except UnicodeError: raise ValueError('Text attachments must be UTF-8.')
        if b'\x00' in data: raise ValueError('Binary text attachment rejected.')
        return 'text/plain'
    raise ValueError('Supported attachments: JPEG, PNG, PDF, UTF-8 TXT. Active formats are not accepted.')

def date_value(text):
    """Original remains authoritative; search interval is explicitly a heuristic."""
    original = text or ''
    upper = original.upper().strip()
    calendar = 'Gregorian'
    if upper.startswith('@#D'):
        end = upper.find('@', 1)
        calendar = original[3:end] if end >= 0 else 'Unknown'
        upper = upper[end + 1:].strip() if end >= 0 else upper
    out = dict(original=original, calendar=calendar, qualifier=upper.split(' ')[0] if upper else '', precision='unknown', interval=None, assumptions=[])
    if calendar.upper() not in ('GREGORIAN', ''):
        out['assumptions'] = ['Calendar not converted; no derived interval.']; return out
    years = [int(x) for x in re.findall(r'(?<!\d)(\d{3,4})(?!\d)', upper)]
    if not years or '/' in upper or 'B.C.' in upper or 'BCE' in upper: return out
    if upper.startswith(('BET ', 'FROM ')) and len(years) == 2:
        interval = [min(years), max(years)]; out['precision'] = 'range'
    elif upper.startswith(('ABT ', 'ABOUT ', 'CAL ', 'EST ', 'CIRCA ')):
        interval = [years[0]-5, years[0]+5]; out['precision'] = 'approximate'; out['assumptions'] = ['Search window ±5 years, not an exact date.']
    elif upper.startswith(('BEF ', 'BEFORE ')):
        interval = [None, years[0]-1]; out['precision'] = 'before'
    elif upper.startswith(('AFT ', 'AFTER ')):
        interval = [years[0]+1, None]; out['precision'] = 'after'
    elif upper.startswith(('INT ', 'TO ', 'FROM ')) or len(years) != 1: return out
    else:
        if not re.fullmatch(r'(?:[0-9]{1,2} )?(?:(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC) )?[0-9]{3,4}',upper):return out
        interval = [years[0], years[0]]; out['precision'] = 'day' if len(upper.split()) == 3 else ('month' if len(upper.split()) == 2 else 'year')
    out['interval'] = interval
    return out

def decode(data):
    warnings = []
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        encoding = 'utf-16'; text = data.decode(encoding, errors='replace')
    else:
        probe = data[:16384].decode('ascii', errors='ignore')
        charset = next((line.split(' ', 2)[2].strip().upper() for line in probe.splitlines() if line.startswith('1 CHAR ')), 'UTF-8')
        if charset == 'ANSEL':
            # ANSEL requires a full combining-character table. Fail closed, retain original in caller.
            raise ValueError('ANSEL encoding is not yet supported. Re-export as UTF-8 in RootsMagic/Family Tree Maker; do not rename the encoding header.')
        encoding = {'UTF-8':'utf-8-sig','ASCII':'ascii','ANSI':'cp1252','UNICODE':'utf-16'}.get(charset)
        if not encoding: raise ValueError('Unsupported encoding '+charset+'. Re-export as UTF-8.')
        try: text = data.decode(encoding, errors='replace')
        except UnicodeError: raise ValueError('Invalid Unicode encoding; re-export with a UTF-8 BOM or correct byte order.')
        if charset == 'ANSI': warnings.append('Nonstandard ANSI declaration interpreted as Windows-1252; inspect accented names.')
    if '\ufffd' in text: warnings.append('Undecodable bytes replaced in display; original bytes preserved. Review before committing.')
    return text, encoding, warnings

def children(n, tag): return [x for x in n['children'] if x['tag'] == tag]
def child(n, tag): return next(iter(children(n, tag)), None)
def val(n, tag=None):
    if tag is not None: n = child(n, tag)
    if not n: return ''
    text = n['value']
    for c in n['children']:
        if c['tag'] == 'CONT': text += '\n'+val(c)
        elif c['tag'] == 'CONC': text += val(c)
    return text

def parse(data):
    text, encoding, warnings = decode(data)
    roots, stack, xrefs, unsupported = [], [], {}, []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip(): continue
        parts = line.split(' ', 2)
        if len(parts) < 2 or not parts[0].isdigit(): raise ValueError(f'Malformed GEDCOM line {number}: expected level and tag.')
        level, token = int(parts[0]), parts[1]
        rest = parts[2] if len(parts) == 3 else ''
        xref = None
        if token.startswith('@') and token.endswith('@'):
            xref = token; sub = rest.split(' ', 1); token = sub[0]; rest = sub[1] if len(sub) > 1 else ''
        if not token or not all(c.isalnum() or c == '_' for c in token): raise ValueError(f'Invalid tag on line {number}.')
        if level > 64 or level > len(stack): raise ValueError(f'Invalid level jump on line {number}.')
        node = dict(tag=token, value=rest, xref=xref, line=number, children=[])
        if level == 0: roots.append(node)
        else: stack[level-1]['children'].append(node)
        stack = stack[:level] + [node]
        if xref:
            if xref in xrefs: raise ValueError('Duplicate cross-reference '+xref)
            xrefs[xref] = node
        if token not in KNOWN: unsupported.append(dict(tag=token, line=number, reason='Raw preserved; not interpreted'))
    if not roots or roots[0]['tag'] != 'HEAD' or roots[-1]['tag'] != 'TRLR': raise ValueError('GEDCOM must have HEAD and TRLR records.')
    gedc = child(roots[0], 'GEDC')
    version = val(gedc, 'VERS') if gedc else ''
    if version not in ('5.5','5.5.1','7.0','7.0.0','7.0.1','7.0.2','7.0.3','7.0.4','7.0.5','7.0.6','7.0.7','7.0.8','7.0.9'):
        raise ValueError('Unrecognized GEDCOM version '+repr(version)+'. Supported: 5.5, 5.5.1, 7.0.x. Re-export in one of these formats.')
    if version.startswith('7') and encoding != 'utf-8-sig': raise ValueError('GEDCOM 7 requires UTF-8.')
    def walk(n):
        yield n
        for c in n['children']: yield from walk(c)
    for root in roots:
        for n in walk(root):
            if n['value'].startswith('@') and n['value'].endswith('@') and not n['value'].startswith('@#') and n['value'] not in xrefs and n['value'] != '@VOID@':
                warnings.append(f"Unresolved reference {n['value']} at line {n['line']}; retained.")
    return dict(roots=roots, version=version, encoding=encoding, warnings=warnings, unsupported=unsupported, hash=digest(data))

def normalize(parsed):
    roots = parsed['roots']; byref = {n['xref']: n for n in roots if n['xref']}
    entities, media = [], []
    interpreted=set()
    def read(n, tag=None):
        if tag is not None: n=child(n,tag)
        if not n:return ''
        interpreted.add(n['line'])
        for c in n['children']:
            if c['tag'] in ('CONT','CONC'):read(c)
        return val(n)

    def add(kind, key, data, node, person=None):
        interpreted.add(node['line'])
        data = dict(data, origin=dict(record=node.get('_record', node.get('xref')), line=node['line']), review='unreviewed')
        entities.append(dict(kind=kind, key=key, person=person, data=data)); return key
    def notes(n):
        result=[]
        for item in children(n,'NOTE')+children(n,'SNOTE'):
            interpreted.add(item['line'])
            result.append(read(byref.get(item['value'],item)))
        return result
    for root in roots:
        def annotate(n):
            n['_record'] = root['xref']
            for c in n['children']: annotate(c)
        annotate(root)
    def cites(n, owner, person):
        ids=[]
        for c in children(n,'SOUR'):
            key = f"citation:{owner}:{len(ids)}"
            source = c['value'] if byref.get(c['value'],{}).get('tag')=='SOUR' else None
            if not source:
                source='inline-source:'+key
                add('source',source,dict(title=c['value'] or 'Untitled imported source', notes=notes(c)),c)
            ids.append(add('citation',key,dict(source_key=source,locator=read(c,'PAGE'),excerpt=read(child(c,'DATA'),'TEXT') if child(c,'DATA') else read(c,'TEXT'),notes=notes(c),quality_original=read(c,'QUAY'),owner_key=owner),c,person))
        return ids
    def medias(n, owner, person):
        for obj in children(n,'OBJE'):
            interpreted.add(obj['line'])
            resolved = byref.get(obj['value'],obj)
            for f in children(resolved,'FILE'):
                key=f"media:{owner}:{f['line']}"
                entry=dict(owner_key=owner, path=read(f),title=read(resolved,'TITL'),status='remote reference' if read(f).startswith(('http://','https://')) else 'missing',attachment=None)
                add('media',key,entry,f,person); media.append(entry)
    for n in roots:
        key=n['xref'] or f"line:{n['line']}"
        if n['tag']=='REPO': add('repository',key,dict(name=read(n,'NAME'),address=read(n,'ADDR'),notes=notes(n)),n)
        if n['tag']=='SOUR':
            add('source',key,dict(title=read(n,'TITL') or 'Untitled source',creator=read(n,'AUTH'),publication=read(n,'PUBL'),excerpt=read(n,'TEXT'),repository_keys=[read(x) for x in children(n,'REPO')],notes=notes(n),format='unknown',informant='unknown'),n)
            medias(n,key,None)
        if n['tag']=='INDI':
            names=[read(x).replace('/','').strip() for x in children(n,'NAME')]
            add('person',key,dict(name=names[0] if names else 'Unnamed person',aliases=names[1:],names_raw=[x for x in children(n,'NAME')],living='unknown',notes=notes(n),persistent_ids=[read(x) for x in children(n,'UID')],original_id=key),n,key)
            cites(n,key,key); medias(n,key,key)
            event_index={}
            for e in n['children']:
                if e['tag'] in EVENTS:
                    i=event_index.get(e['tag'],0); event_index[e['tag']]=i+1
                    ek=f"{key}:{e['tag']}:{i}"
                    citations=cites(e,ek,key)
                    add('assertion',ek,dict(type=e['tag'],value=e['value'],date=date_value(read(e,'DATE')),place=read(e,'PLAC'),place_status='unresolved',citation_keys=citations,notes=notes(e),rationale='Imported claim; not independently verified.'),e,key)
                    medias(e,ek,key)
            for i,a in enumerate(children(n,'ASSO')):
                add('relationship',f'{key}:ASSO:{i}',dict(from_key=key,to_key=a['value'],type='associate',role_original=read(a,'RELA'),notes=notes(a)),a,key)
        if n['tag']=='FAM':
            parents=children(n,'HUSB')+children(n,'WIFE')
            interpreted.update(p['line'] for p in parents)
            for i,p in enumerate(parents):
                for j,q in enumerate(parents[i+1:]):
                    add('relationship',f'{key}:partner:{i}:{j}',dict(from_key=p['value'],to_key=q['value'],type='partner',role_original=p['tag']+'/'+q['tag'],family_key=key),n,p['value'])
            for c in children(n,'CHIL'):
                cn=byref.get(c['value'],dict(children=[])); pedigree=''
                for fc in children(cn,'FAMC'):
                    if fc['value']==key:
                        interpreted.add(fc['line']);pedigree=read(fc,'PEDI')
                typ={'birth':'biological','adopted':'adoptive','foster':'foster','step':'step'}.get(pedigree.lower(),'unspecified')
                for p in parents:
                    add('relationship',f'{key}:{p["value"]}:{c["value"]}',dict(from_key=p['value'],to_key=c['value'],type=typ,role_original=pedigree or 'unspecified',family_key=key),c,c['value'])
            for e in n['children']:
                if e['tag'] in EVENTS:
                    ek=f"{key}:{e['tag']}:{e['line']}"
                    add('assertion',ek,dict(type=e['tag'],value=e['value'],date=date_value(read(e,'DATE')),place=read(e,'PLAC'),family_key=key,participant_keys=[p['value'] for p in parents],citation_keys=cites(e,ek,parents[0]['value'] if parents else None),notes=notes(e)),e,parents[0]['value'] if parents else None)
    counts={k:sum(e['kind']==k for e in entities) for k in ['person','relationship','assertion','source','citation','repository','media']}
    counts['notes']=sum(len(e['data'].get('notes',[])) for e in entities)
    raw_only=[]
    def audit(n,path):
        path=path+'/'+n['tag']
        if n['line'] not in interpreted:
            raw_only.append(dict(line=n['line'],record=n.get('_record'),path=path,tag=n['tag'],status='preserved raw only'))
        for c in n['children']:audit(c,path)
    for n in roots:audit(n,'')
    # Exact paths and referenced object edges only; never attach by basename.
    return entities, dict(counts=counts,version=parsed['version'],encoding=parsed['encoding'],warnings=parsed['warnings'],unsupported=parsed['unsupported'],hash=parsed['hash'],parsing_failures=0,field_accounting=dict(interpreted_nodes=len(interpreted),raw_only_nodes=len(raw_only),raw_only=raw_only),profiles=[e for e in entities if e['kind']=='person'][:5],preservation='Every raw record, hierarchy, line number and original byte stream retained. Only mapped fields are interpreted; inspect Raw provenance for all others.')
