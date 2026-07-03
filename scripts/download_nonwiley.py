#!/usr/bin/env python3
"""
Fast download of remaining non-Wiley PDFs via HKU ezproxy.
Uses short timeouts and skips Wiley (needs browser auth refresh).
"""
import json, os, re, sys, time, requests
from urllib.parse import urljoin

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')
os.makedirs(PDF_DIR, exist_ok=True)

COOKIES = {
    'ezproxy': 'e1~Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyl': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyn': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
}
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

session = requests.Session()
session.cookies.update(COOKIES)
session.headers.update(HEADERS)

with open(PUBMED_FILE) as f:
    papers = json.load(f)

existing_pmids = set()
for root, dirs, files in os.walk(PDF_DIR):
    for fn in files:
        if fn.endswith('.pdf') and fn.startswith('PMID_'):
            existing_pmids.add(fn.split('_')[1])

targets = [p for p in papers if 
           'affiliation' in p.get('source', []) and 
           'innohk_acknowledgement' in p.get('source', []) and
           p.get('doi') and p.get('pmid','') not in existing_pmids]

# Only non-Wiley for now
targets = [p for p in targets if '10.1002/' not in p.get('doi','')]
wiley_count = len([p for p in papers if '10.1002/' in p.get('doi','') and p.get('pmid','') not in existing_pmids])

print(f"Non-Wiley missing: {len(targets)}")
print(f"Wiley skipped (needs auth refresh): {wiley_count}")
print(f"Existing: {len(existing_pmids)}")

def sanitize_filename(title, pmid):
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = re.sub(r'\s+', '_', safe)[:80]
    return f"PMID_{pmid}_{safe}.pdf"

def get_itc_year(p):
    y = int(p.get('pub_year', '0') or '0')
    m = (p.get('pub_month', 'Jan') or 'Jan')[:3]
    mn = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
          'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}.get(m, 1)
    return y + 1 if mn == 12 else y

PUBLISHER_PATTERNS = {
    'springer.com':    lambda url, doi: f'https://link-springer-com.eproxy.lib.hku.hk/content/pdf/{doi}.pdf',
    'acs.org':         lambda url, doi: url.replace('/doi/abs/', '/doi/pdf/').replace('/doi/full/', '/doi/pdf/').replace('/doi/', '/doi/pdf/'),
    'science.org':     lambda url, doi: url.replace('/doi/', '/doi/pdf/') + '?download=true',
    'ieee.org':        lambda url, doi: None,  # handled separately
    'elsevier.com':    lambda url, doi: url.replace('/science/article/pii/', '/science/article/pii/') + '/pdf',
    'springeropen.com':lambda url, doi: f'https://link-springer-com.eproxy.lib.hku.hk/content/pdf/{doi}.pdf',
    'nature.com':      lambda url, doi: url.replace('/articles/', '/articles/') + '.pdf',
    'tandfonline.com': lambda url, doi: url.replace('/doi/full/', '/doi/pdf/').replace('/doi/abs/', '/doi/pdf/'),
    'wiley.com':       lambda url, doi: url.replace('/doi/', '/doi/pdf/'),
    'mdpi.com':        lambda url, doi: url.rstrip('/') + '/pdf',
    'frontiersin.org': lambda url, doi: url.rstrip('/') + '/pdf',
    'bmj.com':         lambda url, doi: url.rstrip('/') + '.pdf',
    'rsc.org':         lambda url, doi: url.replace('/articlelanding/', '/articlepdf/'),
}

def download_paper(p):
    doi = p.get('doi', '').strip()
    pmid = p.get('pmid', '')
    title = p['title']
    
    filename = sanitize_filename(title, pmid)
    itc_year = get_itc_year(p)
    year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
    os.makedirs(year_dir, exist_ok=True)
    filepath = os.path.join(year_dir, filename)
    
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        return 'exists', filepath, 0
    
    doi_url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    
    try:
        # Step 1: Go to DOI via ezproxy
        resp = session.get(doi_url, timeout=15, allow_redirects=True)
        html = resp.text
        final_url = resp.url
        
        # Step 2: Find citation_pdf_url
        m = re.search(r'citation_pdf_url["\'][^>]*content=["\']([^"\']+)', html, re.IGNORECASE)
        if m:
            pdf_url = m.group(1)
            pr = session.get(pdf_url, timeout=30, allow_redirects=True, headers={'Referer': final_url})
            if pr.content[:4] == b'%PDF' and len(pr.content) > 2000:
                with open(filepath, 'wb') as f:
                    f.write(pr.content)
                return 'cite_pdf', filepath, len(pr.content)
        
        # Step 3: Try publisher-specific patterns
        pdf_candidates = []
        doi_part = doi.split('/')[-1]
        
        # IEEE special: find arnumber
        if 'ieee.org' in final_url:
            arm = re.search(r'/document/(\d+)', final_url)
            if arm:
                pdf_candidates.append(
                    f'https://ieeexplore-ieee-org.eproxy.lib.hku.hk/stamp/stamp.jsp?tp=&arnumber={arm.group(1)}'
                )
        
        # Check publisher patterns
        for domain, pattern_fn in PUBLISHER_PATTERNS.items():
            if domain in final_url:
                candidate = pattern_fn(final_url, doi)
                if candidate:
                    pdf_candidates.append(candidate)
        
        # Generic doi-based patterns
        pdf_candidates.extend([
            f'https://eproxy.lib.hku.hk/login?url=https://pubs.acs.org/doi/pdf/{doi}',
            f'https://eproxy.lib.hku.hk/login?url=https://www.science.org/doi/pdf/{doi}?download=true',
            f'https://eproxy.lib.hku.hk/login?url=https://www.nature.com/articles/{doi_part}.pdf',
            f'https://eproxy.lib.hku.hk/login?url=https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{doi_part}/pdf/',
        ])
        
        for pdf_url in pdf_candidates:
            if not pdf_url:
                continue
            try:
                pr = session.get(pdf_url, timeout=30, allow_redirects=True, headers={'Referer': final_url})
                if pr.content[:4] == b'%PDF' and len(pr.content) > 2000:
                    with open(filepath, 'wb') as f:
                        f.write(pr.content)
                    return 'direct', filepath, len(pr.content)
            except:
                continue
        
        # Step 4: Find PDF links in page
        pdf_links = re.findall(r'href=[\"\']([^\"\']*(?:\.pdf|/pdf/|/articlepdf/)[^\"\']*)[\"\']', html, re.IGNORECASE)
        for link in pdf_links[:5]:
            full = urljoin(final_url, link)
            if any(w in full.lower() for w in ['suppl', 'supplementary', 'cover', 'graphical']):
                continue
            try:
                pr = session.get(full, timeout=30, allow_redirects=True, headers={'Referer': final_url})
                if pr.content[:4] == b'%PDF' and len(pr.content) > 2000:
                    with open(filepath, 'wb') as f:
                        f.write(pr.content)
                    return 'link', filepath, len(pr.content)
            except:
                continue
        
        return 'no_pdf', filepath, 0
        
    except requests.Timeout:
        return 'timeout', filepath, 0
    except Exception as e:
        return f'err:{str(e)[:30]}', filepath, 0

downloaded = 0
failed = 0

for idx, p in enumerate(targets):
    result, filepath, size = download_paper(p)
    title = p['title'][:55]
    doi = p.get('doi', '')[:30]
    
    if result in ('cite_pdf', 'direct', 'link'):
        downloaded += 1
        print(f"  ✅ [{downloaded}/{idx+1}] {title} ({result}:{size//1024}KB)", flush=True)
    elif result == 'exists':
        print(f"  ⏭️ [{idx+1}] Exists: {title}", flush=True)
    else:
        failed += 1
        print(f"  ❌ [{idx+1}] {result}: {title} [{doi}]", flush=True)
    
    if (idx + 1) % 5 == 0:
        print(f"  📊 {idx+1}/{len(targets)}: {downloaded} ok, {failed} fail", flush=True)
    
    time.sleep(0.3)

# Stats
total = sum(1 for _ in os.walk(PDF_DIR) for f in _[2] if f.endswith('.pdf'))
total_size = sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(PDF_DIR) for f in fs if f.endswith('.pdf'))

print(f"\n=== Final ===")
print(f"New downloaded: {downloaded}, Failed: {failed}")
print(f"Total PDFs: {total} ({total_size/1024/1024:.1f} MB)")
print(f"Wiley remaining: {wiley_count} (needs HKU browser login refresh)")
