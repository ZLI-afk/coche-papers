#!/usr/bin/env python3
"""
Download PDFs for ALL InnoHK papers — v3 with Unpaywall + direct URL strategies.
Strategies (tried in order):
  1. Unpaywall API → OA PDF
  2. citation_pdf_url meta tag in publisher page
  3. Publisher-specific direct PDF URL patterns
  4. Parse PDF link from EZproxy publisher page
"""
import json, requests, re, time, os, gc, sys
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

def try_download_url(url, filepath):
    """Try to download PDF from a URL. Streams to disk to avoid memory issues."""
    try:
        resp = requests.get(url, headers=headers, timeout=45, allow_redirects=True, stream=True)
        if resp.status_code == 200:
            total = 0
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
            resp.close()
            if total > 2000:
                # Verify PDF magic
                with open(filepath, 'rb') as f:
                    magic = f.read(4)
                if magic == b'%PDF':
                    return total
                else:
                    os.remove(filepath)
                    return 0
            else:
                os.remove(filepath)
                return 0
        resp.close()
        # Also try without EZproxy for OA papers
        if 'eproxy.lib.hku.hk' in url:
            direct_url = url.replace('https://eproxy.lib.hku.hk/login?url=', '')
            if direct_url != url:
                resp2 = requests.get(direct_url, headers=headers, timeout=30, allow_redirects=True, stream=True)
                if resp2.status_code == 200:
                    total2 = 0
                    with open(filepath, 'wb') as f:
                        for chunk in resp2.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                total2 += len(chunk)
                    resp2.close()
                    if total2 > 2000:
                        with open(filepath, 'rb') as f:
                            magic2 = f.read(4)
                        if magic2 == b'%PDF':
                            return total2
                        else:
                            os.remove(filepath)
                    else:
                        os.remove(filepath)
                else:
                    resp2.close()
    except:
        pass
    return 0

def download_one(p):
    doi = p.get('doi', '')
    pmid = p.get('pmid', '')
    if not doi:
        return 'no_doi'
    
    filename = sanitize_filename(p['title'], pmid)
    itc_year = get_itc_year(p)
    year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
    os.makedirs(year_dir, exist_ok=True)
    filepath = os.path.join(year_dir, filename)
    
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        return 'exists'
    
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
        direct_urls = []
        doi_part = doi.split('/')[-1]
        
        if 'acs.org' in final_url or '10.1021/' in doi:
            direct_urls.append(f'https://pubs.acs.org/doi/pdf/{doi}')
        if 'science.org' in final_url or '10.1126/' in doi:
            direct_urls.append(f'https://www.science.org/doi/pdf/{doi}?download=true')
        if 'wiley.com' in final_url or '10.1002/' in doi:
            direct_urls.append(f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}')
        if 'ieee' in final_url or '10.1109/' in doi:
            ar = re.search(r'/document/(\d+)', final_url)
            if ar:
                direct_urls.append(f'https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={ar.group(1)}')
        if 'springer' in final_url or 'link.springer' in final_url or '10.1007/' in doi:
            direct_urls.append(f'https://link.springer.com/content/pdf/{doi}.pdf')
        if 'elsevier' in final_url or '10.1016/' in doi:
            pii = re.search(r'/pii/(S\d+)', final_url)
            if pii:
                direct_urls.append(f'https://linkinghub.elsevier.com/retrieve/pii/{pii.group(1)}/pdf')
        if 'rsc.org' in final_url or '10.1039/' in doi or '10.1038/' in doi:
            # RSC/Nature: article-pdf links usually found in meta/styles
            direct_urls.append(f'https://eproxy.lib.hku.hk/login?url=https://pubs.rsc.org/en/content/articlepdf/{p.get("pub_year","2024")}/{doi}')
        
        for url in direct_urls:
            if 'eproxy.lib.hku.hk' not in url and ('acs.org' in url or 'science.org' in url or 'springer.com' in url or 'wiley.com' in url or 'ieee' in url or 'elsevier' in url):
                # Publisher direct URLs should NOT go through EZproxy (they handle auth independently)
                pass
            elif 'eproxy.lib.hku.hk' not in url:
                url = f'https://eproxy.lib.hku.hk/login?url={url}'
            
            size = try_download_url(url, filepath)
            if size:
                return f'direct:{size//1024}KB'
        
        return 'no_pdf'
        
    except Exception as e:
        return str(e)[:40]

# Main loop
downloaded = 0
failed = 0
exists = 0
cookie_expired = False

for idx, (orig_i, p) in enumerate(target):
    if cookie_expired:
        break
    result = download_one(p)
    
    if result == 'cookie_expired':
        print(f"❌ Cookie expired at {idx+1}", flush=True)
        cookie_expired = True
    elif result == 'exists':
        exists += 1
    elif result and 'KB' in str(result):
        downloaded += 1
        print(f"  ✅ [{downloaded}] {p['title'][:55]} ({result})", flush=True)
    else:
        failed += 1
        if failed <= 5 or failed % 15 == 0:
            print(f"  ❌ {result}: {p['title'][:50]}", flush=True)
    
    time.sleep(0.3)
    # Force garbage collection to manage memory
    gc.collect()
    if (idx + 1) % 15 == 0:
        print(f"  💾 {idx+1}/{len(target)}: {downloaded} ok, {exists} exist, {failed} fail", flush=True)

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
print(f"New: {downloaded} | Skipped: {exists} | Failed: {failed}", flush=True)
print(f"Total PDFs: {total_pdfs} ({total_size//1024//1024} MB)", flush=True)
