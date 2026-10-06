"""Synthetic workload, no personal data. Run: python3 -m scripts.benchmark."""
import json,platform,tempfile,time,subprocess,statistics
from pathlib import Path
from bluegene.store import Store

def main():
    lines=['0 HEAD','1 SOUR BLUEGENE_BENCHMARK','1 GEDC','2 VERS 5.5.1','1 CHAR UTF-8']
    for i in range(10000):
        lines += [f'0 @I{i}@ INDI',f'1 NAME Synthetic{i:05d} /Benchmark/']
        for tag,year in [('BIRT',1840),('RESI',1860),('CENS',1870),('RESI',1880),('DEAT',1900)]:lines += ['1 '+tag,'2 DATE ABT '+str(year),'2 PLAC Fitchburg, Massachusetts, United States']
    lines+=['0 TRLR'];data='\n'.join(lines).encode()
    results={'dataset':{'people':10000,'assertions':50000,'gedcom_bytes':len(data),'synthetic':True},'platform':platform.platform(),'machine':platform.machine(),'logical_cpus':__import__('os').cpu_count(),'python':platform.python_version(),'timings_seconds':{}}
    try:results['hardware']=subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip();results['ram_bytes']=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True))
    except Exception:results['hardware']=results.get('hardware','Hardware name unavailable in sandbox');results['hardware_note']='Some sysctl queries blocked in sandbox'
    with tempfile.TemporaryDirectory() as temp:
        s=Store(Path(temp)/'db.sqlite3')
        def measure(name,fn):
            start=time.perf_counter();out=fn();results['timings_seconds'][name]=round(time.perf_counter()-start,4);return out
        stage=measure('parse_and_preview',lambda:s.stage_import('synthetic.ged',data));result=measure('commit',lambda:s.commit_import(stage,'Synthetic 10k'))
        p=result['project'];search=measure('person_search',lambda:s.records(p,'person',q='Synthetic05000'));person=search['items'][0]
        measure('person_navigation',lambda:s.records(p,person=person['id']));backup=measure('backup',s.backup);results['backup_bytes']=len(backup)
        validated=measure('backup_validation',lambda:s.inspect_backup(backup));measure('restore',lambda:s.restore(validated,Path(temp)/'restored.sqlite3'))
        restored=Store(Path(temp)/'restored.sqlite3');assert restored.records(p,'person')['total']==10000;assert restored.records(p,'assertion')['total']==50000;assert restored.records(p,person=person['id'])==s.records(p,person=person['id'])
        results['restored_person_links_verified']=True;restored.db.close();s.db.close()
    Path('docs/performance.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
