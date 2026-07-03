#!/usr/bin/env python3
"""
Fast resume: skip already-existing PDFs, try remaining papers.
"""
import json, requests, re, time, os, sys
from urllib.parse import urljoin

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')

os.makedirs(PDF_DIR, exist_ok=True)

with open(PUBMED_FILE) as f:
    papers = json.load(f)

target = [(i, p) for i, p in enumerate(papers) if 
          'affiliation' in p.get('source', []) and 
          'innohk_acknowledgement' in p.get('source', []) and
          p.get('doi')]

cookies = {
    'ezproxy': 'e1~Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyl': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyn': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
}
headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}

def sanitize_filename(title, pmid):
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = re.sub(r'\s+', '_', safe)[:80]
    return f"PMID_{pmid}_{safe}.pdf" if pmid else f"NOPMID_{safe}.pdf"

def get_itc_year(p):
    y = int(p.get('pub_year', '0') or '0')
    m = (p.get('pub_month', 'Jan') or 'Jan')[:3]
    mn = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}.get(m, 1)
    return y + 1 if mn == 12 else y

def get_filepath(p):
    doi = p.get('doi', '')
    pmid = p.get('pmid', '')
    filename = sanitize_filename(p['title'], pmid)
    itc_year = get_itc_year(p)
    year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
    os.makedirs(year_dir, exist_ok=True)
    return os.path.join(year_dir, filename)

def pdf_exists(p):
    fp = get_filepath(p)
    return os.path.exists(fp) and os.path.getsize(fp) > 2000

def try_download_url(url, filepath):
    try:
        resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True, stream=True)
        content = resp.content
        if content[:4] == b'%PDF' and len(content) > 2000:
            with open(filepath, 'wb') as f:
                f.write(content)
            return len(content)
        if 'eproxy.lib.hku.hk' in url:
            direct_url = url.replace('https://eproxy.lib.hku.hk/login?url=', '')
            if direct_url != url:
                resp2 = requests.get(direct_url, headers=headers, timeout=20, allow_redirects=True)
                if resp2.content[:4] == b'%PDF' and len(resp2.content) > 2000:
                    with open(filepath, 'wb') as f:
                        f.write(resp2.content)
                    return len(resp2.content)
    except:
        pass
    return 0

def download_one(p):
    doi = p.get('doi', '')
    if not doi:
        return 'no_doi'
    filepath = get_filepath(p)
    
    # Strategy 1: Unpaywall API
    try:
        up = requests.get(f'https://api.unpaywall.org/v2/{doi}?email=coche@cityu.edu.hk', timeout=10).json()
        oa = up.get('best_oa_location', {})
        if oa and oa.get('url_for_pdf'):
            size = try_download_url(oa['url_for_pdf'], filepath)
            if size:
                return f'oa:{size//1024}KB'
    except:
        pass
    
    # Strategy 2: EZproxy publisher page → parse PDF link
    doi_url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    try:
        resp = requests.get(doi_url, headers=headers, cookies=cookies, timeout=20, allow_redirects=True)
        html = resp.text
        final_url = resp.url
        
        if len(html) < 500 and 'login' in final_url and 'eproxy' in final_url:
            return 'cookie_expired'
        
        # Check citation_pdf_url
        m = re.search(r'<meta[^>]*citation_pdf_url[^>]*content="([^"]+)"', html, re.IGNORECASE)
        if m:
            pdf_url = m.group(1)
            if 'eproxy.lib.hku.hk' not in pdf_url:
                pdf_url = f'https://eproxy.lib.hku.hk/login?url={pdf_url}'
            size = try_download_url(pdf_url, filepath)
            if size:
                return f'meta:{size//1024}KB'
        
        # Check PDF links in page
        for link in re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.IGNORECASE):
            if 'supplementary' in link.lower() or 'suppl' in link.lower() or 'cover' in link.lower():
                continue
            pdf_url = urljoin(final_url, link)
            if 'eproxy.lib.hku.hk' not in pdf_url:
                pdf_url = f'https://eproxy.lib.hku.hk/login?url={pdf_url}'
            size = try_download_url(pdf_url, filepath)
            if size:
                return f'link:{size//1024}KB'
        
        # Strategy 3: Publisher-specific direct URL patterns
        doi_part = doi.split('/')[-1]
        
        if 'acs.org' in final_url or '10.1021/' in doi:
            url = f'https://pubs.acs.org/doi/pdf/{doi}'
            size = try_download_url(url, filepath)
            if size: return f'direct-acs:{size//1024}KB'
        if 'science.org' in final_url or '10.1126/' in doi:
            url = f'https://www.science.org/doi/pdf/{doi}?download=true'
            size = try_download_url(url, filepath)
            if size: return f'direct-science:{size//1024}KB'
        if 'wiley.com' in final_url or '10.1002/' in doi:
            url = f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}'
            size = try_download_url(url, filepath)
            if size: return f'direct-wiley:{size//1024}KB'
        if 'ieee' in final_url or '10.1109/' in doi:
            ar = re.search(r'/document/(\d+)', final_url)
            if ar:
                url = f'https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={ar.group(1)}'
                size = try_download_url(url, filepath)
                if size: return f'direct-ieee:{size//1024}KB'
        if 'springer' in final_url or 'link.springer' in final_url or '10.1007/' in doi:
            url = f'https://link.springer.com/content/pdf/{doi}.pdf'
            size = try_download_url(url, filepath)
            if size: return f'direct-springer:{size//1024}KB'
        if 'elsevier' in final_url or '10.1016/' in doi:
            pii = re.search(r'/pii/(S\d+)', final_url)
            if pii:
                url = f'https://linkinghub.elsevier.com/retrieve/pii/{pii.group(1)}/pdf'
                size = try_download_url(url, filepath)
                if size: return f'direct-elsevier:{size//1024}KB'
        if 'rsc.org' in final_url or '10.1039/' in doi:
            url = f'https://eproxy.lib.hku.hk/login?url=https://pubs.rsc.org/en/content/articlepdf/{p.get("pub_year","2024")}/{doi}'
            size = try_download_url(url, filepath)
            if size: return f'direct-rsc:{size//1024}KB'
        
        return 'no_pdf'
    except Exception as e:
        return str(e)[:40]

# Pre-filter: skip existing
remaining = []
for orig_i, p in target:
    if not pdf_exists(p):
        remaining.append((orig_i, p))

print(f"Skipping {len(target) - len(remaining)} existing PDFs, {len(remaining)} remaining", flush=True)

downloaded = 0
failed = 0
cookie_expired = False

for idx, (orig_i, p) in enumerate(remaining):
    if cookie_expired:
        break
    result = download_one(p)
    
    if result == 'cookie_expired':
        print(f"❌ Cookie expired at {idx+1}", flush=True)
        cookie_expired = True
    elif result and 'KB' in str(result):
        downloaded += 1
        print(f"  ✅ [{downloaded}] {p['title'][:55]} ({result})", flush=True)
    else:
        failed += 1
        if failed <= 10 or failed % 20 == 0:
            print(f"  ❌ {result}: {p['title'][:50]}", flush=True)
    
    time.sleep(0.3)
    if (idx + 1) % 20 == 0:
        print(f"  💾 {idx+1}/{len(remaining)}: {downloaded} ok, {failed} fail", flush=True)

# Summary
total_pdfs = 0
total_size = 0
for root, dirs, files in os.walk(PDF_DIR):
    for f in files:
        if f.endswith('.pdf'):
            fp = os.path.join(root, f)
            total_pdfs += 1
            total_size += os.path.getsize(fp)

print(f"\n=== Final ===", flush=True)
print(f"New: {downloaded} | Skipped: {len(target) - len(remaining) - downloaded} | Failed: {failed}", flush=True)
print(f"Total PDFs: {total_pdfs} ({total_size//1024//1024} MB)", flush=True)
