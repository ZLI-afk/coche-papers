#!/usr/bin/env python3
"""
Scrape Google Scholar via xueshu.lanfanshu.cn mirror using curl.
Filters for actual COCHE institution mention in snippet or author line.
"""
import re
import json
import time
import subprocess
import urllib.parse

BASE_URL = "https://xueshu.lanfanshu.cn/scholar"
CURL_HEADERS = [
    '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    '-H', 'Accept-Language: en-US,en;q=0.5',
]

QUERIES = [
    'Hong Kong Centre for Cerebro-cardiovascular Health Engineering',
    'Hong Kong Center for Cerebro-cardiovascular Health Engineering',
    'COCHE Hong Kong cerebro-cardiovascular engineering',
    'COCHE InnoHK Hong Kong',
]

COCHE_PATTERNS = [
    r'(?i)hong kong (?:centre|center) for (?:cerebro-?cardiovascular|cerebro ?cardiovascular) health engineering',
    r'(?i)coche.*hong kong',
    r'(?i)oxford-cityu centre for cerebro-?cardiovascular',
    r'(?i)cardiovascular and cerebrovascular health research centre.*hong kong',
    r'(?i)innohk.*coche',
]

def is_coche_paper(authors_venue, snippet):
    text = f"{authors_venue} {snippet}"
    for pat in COCHE_PATTERNS:
        if re.search(pat, text):
            return True
    return False

def fetch_page(query, start=0):
    params = urllib.parse.urlencode({
        'q': query,
        'hl': 'en',
        'as_sdt': '0,5',
        'start': start,
    })
    url = f"{BASE_URL}?{params}"
    
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '20'] + CURL_HEADERS + [url],
            capture_output=True, text=True, timeout=25
        )
        return result.stdout
    except Exception as e:
        print(f"    curl error: {e}")
        return ""

def parse_results(html):
    papers = []
    
    # Find all result blocks
    blocks = re.findall(r'<div class="gs_r gs_or gs_scl"[^>]*>(.*?)</div>\s*</div>\s*</div>', html, re.DOTALL)
    
    for block in blocks:
        # Title - try multiple patterns
        title = ''
        for pat in [
            r'<h3 class="gs_rt"[^>]*>.*?<a[^>]*>(.*?)</a>',
            r'<h3 class="gs_rt"[^>]*>.*?<a\b[^>]*>(.*?)</a>',
        ]:
            m = re.search(pat, block, re.DOTALL)
            if m:
                title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if title:
                    break
        
        if not title:
            continue
        
        # Remove things like [PDF] [HTML] etc from title
        title = re.sub(r'^\[[A-Z]+\]\s*', '', title)
        
        # Authors and venue
        authors_venue = ''
        m = re.search(r'<div class="gs_a">(.*?)</div>', block, re.DOTALL)
        if m:
            authors_venue = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        
        # Snippet
        snippet = ''
        m = re.search(r'<div class="gs_rs">(.*?)</div>', block, re.DOTALL)
        if m:
            snippet = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        
        # Citations
        citations = 0
        m = re.search(r'被引用次数：(\d+)', block)
        if not m:
            m = re.search(r'Cited by (\d+)', block)
        if m:
            citations = int(m.group(1))
        
        # Link
        link = ''
        m = re.search(r'href="(https?://[^"]+)"[^>]*id="[^"]*"', block)
        if m:
            link = m.group(1)
        
        papers.append({
            'title': title,
            'authors_venue': authors_venue,
            'snippet': snippet,
            'citations': citations,
            'link': link,
        })
    
    return papers

def main():
    all_papers = {}  # title[:100] -> paper
    
    for query in QUERIES:
        print(f"\n=== Searching: {query} ===")
        
        for page in range(10):
            html = fetch_page(query, start=page * 10)
            papers = parse_results(html)
            
            if not papers:
                print(f"  Page {page+1}: no results, stopping")
                break
            
            new = 0
            for p in papers:
                key = p['title'][:100].lower()
                if key not in all_papers and is_coche_paper(p['authors_venue'], p['snippet']):
                    all_papers[key] = p
                    new += 1
            
            print(f"  Page {page+1}: {len(papers)} results, {new} new COCHE, total: {len(all_papers)}")
            time.sleep(1)
        
        time.sleep(2)
    
    # Sort by citations
    papers_list = sorted(all_papers.values(), key=lambda x: x['citations'], reverse=True)
    
    print(f"\n{'='*60}")
    print(f"Total COCHE papers from Google Scholar: {len(papers_list)}")
    total_cit = sum(p['citations'] for p in papers_list)
    print(f"Total citations: {total_cit}")
    
    output_path = '/home/ubuntu/.openclaw/workspace/coche_gs.json'
    with open(output_path, 'w') as f:
        json.dump(papers_list, f, indent=2, ensure_ascii=False)
    print(f"Saved to {output_path}")
    
    print("\n=== Top 10 ===")
    for i, p in enumerate(papers_list[:10]):
        print(f"{i+1}. [{p['citations']} cit] {p['title'][:80]}")
    
    return len(papers_list)

if __name__ == '__main__':
    main()
