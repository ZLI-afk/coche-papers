#!/usr/bin/env python3
"""EZproxy InnoHK scanner — parallel version with concurrency."""
import json, requests, re, time, os
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
MAX_WORKERS = 8

with open(PUBMED_FILE) as f:
    papers = json.load(f)

target = [(i, p) for i, p in enumerate(papers) if 'innohk_acknowledgement' not in p.get('source', []) and (p.get('doi') or p.get('pmid'))]
print(f"Papers to scan: {len(target)}", flush=True)

cookies = {
    'ezproxy': 'e1~Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyl': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyn': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
}
headers = {'User-Agent': 'Mozilla/5.0 (compatible; COCHE-tracker/1.0)'}
pattern = re.compile(r'InnoHK', re.IGNORECASE)

def check_ack_context(html, pos):
    before = html[max(0, pos-800):pos].lower()
    if any(w in before for w in ['acknowledg', 'funding', 'support', 'grant', 'financial']):
        return True
    if re.search(r'(?:RGC|GRF|CRF|Research\s+Grant|project\s+(?:no|number))', before, re.IGNORECASE):
        return True
    if len(html) - pos < 3000:
        if not re.search(r'(?:affiliation|department\s+of|corresponding\s+author)', before[-400:]):
            return True
    return False

def scan_one(orig_i, p):
    doi = p.get('doi', '')
    if not doi:
        return orig_i, None
    
    url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=12, allow_redirects=True)
        html = resp.text
        
        if 'ezproxy.lib.hku.hk/login' in resp.url and len(html) < 1000:
            return orig_i, 'expired'
        
        m = pattern.search(html)
        if m and check_ack_context(html, m.start()):
            snippet = re.sub(r'<[^>]+>', ' ', html[max(0, m.start()-80):m.start()+300])
            snippet = re.sub(r'\s+', ' ', snippet).strip()
            return orig_i, snippet
        return orig_i, None
    except:
        return orig_i, 'error'

new_finds = 0
errors = 0
done = 0
cookie_expired = False

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(scan_one, i, p): (i, p) for i, p in target}
    
    for future in as_completed(futures):
        if cookie_expired:
            break
        done += 1
        try:
            orig_i, result = future.result()
            if result == 'expired':
                print(f"❌ Cookie expired after {done} scans", flush=True)
                cookie_expired = True
            elif result == 'error':
                errors += 1
            elif result:
                papers[orig_i].setdefault('source', []).append('innohk_acknowledgement')
                papers[orig_i]['innohk_snippet'] = result[:300]
                papers[orig_i]['innohk_source'] = 'ezproxy_innohk'
                new_finds += 1
                print(f"  ✅ [{new_finds}] {papers[orig_i]['title'][:60]}", flush=True)
        except:
            errors += 1
        
        if done % 50 == 0:
            with open(PUBMED_FILE, 'w') as f:
                json.dump(papers, f, indent=2, ensure_ascii=False)
            print(f"  💾 {done}/{len(target)} done, {new_finds} InnoHK, {errors} errors", flush=True)

# Final save
with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

innohk_total = sum(1 for p in papers if 'innohk_acknowledgement' in p.get('source', []))
dual = sum(1 for p in papers if 'affiliation' in p.get('source', []) and 'innohk_acknowledgement' in p.get('source', []))
print(f"\n=== Done ===", flush=True)
print(f"Scanned: {done}, Errors: {errors}, New InnoHK: {new_finds}", flush=True)
print(f"⭐ InnoHK total: {innohk_total} ({dual} dual)", flush=True)
