#!/usr/bin/env python3
"""
Batch lookup DOIs for papers missing DOI via Crossref + Semantic Scholar APIs.
"""
import json, requests, time, sys, os, re

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)  # type: ignore
sys.stderr.reconfigure(line_buffering=True)  # type: ignore

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

with open(PUBMED_FILE) as f:
    papers = json.load(f)

need_doi = [p for p in papers if not p.get('doi') and not p.get('pmid') and 'gs_only' in p.get('source', [])]
print(f"Papers needing DOI lookup: {len(need_doi)}")

found_doi = 0
not_found = 0

for i, p in enumerate(need_doi):
    title = p.get('title', '').strip()
    if not title or len(title) < 10:
        not_found += 1
        continue
    
    # Try Crossref first
    doi = None
    try:
        resp = requests.get('https://api.crossref.org/works', params={
            'query.bibliographic': title,
            'rows': 3,
            'select': 'DOI,title,author'
        }, timeout=15, headers={'User-Agent': 'COCHE-Tracker/1.0 (mailto:coche@example.com)'})
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('message', {}).get('items', [])
            for item in items:
                item_title = item.get('title', [''])[0] if item.get('title') else ''
                # Check title similarity
                if len(item_title) > 20 and (item_title.lower()[:50] in title.lower() or title.lower()[:50] in item_title.lower()):
                    doi = item.get('DOI')
                    # Also get authors if missing
                    if not p.get('authors') or len(p.get('authors', [])) == 0:
                        authors = item.get('author', [])
                        if authors:
                            author_names = []
                            author_list = []
                            for a in authors:
                                given = a.get('given', '')
                                family = a.get('family', '')
                                name = f"{given} {family}".strip()
                                author_names.append(name)
                                author_list.append({
                                    'name': name,
                                    'affiliations': [],
                                    'is_corresponding': False,
                                    'is_coche': False
                                })
                            p['authors'] = author_names
                            p['author_list'] = author_list
                            p['source'] = [s for s in p.get('source', []) if s != 'gs_only'] + ['affiliation']
                    break
    except Exception as e:
        pass
    
    # Try Semantic Scholar if Crossref didn't find
    if not doi:
        try:
            # S2 title search
            resp = requests.get('https://api.semanticscholar.org/graph/v1/paper/search', params={
                'query': title[:200],
                'limit': 3,
                'fields': 'title,externalIds,authors'
            }, timeout=15, headers={'User-Agent': 'COCHE-Tracker/1.0'})
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get('data', []):
                    item_title = item.get('title', '')
                    if len(item_title) > 20 and (item_title.lower()[:50] in title.lower() or title.lower()[:50] in item_title.lower()):
                        ext_ids = item.get('externalIds', {})
                        doi = ext_ids.get('DOI')
                        if doi:
                            # Get authors
                            if not p.get('authors') or len(p.get('authors', [])) == 0:
                                authors = item.get('authors', [])
                                author_names = []
                                author_list = []
                                for a in authors:
                                    name = a.get('name', '')
                                    author_names.append(name)
                                    author_list.append({
                                        'name': name,
                                        'affiliations': [],
                                        'is_corresponding': False,
                                        'is_coche': False
                                    })
                                p['authors'] = author_names
                                p['author_list'] = author_list
                                if 'gs_only' in p.get('source', []):
                                    p['source'] = [s for s in p.get('source', []) if s != 'gs_only'] + ['affiliation']
                        break
        except Exception as e:
            pass
    
    if doi:
        p['doi'] = doi
        found_doi += 1
        print(f"  ✅ [{found_doi}/{i+1}] {title[:60]}")
        print(f"      DOI: {doi}")
    else:
        not_found += 1
        if not_found <= 5 or not_found % 20 == 0:
            print(f"  ❌ [{i+1}/{len(need_doi)}] {title[:60]}")
    
    time.sleep(0.3)
    if (i + 1) % 30 == 0:
        print(f"  ... {i+1}/{len(need_doi)} done, {found_doi} found, {not_found} not found")

# Save
with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

# Stats
gs_papers = [p for p in papers if 'gs_only' in p.get('source', [])]
still_no_doi = sum(1 for p in papers if not p.get('doi') and not p.get('pmid'))
print(f"\n=== Results ===")
print(f"Total papers: {len(papers)}")
print(f"DOI lookup: {found_doi} found, {not_found} not found")
print(f"GS-only remaining: {len(gs_papers)}")
print(f"Papers still without DOI/PMID: {still_no_doi}")
