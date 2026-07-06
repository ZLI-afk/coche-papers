#!/usr/bin/env python3
"""
Download PDFs for InnoHK dual-channel papers — v5 (extra strategies).
Adds more aggressive direct URL patterns and a try with unpaywall green OA.
"""
import json, requests, re, time, os, gc

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')
PROGRESS_FILE = os.path.join(WORKSPACE, 'pdf_download_progress.json')

os.makedirs(PDF_DIR, exist_ok=True)

headers = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/pdf,text/html,*/*',
}

def sanitize_filename(title, pmid):
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = re.sub(r'\s+', '_', safe)[:80]
    return f"PMID_{pmid}_{safe}.pdf" if pmid else f"NOPMID_{safe}.pdf"

def get_itc_year(p):
    y = int(p.get('pub_year', '0') or '0')
    m = (p.get('pub_month', 'Jan') or 'Jan')[:3]
    mn = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
          'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}.get(m, 1)
    return y + 1 if mn == 12 else y

def stream_download(url, filepath, timeout=30, referer=None, accept='application/pdf,text/html,*/*'):
    h = dict(headers)
    h['Accept'] = accept
    if referer:
        h['Referer'] = referer
    try:
        resp = requests.get(url, headers=h, timeout=timeout,
                          allow_redirects=True, stream=True)
        if resp.status_code == 200:
            # Check if HTML (not PDF)
            ct = resp.headers.get('content-type','')
            if 'text/html' in ct and 'application/pdf' not in ct:
                resp.close()
                return 0
            total = 0
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
            resp.close()
            if total > 2000:
                with open(filepath, 'rb') as f:
                    magic = f.read(4)
                if magic == b'%PDF':
                    return total
            os.remove(filepath)
            return 0
        resp.close()
    except:
        return 0
    return 0

def download_one(p):
    doi = p.get('doi', '')
    pmid = p.get('pmid', '')
    
    filename = sanitize_filename(p['title'], pmid)
    itc_year = get_itc_year(p)
    year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
    os.makedirs(year_dir, exist_ok=True)
    filepath = os.path.join(year_dir, filename)
    
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        return 'exists'
    
    # Strategy 0: Unpaywall (already tried, but try again in case it's new)
    try:
        up = requests.get(f'https://api.unpaywall.org/v2/{doi}?email=coche@cityu.edu.hk', timeout=10).json()
        oa = up.get('best_oa_location', {})
        if oa and oa.get('url_for_pdf'):
            size = stream_download(oa['url_for_pdf'], filepath, timeout=30)
            if size:
                return f'oa:{size//1024}KB'
    except:
        pass
    
    # Strategy 1: Multi-publisher direct URL barrage
    urls = []
    
    # Common bypass URLs
    doi_encoded = doi.replace('/', '%2F')
    doi_article_id = doi.split('/')[-1]
    
    # Wiley - try multiple patterns
    if '10.1002/' in doi:
        urls += [
            f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true',
            f'https://onlinelibrary.wiley.com/doi/pdf/{doi}',
            f'https://onlinelibrary.wiley.com/doi/epdf/{doi}',
        ]
    
    # Science Advances / AAAS
    if '10.1126/' in doi:
        urls += [
            f'https://www.science.org/doi/pdf/{doi}?download=true',
            f'https://www.science.org/doi/epdf/{doi}',
        ]
    
    # RSC
    if '10.1039/' in doi:
        urls += [
            f'https://pubs.rsc.org/en/content/articlepdf/{p.get("pub_year","2024")}/{doi}',
            f'https://pubs.rsc.org/en/content/articlelanding/{p.get("pub_year","2024")}/{doi}',
        ]
    
    # ACS
    if '10.1021/' in doi:
        urls += [
            f'https://pubs.acs.org/doi/pdf/{doi}?download=true',
            f'https://pubs.acs.org/doi/pdf/{doi}',
            f'https://pubs.acs.org/doi/epdf/{doi}',
        ]
    
    # Nature
    if '10.1038/' in doi:
        urls += [
            f'https://www.nature.com/articles/{doi_article_id}.pdf',
            f'https://www.nature.com/articles/{doi_article_id}/pdf',
        ]
    
    # PNAS
    if '10.1073/' in doi:
        urls += [
            f'https://www.pnas.org/doi/pdf/{doi}?download=true',
            f'https://www.pnas.org/doi/pdfdirect/{doi}',
        ]
    
    # MDPI
    if '10.3390/' in doi:
        urls += [
            f'https://mdpi.com/{doi}/pdf?version=1',
            f'https://www.mdpi.com/{doi}/pdf',
        ]
    
    # Springer
    if '10.1007/' in doi:
        urls += [
            f'https://link.springer.com/content/pdf/{doi}.pdf',
            f'https://link.springer.com/content/pdf/{doi}',
        ]
    
    # Elsevier/ScienceDirect
    if '10.1016/' in doi:
        pii = doi.split('/')[-1]
        urls += [
            f'https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?md5=xxx&pid=1-s2.0-{pii}-main.pdf',
        ]
    
    # IOP
    if '10.1088/' in doi:
        urls += [
            f'https://iopscience.iop.org/article/{doi}/pdf',
        ]
    
    # BMJ
    if '10.1136/' in doi:
        urls += [
            f'https://www.bmj.com/content/bmj/doi/{doi}.full.pdf',
        ]
    
    # OUP
    if '10.1093/' in doi:
        urls += [
            f'https://academic.oup.com/view-large/{doi}',
        ]
    
    # Frontiers
    if '10.3389/' in doi:
        urls += [
            f'https://www.frontiersin.org/articles/{doi}/pdf',
        ]
    
    # Elsevier via API
    if '10.1016/' in doi or '10.1186/' in doi:
        urls += [
            f'https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf',
        ]
    
    # General: DOI.org → use Accept header for PDF
    urls.append(f'https://doi.org/{doi}')
    
    for url in urls:
        size = stream_download(url, filepath, timeout=25, accept='application/pdf')
        if size:
            return f'direct:{size//1024}KB'
    
    return None

# Load progress
progress = {}
if os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE) as f:
        progress = json.load(f)

failed_dois = set(progress.get('failed', []))
succeeded_dois = set(progress.get('succeeded', []))

# Load papers
with open(PUBMED_FILE) as f:
    papers = json.load(f)

target = [(i, p) for i, p in enumerate(papers) if 
          'affiliation' in p.get('source', []) and 
          'innohk_acknowledgement' in p.get('source', []) and
          p.get('doi')]

# Only try the ones that failed before
retry = [(i, p) for i, p in target if p.get('doi', '') in failed_dois and p.get('doi', '') not in succeeded_dois]

print(f"Retrying {len(retry)} previously failed papers", flush=True)

downloaded = 0
failed = 0

for idx, (orig_i, p) in enumerate(retry):
    result = download_one(p)
    
    if result == 'exists':
        succeeded_dois.add(p['doi'])
        failed_dois.discard(p['doi'])
    elif result:
        downloaded += 1
        succeeded_dois.add(p['doi'])
        failed_dois.discard(p['doi'])
        progress['succeeded'] = list(succeeded_dois)
        progress['failed'] = list(failed_dois)
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(progress, f)
        print(f"  ✅ [{downloaded}] {p['title'][:55]} ({result})", flush=True)
    else:
        failed += 1
        if failed <= 10 or failed % 15 == 0:
            print(f"  ❌ {p['title'][:50]}", flush=True)
    
    gc.collect()
    time.sleep(0.2)
    if (idx + 1) % 25 == 0:
        print(f"  💾 Retry progress: {idx+1}/{len(retry)} — {downloaded} ok, {failed} fail", flush=True)

# Save final
progress['succeeded'] = list(succeeded_dois)
progress['failed'] = list(failed_dois)
with open(PROGRESS_FILE, 'w') as f:
    json.dump(progress, f)

# Final summary
print(f"\n{'='*60}", flush=True)
print(f"FINAL RESULT", flush=True)
print(f"{'='*60}", flush=True)

total_pdfs = 0
total_size = 0
for root, dirs, files in os.walk(PDF_DIR):
    for f in files:
        if f.endswith('.pdf'):
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            total_pdfs += 1
            total_size += sz

print(f"Retried: {len(retry)}", flush=True)
print(f"Newly downloaded: {downloaded}", flush=True)
print(f"Still failed: {failed}", flush=True)
print(f"Total PDFs: {total_pdfs}", flush=True)
print(f"Total size: {total_size//1024//1024} MB", flush=True)
