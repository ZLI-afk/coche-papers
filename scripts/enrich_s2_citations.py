#!/usr/bin/env python3
"""
Enrich COCHE PubMed papers with Semantic Scholar citation counts.
Uses the official Semantic Scholar API batch endpoint.
"""

import json
import time
import sys
import os

S2_KEY = "s2k-Xgbsn7RcgCpzu339FtNOh4wrSsHxvnwU7XVmY3FO"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
BATCH_SIZE = 20  # Max batch size for S2
REQUEST_DELAY = 1.5  # seconds between requests (rate limit safety)

PUBMED_FILE = os.path.expanduser("~/.openclaw/workspace/coche_pubmed.json")
OUTPUT_FILE = os.path.expanduser("~/.openclaw/workspace/coche_s2_citations.json")

import urllib.request
import urllib.error

def s2_batch_lookup(doi_list, fields="citationCount,title,year,externalIds"):
    """Batch lookup papers by DOI on Semantic Scholar."""
    ids = [f"DOI:{doi}" for doi in doi_list if doi]
    if not ids:
        return []
    
    data = json.dumps({"ids": ids}).encode('utf-8')
    req = urllib.request.Request(
        f"{S2_BATCH_URL}?fields={fields}",
        data=data,
        headers={
            "x-api-key": S2_KEY,
            "Content-Type": "application/json"
        },
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code}: {body[:200]}")
        if e.code == 429:
            print("  Rate limited, waiting 30s...")
            time.sleep(30)
            return s2_batch_lookup(doi_list, fields)  # retry
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None

def main():
    # Load PubMed papers
    with open(PUBMED_FILE) as f:
        papers = json.load(f)
    
    print(f"Loaded {len(papers)} papers from PubMed")
    
    # Load existing S2 data if any
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            existing_list = json.load(f)
            existing = {p.get('pmid', ''): p for p in existing_list}
        print(f"Loaded {len(existing)} existing S2 records")
    
    # Enrich in batches
    enriched = []
    to_lookup = []
    
    for paper in papers:
        pmid = paper.get('pmid', '')
        doi = paper.get('doi', '')
        
        if pmid in existing and existing[pmid].get('s2_citations') is not None:
            enriched.append(existing[pmid])
            continue
        
        enriched.append({
            'pmid': pmid,
            'doi': doi,
            'title': paper.get('title', ''),
            's2_citations': None,
            's2_paper_id': None,
        })
        
        if doi:
            to_lookup.append((pmid, doi))
    
    print(f"Need to look up {len(to_lookup)} papers on Semantic Scholar")
    
    # Batch lookup
    for i in range(0, len(to_lookup), BATCH_SIZE):
        batch = to_lookup[i:i+BATCH_SIZE]
        dois = [d for _, d in batch]
        
        print(f"  Batch {i//BATCH_SIZE + 1}/{(len(to_lookup)-1)//BATCH_SIZE + 1}: "
              f"looking up {len(dois)} DOIs...", end=" ", flush=True)
        
        results = s2_batch_lookup(dois)
        
        if results is None:
            print("FAILED, skipping batch")
            time.sleep(REQUEST_DELAY)
            continue
        
        # Map results back
        result_map = {}
        for r in results:
            if r is not None:
                # Get DOI from externalIds
                ext = r.get('externalIds', {}) or {}
                result_doi = ext.get('DOI', '')
                if result_doi:
                    result_map[result_doi.lower()] = r
        
        found = 0
        for pmid, doi in batch:
            r = result_map.get(doi.lower(), {})
            citations = r.get('citationCount')
            paper_id = r.get('paperId', '')
            
            for e in enriched:
                if e['pmid'] == pmid:
                    e['s2_citations'] = citations
                    e['s2_paper_id'] = paper_id
                    if citations is not None:
                        found += 1
                    break
        
        print(f"found {found}/{len(batch)}")
        
        # Save intermediate
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(enriched, f, indent=2)
        
        time.sleep(REQUEST_DELAY)
    
    # Summary
    with_citations = sum(1 for e in enriched if e['s2_citations'] is not None)
    total_citations = sum(e['s2_citations'] or 0 for e in enriched)
    
    print(f"\nDone! {with_citations}/{len(enriched)} papers have S2 citations")
    print(f"Total citations: {total_citations}")
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
