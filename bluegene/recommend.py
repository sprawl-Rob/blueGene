"""Deterministic, versioned ranking. Scores are ordering weights, never probabilities."""
import re
RULE_VERSION=1
TYPE_HINTS={'parent':['birth','baptism','probate','census','marriage'],'birth':['birth','baptism','vital'],'death':['death','burial','obituary','probate'],'marriage':['marriage','religious','newspaper'],'immigra':['migration','naturalization','passenger'],'residen':['census','directory','land','newspaper'],'military':['military','pension']}
def tokens(text):return set(re.findall(r'[\w]+',text.casefold()))
def geography(place,coverage):
    if not place or not coverage:return 'unknown'
    a=tokens(place)
    # Recorded names only; aliases must be explicitly provided by a reviewed place mapping.
    for item in coverage:
        b=tokens(item)
        if b and b<=a:return 'known'
    common_words={'united','states','kingdom','of','america','county','province','state'}
    if any((a & tokens(x))-common_words for x in coverage):return 'partial'
    return 'different'
def overlap(interval,ranges):
    if not interval or not ranges:return 'unknown'
    a,b=interval;a=-9999 if a is None else a;b=9999 if b is None else b
    partial=False
    for lo,hi in ranges:
        lo=-9999 if lo is None else lo;hi=9999 if hi is None else hi
        if lo<=a and b<=hi:return 'known'
        if max(lo,a)<=min(hi,b):partial=True
    return 'partial' if partial else 'different'
def filter_resources(entries,filters):
    result=[]
    for e in entries:
        if e.get('archived') and not filters.get('archived'):continue
        if filters.get('q') and filters['q'].lower() not in str(e).lower():continue
        if filters.get('kind') and e.get('kind')!=filters['kind']:continue
        if filters.get('type') and filters['type'] not in e.get('record_types',[]):continue
        if filters.get('language') and filters['language'] not in e.get('languages',[]):continue
        if filters.get('free') and not any(x in e.get('access',{}).get('search',[]) for x in ['free','free account']):continue
        if filters.get('remote') and e.get('capabilities') and all(x in ('onsite','request') for x in e['capabilities']):continue
        if filters.get('place') and geography(filters['place'],e.get('geography',[]))=='different':continue
        if filters.get('start'):
            interval=[int(filters['start']),int(filters.get('end') or filters['start'])]
            if overlap(interval,e.get('dates',[]))=='different':continue
        result.append(e)
    return result

def recommend(person,assertions,question,entries,logs,preferences=None,places=None):
    preferences=preferences or {}; question=question or {}; wants=set(question.get('record_types',[]))
    for needle,types in TYPE_HINTS.items():
        if needle in question.get('title','').lower():wants.update(types)
    hypotheses=[dict(assertion=a['id'],place=a['data'].get('place',''),date=a['data'].get('date',{}),type=a['data'].get('type')) for a in assertions]
    if not hypotheses:hypotheses=[dict(assertion=None,place='',date={},type='unknown')]
    # A selected assertion is an explicit research hypothesis, not a preferred truth value.
    if question.get('assertion_id'):hypotheses=[h for h in hypotheses if h['assertion']==question['assertion_id']] or hypotheses
    results=[];exclusions=[]
    for e in filter_resources(entries,preferences):
        if e.get('kind')=='provider' or e['id'].startswith('path-'):continue
        evaluated=[]
        for h in hypotheses:
            geo=geography(h['place'],e.get('geography',[]));dt=overlap(h['date'].get('interval'),e.get('dates',[]))
            # User-reviewed historical mappings only, respecting effective dates.
            for p in places or []:
                d=p['data']
                if d.get('recorded')==h['place'] and d.get('review')=='accepted by user' and overlap(h['date'].get('interval'),d.get('dates',[]))=='known':
                    mapped=geography(d.get('normalized',''),e.get('geography',[]))
                    if mapped=='known':geo='known'
            evaluated.append((geo,dt,h))
        viable=[x for x in evaluated if x[0]!='different' and x[1]!='different']
        if not viable:
            exclusions.append(dict(id=e['id'],name=e['name'],reason='Known geographic or date coverage does not overlap any supplied hypothesis. Unknown jurisdictions may still need manual review.'));continue
        geo,dt,h=max(viable,key=lambda x:({'known':3,'partial':1,'unknown':0}[x[0]]+{'known':3,'partial':1,'unknown':0}[x[1]],str(x[2]['assertion'])))
        score={'known':40,'partial':15,'unknown':0}[geo]+{'known':30,'partial':10,'unknown':0}[dt]
        match=wants & set(e.get('record_types',[]));score+=20 if match else 0
        reasons=[f'Geography: {geo} match.',f'Dates: {dt} match.']
        if match:reasons.append('Relevant record types: '+', '.join(sorted(match))+'.')
        if e.get('provider') in preferences.get('subscriptions',[]):score+=8;reasons.append('Provider is in your available subscriptions.')
        elif 'free' in e.get('access',{}).get('search',[]):score+=5
        query=' '.join(x for x in [person['data']['name'],h['place'],h['date'].get('original','')] if x)
        exact=[l for l in logs if l['data'].get('collection_id')==e['id'] and l.get('person')==person['id'] and l['data'].get('question_id')==question.get('id') and l['data'].get('query','').strip().casefold()==query.casefold() and l['data'].get('coverage','')==h['date'].get('original','')]
        history=[l for l in logs if l['data'].get('collection_id')==e['id'] and l.get('person')==person['id']]
        alternatives=[]
        if any(l['data'].get('outcome')=='no result' for l in exact):
            score-=25;reasons.append('This exact query and coverage returned no result; avoid repeating it unchanged.')
        if any(l['data'].get('outcome')=='no result' for l in history):
            alternatives=['Try the recorded aliases; an index can miss spelling variants.','Browse images or the catalog for the locality; no indexed result does not establish absence.','Search a household member or nearby year and log the changed scope.']
        if any(l['data'].get('outcome')=='inaccessible' for l in history):reasons.append('A prior attempt was inaccessible; check library access or request copies.')
        uncertainty=[]
        verified_coverage=e.get('verification')=='coverage checked'
        if 'unknown' in (geo,dt):uncertainty.append('Unknown coverage: exploratory, not a confirmed match.')
        if e.get('verification')!='coverage checked':uncertainty.append('Coverage/access verification may be incomplete.')
        if len(hypotheses)>1:uncertainty.append('Multiple assertions exist. This recommendation uses the displayed hypothesis; none were overwritten.')
        if e.get('overlap_group'):uncertainty.append('Overlapping collection group '+e['overlap_group']+'; copies are not independent corroboration.')
        results.append(dict(resource=e,score=score,band='known' if geo==dt=='known' and verified_coverage else ('exploratory' if 'unknown' in (geo,dt) or not verified_coverage else 'partial'),why=reasons,hypothesis=h,question=question.get('title','Find a useful next source'),query=query,variants=person['data'].get('aliases',[]),next_action='Open provider search; copy the query and check actual collection coverage.',alternatives=alternatives,uncertainty=uncertainty))
    results.sort(key=lambda x:({'known':0,'partial':1,'exploratory':2}[x['band']],-x['score'],x['resource']['id']))
    return dict(rule_version=RULE_VERSION,items=results,exclusions=exclusions,notice='Scores rank research opportunities; they are not probabilities. '+('No strong matches: explore unknown coverage, historical jurisdictions and local repositories.' if not any(x['band']=='known' for x in results) else ''))
