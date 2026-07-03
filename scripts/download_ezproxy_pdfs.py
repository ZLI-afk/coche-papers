#!/usr/bin/env python3
"""
Download missing PDFs via HKU ezproxy using requests (much faster than Playwright).
Strategy: doi.org via ezproxy → find citation_pdf_url → download PDF.
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

# Find missing
existing_pmids = set()
for root, dirs, files in os.walk(PDF_DIR):
    for fn in files:
        if fn.endswith('.pdf') and fn.startswith('PMID_'):
            existing_pmids.add(fn.split('_')[1])

targets = [p for p in papers if 
           'affiliation' in p.get('source', []) and 
           'innohk_acknowledgement' in p.get('source', []) and
           p.get('doi') and p.get('pmid','') not in existing_pmids]

print(f"Missing PDFs: {len(targets)}")
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
        # Step 1: Go to DOI via ezproxy, get publisher page
        resp = session.get(doi_url, timeout=30, allow_redirects=True)
        html = resp.text
        final_url = resp.url
        
        # Step 2: Find citation_pdf_url
        m = re.search(r'citation_pdf_url["\'][^>]*content=["\']([^"\']+)', html, re.IGNORECASE)
        if m:
            pdf_url = m.group(1)
            # Step 3: Download PDF
            pr = session.get(pdf_url, timeout=60, allow_redirects=True)
            ct = pr.headers.get('content-type', '')
            is_pdf = pr.content[:4] == b'%PDF' or 'application/pdf' in ct
            
            if is_pdf and len(pr.content) > 2000:
                with open(filepath, 'wb') as f:
                    f.write(pr.content)
                return 'cite_pdf', filepath, len(pr.content)
            else:
                return 'cite_not_pdf', filepath, len(pr.content)
        
        # Step 3: Try publisher-specific direct PDF URLs
        doi_part = doi.split('/')[-1]
        
        pdf_candidates = []
        
        if 'wiley.com' in final_url:
            pdf_candidates.append(final_url.replace('/doi/', '/doi/pdfdirect/'))
            pdf_candidates.append(final_url.replace('/doi/', '/doi/epdf/'))
        elif 'acs.org' in final_url:
            pdf_candidates.append(final_url.replace('/doi/abs/', '/doi/pdf/').replace('/doi/full/', '/doi/pdf/').replace('/doi/', '/doi/pdf/'))
        elif 'science.org' in final_url:
            pdf_candidates.append(final_url.replace('/doi/', '/doi/pdf/') + '?download=true')
        elif 'ieee' in final_url:
            # Try stamp.jsp
            arn_match = re.search(r'/document/(\d+)', final_url)
            if arn_match:
                pdf_candidates.append(f'https://ieeexplore-ieee-org.eproxy.lib.hku.hk/stamp/stamp.jsp?tp=&arnumber={arn_match.group(1)}')
        elif 'springer' in final_url:
            pdf_candidates.append(f'https://link-springer-com.eproxy.lib.hku.hk/content/pdf/{doi}.pdf')
        elif 'elsevier' in final_url:
            pdf_candidates.append(final_url.replace('/science/article/pii/', '/science/article/pii/') + '/pdf')
        
        # Also try direct doi.org + publisher pattern
        for pattern in [
            f'https://eproxy.lib.hku.hk/login?url=https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}',
            f'https://eproxy.lib.hku.hk/login?url=https://onlinelibrary.wiley.com/doi/epdf/{doi}',
            f'https://eproxy.lib.hku.hk/login?url=https://pubs.acs.org/doi/pdf/{doi}',
            f'https://eproxy.lib.hku.hk/login?url=https://www.science.org/doi/pdf/{doi}?download=true',
        ]:
            pdf_candidates.append(pattern)
        
        # Step 4: Try each PDF candidate
        for pdf_url in pdf_candidates[:6]:
            try:
                pr = session.get(pdf_url, timeout=60, allow_redirects=True)
                ct = pr.headers.get('content-type', '')
                is_pdf = pr.content[:4] == b'%PDF' or 'application/pdf' in ct
                
                if is_pdf and len(pr.content) > 2000:
                    with open(filepath, 'wb') as f:
                        f.write(pr.content)
                    return 'direct', filepath, len(pr.content)
            except:
                continue
        
        # Step 5: Find PDF links in page HTML
        pdf_links = re.findall(r'href=(?:"|\')([^"\']*\b(?:doi|pdf|article)[^"\']*\.pdf[^"\']*)(?:"|\')', html, re.IGNORECASE)
        if not pdf_links:
            pdf_links = re.findall(r'href=[\"\']([^\"\']*\/pdf\/[^\"\']+|[^\"\']*\.pdf[^\"\']*)[\"\']', html, re.IGNORECASE)
        
        for link in pdf_links[:5]:
            full = urljoin(final_url, link)
            if 'suppl' in full.lower() or 'supplementary' in full.lower() or 'cover' in full.lower():
                continue
            try:
                pr = session.get(full, timeout=60, allow_redirects=True)
                if pr.content[:4] == b'%PDF' and len(pr.content) > 2000:
                    with open(filepath, 'wb') as f:
                        f.write(pr.content)
                    return 'html_link', filepath, len(pr.content)
            except:
                continue
        
        return 'no_pdf_found', filepath, 0
        
    except requests.Timeout:
        return 'timeout', filepath, 0
    except Exception as e:
        return f'err:{str(e)[:50]}', filepath, 0

downloaded = 0
failed = 0

for idx, p in enumerate(targets):
    result, filepath, size = download_paper(p)
    title = p['title'][:55]
    doi = p.get('doi', '')[:40]
    
    if result in ('cite_pdf', 'direct', 'html_link'):
        downloaded += 1
        print(f"  ✅ [{downloaded}/{idx+1}] {title} ({result}:{size//1024}KB)", flush=True)
    elif result == 'exists':
        print(f"  ⏭️ [{idx+1}] Already exists: {title}", flush=True)
    else:
        failed += 1
        print(f"  ❌ [{idx+1}] {result}: {title} [{doi}]", flush=True)
    
    if (idx + 1) % 10 == 0:
        print(f"  📊 {idx+1}/{len(targets)}: {downloaded} ok, {failed} fail", flush=True)
    
    # Polite delay
    time.sleep(0.5)

# Final stats
total = 0
total_size = 0
for r, d, fs in os.walk(PDF_DIR):
    for fn in fs:
        if fn.endswith('.pdf'):
            fp = os.path.join(r, fn)
            total += 1
            total_size += os.path.getsize(fp)

print(f"\n=== Final ===")
print(f"New: {downloaded} | Failed: {failed}")
print(f"Total PDFs: {total} ({total_size/1024/1024:.1f} MB)")
