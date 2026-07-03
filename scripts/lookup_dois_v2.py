#!/usr/bin/env python3
"""Batch DOI lookup v2 — smaller batches, save after each batch."""
import json, requests, time, os, sys

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

with open(PUBMED_FILE) as f:
    papers = json.load(f)

need_doi = [(i, p) for i, p in enumerate(papers) if not p.get('doi') and not p.get('pmid') and 'gs_only' in p.get('source', [])]
print(f"Papers needing DOI: {len(need_doi)}", flush=True)

found = 0
missed = 0

for idx, (orig_i, p) in enumerate(need_doi):
    title = p.get('title', '').strip()
    if len(title) < 10:
        missed += 1
        continue
    
    doi = None
    
    # Crossref
    try:
        resp = requests.get('https://api.crossref.org/works', params={
            'query.bibliographic': title,
            'rows': 3,
            'select': 'DOI,title,author'
        }, timeout=15, headers={'User-Agent': 'COCHE/1.0 (coche@cityu.edu.hk)'})
        if resp.status_code == 200:
            items = resp.json().get('message', {}).get('items', [])
            for item in items:
                item_title = (item.get('title', [''])[0] or '').lower()
                if len(item_title) > 20 and item_title[:50] in title.lower():
                    doi = item.get('DOI')
                    auths = item.get('author', [])
                    if auths and not p.get('authors'):
                        names = []
                        alist = []
                        for a in auths:
                            n = f"{a.get('given','')} {a.get('family','')}".strip()
                            names.append(n)
                            alist.append({'name': n, 'affiliations': [], 'is_corresponding': False, 'is_coche': False})
                        p['authors'] = names
                        p['author_list'] = alist
                        p['source'] = ['affiliation']
                    break
    except: pass
    
    # S2 fallback
    if not doi:
        try:
            resp = requests.get('https://api.semanticscholar.org/graph/v1/paper/search', params={
                'query': title[:200], 'limit': 3,
                'fields': 'title,externalIds,authors'
            }, timeout=15, headers={'User-Agent': 'COCHE/1.0'})
            if resp.status_code == 200:
                for item in resp.json().get('data', []):
                    if len(item.get('title','')) > 20 and item['title'].lower()[:50] in title.lower():
                        doi = item.get('externalIds', {}).get('DOI')
                        auths = item.get('authors', [])
                        if auths and not p.get('authors'):
                            names = []
                            alist = []
                            for a in auths:
                                n = a.get('name','')
                                names.append(n)
                                alist.append({'name': n, 'affiliations': [], 'is_corresponding': False, 'is_coche': False})
                            p['authors'] = names
                            p['author_list'] = alist
                            p['source'] = ['affiliation']
                        break
        except: pass
    
    if doi:
        p['doi'] = doi
        found += 1
        print(f"  ✅ [{found}/{idx+1}] {title[:60]}", flush=True)
    else:
        missed += 1
        print(f"  ❌ [{idx+1}] {title[:60]}", flush=True)
    
    time.sleep(0.3)
    
    # Save every 20 papers
    if (idx + 1) % 20 == 0:
        with open(PUBMED_FILE, 'w') as f:
            json.dump(papers, f, indent=2, ensure_ascii=False)
        print(f"  💾 Saved ({idx+1}/{len(need_doi)})", flush=True)

# Final save
with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

still_need = sum(1 for p in papers if not p.get('doi') and not p.get('pmid'))
print(f"\nDone: {found} found, {missed} missed, {still_need} still without DOI", flush=True)
