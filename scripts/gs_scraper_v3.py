#!/usr/bin/env python3
"""
Fetch COCHE papers from Google Scholar via xueshu.lanfanshu.cn mirror.
Uses curl for Cloudflare-compatible TLS, pipes to Python for parsing.
"""
import re
import json
import time
import subprocess
import urllib.parse
import sys

PAGE_DELAY = 1.5
MAX_PAGES_PER_QUERY = 10

QUERIES = [
    'Hong Kong Centre for Cerebro-cardiovascular Health Engineering',
    'COCHE Hong Kong cerebro-cardiovascular engineering',
    'COCHE InnoHK Hong Kong',
]

# Patterns that identify a paper as actually COCHE-affiliated
COCHE_PATTERNS = [
    r'(?i)hong kong (?:centre|center) for (?:cerebro-?cardiovascular |cerebro ?cardiovascular )health engineering',
    r'(?i)coche.*hong kong',
    r'(?i)oxford-cityu centre for cerebro-?cardiovascular',
    r'(?i)cardiovascular and cerebrovascular health research centre.*hong kong',
    r'(?i)innohk project at hong kong centre.*cerebro',
    r'(?i)hong kong cardiovascular and cerebrovascular health engineering',
    r'(?i)hongkong centre of cerebro-?cardiovascular',
]

def fetch_page(query, start=0):
    params = urllib.parse.urlencode({
        'q': query,
        'hl': 'en',
        'as_sdt': '0,5',
        'start': start,
    })
    url = f"https://xueshu.lanfanshu.cn/scholar?{params}"
    
    try:
        result = subprocess.run([
            'curl', '-s', '--max-time', '20',
            '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            url
        ], capture_output=True, text=True, timeout=25, stdin=subprocess.DEVNULL)
        return result.stdout
    except Exception as e:
        print(f"    curl error: {e}")
        return ""

def parse_page(html):
    papers = []
    blocks = html.split('<div class="gs_r gs_or gs_scl"')
    
    for block in blocks[1:]:
        title_m = re.search(r'<h3 class="gs_rt"[^>]*>(.*?)</h3>', block, re.DOTALL)
        if not title_m:
            continue
        
        title_parts = re.findall(r'<a[^>]*>(.*?)</a>', title_m.group(1), re.DOTALL)
        if not title_parts:
            title_parts = [title_m.group(1)]
        title = re.sub(r'<[^>]+>', '', ' '.join(title_parts)).strip()
        title = re.sub(r'^\[[A-Z]+\]\s*', '', title)
        
        if not title or len(title) < 10:
            continue
        
        auth_m = re.search(r'<div class="gs_a">(.*?)</div>', block, re.DOTALL)
        auth = re.sub(r'<[^>]+>', '', auth_m.group(1)).strip() if auth_m else ''
        
        snip_m = re.search(r'<div class="gs_rs">(.*?)</div>', block, re.DOTALL)
        snippet = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip() if snip_m else ''
        
        cit_m = re.search(r'被引用次数：(\d+)', block)
        if not cit_m:
            cit_m = re.search(r'Cited by (\d+)', block)
        citations = int(cit_m.group(1)) if cit_m else 0
        
        # Extract link
        link = ''
        link_m = re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*id="[^"]*"', block)
        if link_m:
            link = link_m.group(1)
        
        papers.append({
            'title': title,
            'authors_venue': auth,
            'snippet': snippet,
            'citations': citations,
            'link': link,
        })
    
    return papers

def is_coche(text):
    for pat in COCHE_PATTERNS:
        if re.search(pat, text):
            return True
    return False

def main():
    all_papers = {}
    
    for query in QUERIES:
        print(f"\n{'='*50}")
        print(f"Searching: {query}")
        print(f"{'='*50}")
        
        for page in range(MAX_PAGES_PER_QUERY):
            html = fetch_page(query, start=page * 10)
            if len(html) < 1000:
                print(f"  Page {page+1}: empty/blocked response")
                break
            
            papers = parse_page(html)
            if not papers:
                print(f"  Page {page+1}: no results parsed, stopping")
                break
            
            new = 0
            for p in papers:
                key = p['title'][:100].lower()
                if key not in all_papers:
                    text = f"{p['authors_venue']} {p['snippet']}"
                    if is_coche(text):
                        all_papers[key] = p
                        new += 1
            
            print(f"  Page {page+1}: {len(papers)} results, {new} new COCHE, total: {len(all_papers)}")
            time.sleep(PAGE_DELAY)
        
        time.sleep(2)
    
    # Sort
    papers_list = sorted(all_papers.values(), key=lambda x: x['citations'], reverse=True)
    
    print(f"\n{'='*60}")
    print(f"Google Scholar COCHE papers: {len(papers_list)}")
    print(f"Total citations: {sum(p['citations'] for p in papers_list)}")
    
    output = {
        'source': 'Google Scholar via xueshu.lanfanshu.cn',
        'total': len(papers_list),
        'papers': papers_list,
    }
    
    with open('/home/ubuntu/.openclaw/workspace/coche_gs.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Saved to coche_gs.json")
    
    print("\n=== Top 10 ===")
    for i, p in enumerate(papers_list[:10]):
        print(f"{i+1}. [{p['citations']} cit] {p['title'][:80]}")
    
    return len(papers_list)

if __name__ == '__main__':
    main()
