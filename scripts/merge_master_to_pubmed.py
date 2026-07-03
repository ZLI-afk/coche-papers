#!/usr/bin/env python3
"""
Merge coche_master.json + coche_pubmed.json into a unified coche_pubmed.json
Preserves all existing enrichments (innohk tags, author_list) from pubmed.
Adds GS-only papers with whatever data is available.
"""
import json
import os

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
MASTER_FILE = os.path.join(WORKSPACE, 'coche_master.json')
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

with open(MASTER_FILE) as f:
    master = json.load(f)
with open(PUBMED_FILE) as f:
    pubmed = json.load(f)

pubmed_by_pmid = {p.get('pmid', ''): p for p in pubmed if p.get('pmid')}
pubmed_by_title_lower = {}
for p in pubmed:
    t = p.get('title', '').lower().strip('.')
    if t:
        pubmed_by_title_lower[t] = p

merged = []
# Keep existing pubmed papers with all enrichments
pubmed_pmids = set()
for p in pubmed:
    merged.append(p)
    pubmed_pmids.add(p.get('pmid', ''))

# Add new papers from master that aren't in pubmed
added_from_master = 0
for mp in master:
    mpmid = mp.get('pmid', '')
    if mpmid and mpmid in pubmed_pmids:
        continue
    if not mpmid:
        # Try title match
        mt = mp.get('title', '').lower().strip('.')
        if mt in pubmed_by_title_lower:
            continue
        # Also try substring match
        found = False
        for pt, pp in pubmed_by_title_lower.items():
            if len(mt) > 30 and (mt[:40] in pt or pt[:40] in mt):
                found = True
                break
        if found:
            continue
    
    # Build a paper entry from master data
    # Determine source field
    source = []
    if 'PubMed' in str(mp.get('source', '')):
        source.append('affiliation')
    if mp.get('coche_authors'):
        source.append('affiliation')
    
    authors = mp.get('authors', [])
    # Build author_list if we have authors
    author_list = []
    coche_authors = mp.get('coche_authors', [])
    for a in authors:
        name = a if isinstance(a, str) else a.get('name', '')
        is_coche = name in coche_authors
        author_list.append({
            'name': name.strip() if name else '',
            'affiliations': [],
            'is_corresponding': False,
            'is_coche': is_coche
        })
    
    entry = {
        'pmid': mpmid,
        'doi': mp.get('doi', '') or '',
        'title': mp.get('title', ''),
        'journal': mp.get('journal', '') or '',
        'pub_year': mp.get('pub_year', '') or str(mp.get('gs_year', '') or ''),
        'pub_month': mp.get('pub_month', '') or '',
        'pub_day': mp.get('pub_day', '') or '',
        'date_is_precise': bool(mp.get('pub_year')),
        'authors': authors if isinstance(authors, list) else [],
        'author_list': author_list,
        'coche_authors': coche_authors,
        'source': source if source else ['gs_only'],
        'gs_citations': mp.get('gs_citations'),
        'gs_snippet': mp.get('gs_snippet'),
    }
    
    merged.append(entry)
    added_from_master += 1

# Sort by date desc
mo = {'Jan':0,'Feb':1,'Mar':2,'Apr':3,'May':4,'Jun':5,'Jul':6,'Aug':7,'Sep':8,'Oct':9,'Nov':10,'Dec':11}
merged.sort(key=lambda p: (
    -int(p.get('pub_year','0') or '0'),
    -mo.get((p.get('pub_month','Jan') or 'Jan')[:3], 0),
    -int((p.get('pub_day','01') or '01'))
))

# Count stats
total = len(merged)
pubmed_src = sum(1 for p in merged if p.get('pmid'))
gs_only = sum(1 for p in merged if 'gs_only' in p.get('source', []))
innohk_tagged = sum(1 for p in merged if 'innohk_acknowledgement' in p.get('source', []))
dual = sum(1 for p in merged if 'affiliation' in p.get('source', []) and 'innohk_acknowledgement' in p.get('source', []))

print(f"Merged: {total} total papers")
print(f"  From PubMed (with PMID): {pubmed_src}")
print(f"  GS-only (no PMID): {gs_only}")
print(f"  Added from master: {added_from_master}")
print(f"  Already had InnoHK tag: {innohk_tagged} ({dual} dual)")

# Save
with open(PUBMED_FILE, 'w') as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)

print(f"\nSaved to {PUBMED_FILE}")
