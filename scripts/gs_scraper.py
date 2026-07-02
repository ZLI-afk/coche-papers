#!/usr/bin/env python3
"""
Scrape Google Scholar results from xueshu.lanfanshu.cn (GS mirror)
for COCHE papers. Filters by actual COCHE affiliation mention.
"""
import re
import json
import time
import urllib.request
import urllib.parse
import sys

BASE_URL = "https://xueshu.lanfanshu.cn/scholar"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

QUERIES = [
    'Hong Kong Centre for Cerebro-cardiovascular Health Engineering',
    'Hong Kong Center for Cerebro-cardiovascular Health Engineering',
    'Hong Kong Centre for Cerebrocardiovascular Health Engineering',
    'Hong Kong Center for Cerebrocardiovascular Health Engineering',
    'COCHE Hong Kong cerebro-cardiovascular',
    'COCHE InnoHK Hong Kong',
]

COCHE_KEYWORDS = [
    'hong kong centre for cerebro-cardiovascular health engineering',
    'hong kong center for cerebro-cardiovascular health engineering',
    'hong kong centre for cerebrocardiovascular health engineering',
    'hong kong center for cerebrocardiovascular health engineering',
    'coche hong kong',
    'oxford-cityu centre for cerebro-cardiovascular',
    'oxford-cityu centre for cerebrocardiovascular',
    'cardiovascular and cerebrovascular health research centre',
    'cerebro-cardiovascular health engineering (coche)',
    'cerebrocardiovascular health engineering (coche)',
    'hong kong cardiovascular and cerebrovascular',
    'coche innohk',
]

def is_coche_paper(text):
    """Check if paper text mentions COCHE institution."""
    text_lower = text.lower()
    for kw in COCHE_KEYWORDS:
        if kw in text_lower:
            return True
    return False

def search_gs(query, start=0, max_pages=10):
    """Search Google Scholar mirror and return results."""
    all_results = []
    
    for page in range(max_pages):
        params = urllib.parse.urlencode({
            'q': query,
            'hl': 'en',
            'as_sdt': '0,5',
            'start': start + page * 10,
        })
        url = f"{BASE_URL}?{params}"
        
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode('utf-8', errors='replace')
        except Exception as e:
            print(f"  Error page {page}: {e}")
            break
        
        # Parse results
        papers = parse_results(html)
        if not papers:
            print(f"  No results found on page {page}, stopping")
            break
        
        all_results.extend(papers)
        print(f"  Page {page+1}: {len(papers)} results, total so far: {len(all_results)}")
        
        time.sleep(1.5)
    
    return all_results

def parse_results(html):
    """Parse Google Scholar search results from HTML."""
    papers = []
    
    # Find result blocks
    blocks = re.findall(r'<div class="gs_r gs_or gs_scl"[^>]*>(.*?)</div>\s*</div>\s*</div>', html, re.DOTALL)
    if not blocks:
        blocks = re.findall(r'<div class="gs_r gs_or gs_scl"[^>]*>(.*?)</div>\s*<div class="gs_r', html, re.DOTALL)
    
    for block in blocks:
        # Title
        title_match = re.search(r'<h3 class="gs_rt"[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_match:
            continue
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        
        # Authors and venue
        authors_venue = ''
        auth_match = re.search(r'<div class="gs_a">(.*?)</div>', block, re.DOTALL)
        if auth_match:
            authors_venue = re.sub(r'<[^>]+>', '', auth_match.group(1)).strip()
        
        # Snippet
        snippet = ''
        snip_match = re.search(r'<div class="gs_rs">(.*?)</div>', block, re.DOTALL)
        if snip_match:
            snippet = re.sub(r'<[^>]+>', '', snip_match.group(1)).strip()
        
        # Citations
        citations = 0
        cit_match = re.search(r'被引用次数：(\d+)', block)
        if not cit_match:
            cit_match = re.search(r'Cited by (\d+)', block)
        if cit_match:
            citations = int(cit_match.group(1))
        
        # Link
        link = ''
        link_match = re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*id="[^"]*"', block)
        if link_match:
            link = link_match.group(1)
        
        # Cluster ID (for GS internal)
        cluster_id = ''
        cid_match = re.search(r'data-cid="([^"]+)"', block)
        if cid_match:
            cluster_id = cid_match.group(1)
        
        papers.append({
            'title': title,
            'authors_venue': authors_venue,
            'snippet': snippet,
            'citations': citations,
            'link': link,
            'cluster_id': cluster_id,
        })
    
    return papers

def main():
    all_papers = {}
    
    for query in QUERIES:
        print(f"\n=== Searching: {query} ===")
        results = search_gs(query, max_pages=10)
        
        for r in results:
            # Use title as key for dedup
            key = r['title'].lower()[:100]
            if key not in all_papers:
                # Check if this paper mentions COCHE
                full_text = f"{r['snippet']} {r['authors_venue']}"
                if is_coche_paper(full_text):
                    all_papers[key] = r
        
        print(f"  COCHE papers found so far: {len(all_papers)}")
        time.sleep(2)
    
    # Sort by citations
    papers_list = sorted(all_papers.values(), key=lambda x: x['citations'], reverse=True)
    
    print(f"\n{'='*60}")
    print(f"Total COCHE papers found: {len(papers_list)}")
    total_cit = sum(p['citations'] for p in papers_list)
    print(f"Total citations: {total_cit}")
    
    # Save
    output_path = '/home/ubuntu/.openclaw/workspace/coche_gs.json'
    with open(output_path, 'w') as f:
        json.dump(papers_list, f, indent=2, ensure_ascii=False)
    print(f"Saved to {output_path}")
    
    # Print top 10
    print("\n=== Top 10 ===")
    for i, p in enumerate(papers_list[:10]):
        print(f"{i+1}. [{p['citations']} cit] {p['title'][:80]}")
    
    return len(papers_list)

if __name__ == '__main__':
    main()
