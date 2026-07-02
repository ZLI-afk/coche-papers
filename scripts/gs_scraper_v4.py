#!/usr/bin/env python3
"""
Fetch COCHE papers from Google Scholar — full version with expanded keywords.
Uses xueshu.lanfanshu.cn mirror via curl for Cloudflare-compatible TLS.
"""
import re
import json
import time
import subprocess
import urllib.parse
import sys

PAGE_DELAY = 1.5
MAX_PAGES_PER_QUERY = 20  # increased from 10

# All query variants — cover every spelling/format
QUERIES = [
    # Full names with different spellings
    '"Hong Kong Centre for Cerebro-cardiovascular Health Engineering"',
    '"Hong Kong Center for Cerebro-cardiovascular Health Engineering"',
    '"Hong Kong Centre for Cerebra-cardiovascular Health Engineering"',
    '"Hong Kong Center for Cerebra-cardiovascular Health Engineering"',
    '"Hong Kong Centre for Cerebrocardiovascular Health Engineering"',
    '"Hong Kong Center for Cerebrocardiovascular Health Engineering"',
    # COCHE abbreviation variants
    '"COCHE" "Hong Kong" "Cardiovascular"',
    '"COCHE" InnoHK',
    'COCHE "Hong Kong Science Park"',
    # Broader searches
    '"Cerebro-cardiovascular Health Engineering" "Hong Kong"',
    '"Cerebrocardiovascular Health Engineering" Hong Kong',
    'InnoHK COCHE',
    # Common affiliation string patterns
    '"Hong Kong Center for Cerebro-Cardiovascular"',
    '"Hong Kong Centre for Cerebro-Cardiovascular"',
]

# Expanded pattern matching for COCHE affiliation
COCHE_PATTERNS = [
    # Full name variants
    r'(?i)hong kong (?:centre|center) for (?:cerebro-?cardiovascular |cerebra-?cardiovascular |cerebro ?cardiovascular |cerebrocardiovascular )health engineering',
    # COCHE abbreviation in HK context
    r'(?i)\bcoche\b.*(?:hong kong|cityu|city university|innohk|hkstp|science park|shatin|kowloon)',
    r'(?i)(?:hong kong|cityu|city university|innohk|hkstp|science park).*\bcoche\b',
    # Oxford-CityU joint
    r'(?i)oxford-cityu centre for cerebro-?cardiovascular',
    # InnoHK project mentions
    r'(?i)innohk project.*hong kong centre.*cerebro',
    r'(?i)innohk.*cerebro-?cardiovascular health engineering',
    # Cerebro-cardiovascular in HK context
    r'(?i)hong kong.*cerebro-?cardiovascular health',
    r'(?i)cerebro-?cardiovascular.*health engineering.*hong kong',
    r'(?i)hong kong (?:cardiovascular and cerebrovascular|cerebrovascular and cardiovascular) health',
    # Abbreviated forms
    r'(?i)hk centre (?:of|for) cerebro-?cardiovascular',
    r'(?i)hongkong (?:centre|center).*cerebro-?cardiovascular',
    # Center without Hong Kong but with known COCHE locations
    r'(?i)(?:center|centre) for cerebro-?cardiovascular health engineering.*(?:city university|hk science|999077|pak shek kok)',
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
        
        # Extract year
        year = ''
        year_m = re.search(r'(\d{4})\s*[-–]', auth)
        if year_m:
            year = year_m.group(1)
        
        # Extract cluster_id for later enrichment
        cluster_id = ''
        cid_m = re.search(r'cluster=(\d+)', html)
        if cid_m:
            cluster_id = cid_m.group(1)
        
        papers.append({
            'title': title,
            'authors_venue': auth,
            'snippet': snippet,
            'citations': citations,
            'year': year,
            'cluster_id': cluster_id,
        })
    
    return papers

def is_coche(text):
    for pat in COCHE_PATTERNS:
        if re.search(pat, text):
            return True
    return False

def main():
    all_papers = {}
    total_gs_results = 0
    blocked_count = 0
    
    for qi, query in enumerate(QUERIES):
        print(f"\n{'='*60}")
        print(f"[{qi+1}/{len(QUERIES)}] Searching: {query}")
        print(f"{'='*60}")
        
        for page in range(MAX_PAGES_PER_QUERY):
            html = fetch_page(query, start=page * 10)
            if len(html) < 1000:
                print(f"  Page {page+1}: empty/blocked (len={len(html)})")
                blocked_count += 1
                if blocked_count >= 3:
                    print(f"  Too many blocks, moving to next query")
                    break
                continue
            blocked_count = 0
            
            papers = parse_page(html)
            if not papers:
                print(f"  Page {page+1}: no results, stopping query")
                break
            
            total_gs_results += len(papers)
            new = 0
            for p in papers:
                key = p['title'][:120].lower()
                if key not in all_papers:
                    text = f"{p['authors_venue']} {p['snippet']}"
                    if is_coche(text):
                        all_papers[key] = p
                        new += 1
            
            print(f"  Page {page+1}: {len(papers)} results, {new} new COCHE, cumulative: {len(all_papers)}")
            
            if len(papers) < 8:
                break
            time.sleep(PAGE_DELAY)
        
        time.sleep(2)
    
    # Sort by citations desc
    papers_list = sorted(all_papers.values(), key=lambda x: x['citations'], reverse=True)
    
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Total GS results scanned: {total_gs_results}")
    print(f"COCHE papers found: {len(papers_list)}")
    print(f"Total citations: {sum(p['citations'] for p in papers_list)}")
    
    # Year distribution
    from collections import Counter
    years = Counter(p.get('year', '?') for p in papers_list)
    print(f"Year distribution: {dict(sorted(years.items()))}")
    
    output = {
        'source': 'Google Scholar via xueshu.lanfanshu.cn (expanded keywords)',
        'total_gs': total_gs_results,
        'coche_count': len(papers_list),
        'coche_papers': papers_list,
    }
    
    output_path = '/home/ubuntu/.openclaw/workspace/coche_gs.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {output_path}")
    
    print("\n=== Top 15 ===")
    for i, p in enumerate(papers_list[:15]):
        print(f"{i+1}. [{p['citations']}c] ({p.get('year','?')}) {p['title'][:90]}")
    
    # Also save ack-only version
    ack_patterns = [
        r'(?i)(?:acknowledge?ments?|thank|funding|grant|support|financially|in part)',
    ]
    ack_only = []
    for p in papers_list:
        snippet = p.get('snippet', '')
        s_lower = snippet.lower()
        is_ack = any(re.search(pat, snippet) for pat in ack_patterns)
        if is_ack:
            ack_only.append(p)
    
    ack_output = {
        'source': 'Google Scholar — Acknowledgment-only COCHE mentions',
        'total': len(ack_only),
        'papers': ack_only,
    }
    with open('/home/ubuntu/.openclaw/workspace/coche_gs_ack_only.json', 'w') as f:
        json.dump(ack_output, f, indent=2, ensure_ascii=False)
    print(f"\nAck-only papers: {len(ack_only)}")
    
    return len(papers_list)

if __name__ == '__main__':
    main()
