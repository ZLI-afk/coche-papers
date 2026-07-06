#!/usr/bin/env python3
"""
Download PDFs for InnoHK dual-channel papers — v4.
Strategies (tried in order):
  1. Unpaywall API → OA PDF
  2. Direct publisher URL patterns (no EZproxy)
  3. arXiv API → PDF
Uses short timeouts, no EZproxy, robust streaming.
"""
import json, requests, re, time, os, gc

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')
PROGRESS_FILE = os.path.join(WORKSPACE, 'pdf_download_progress.json')

os.makedirs(PDF_DIR, exist_ok=True)

headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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

def stream_download(url, filepath, timeout=30):
    """Stream download a URL to filepath. Returns size on success, 0 on failure."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, 
                          allow_redirects=True, stream=True)
        if resp.status_code == 200:
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
    except requests.exceptions.Timeout:
        return 0
    except requests.exceptions.ConnectionError:
        return 0
    except Exception:
        return 0
    return 0

def download_from_unpaywall(doi, filepath):
    """Try Unpaywall API for OA PDF."""
    try:
        resp = requests.get(f'https://api.unpaywall.org/v2/{doi}?email=coche@cityu.edu.hk', 
                          timeout=10)
        up = resp.json()
        oa = up.get('best_oa_location', {})
        if oa and oa.get('url_for_pdf'):
            size = stream_download(oa['url_for_pdf'], filepath, timeout=30)
            if size:
                return f'oa:{size//1024}KB'
    except:
        pass
    return None

def download_from_arxiv(p, filepath):
    """Try arXiv API/PDF for arXiv papers."""
    arxiv_id = p.get('arxiv_id') or p.get('arxiv', '')
    doi = p.get('doi', '')
    
    # Check if it's likely an arXiv paper from the DOI
    if not arxiv_id:
        # Try to extract arXiv ID from DOI or notes
        pass
    
    if not arxiv_id:
        return None
    
    # Remove version suffix if present
    arxiv_id = re.sub(r'v\d+$', '', arxiv_id.strip())
    
    urls = [
        f'https://arxiv.org/pdf/{arxiv_id}.pdf',
        f'https://arxiv.org/pdf/{arxiv_id}',
    ]
    
    for url in urls:
        size = stream_download(url, filepath, timeout=45)
        if size:
            return f'arxiv:{size//1024}KB'
    return None

def download_direct_publisher(doi, p, filepath):
    """Try direct publisher URL patterns."""
    urls = []
    
    # ACS
    if '10.1021/' in doi:
        urls.append(f'https://pubs.acs.org/doi/pdf/{doi}?download=true')
    
    # RSC
    if '10.1039/' in doi or '10.1038/' in doi:
        urls.append(f'https://pubs.rsc.org/en/content/articlepdf/{p.get("pub_year","2024")}/{doi}')
    
    # Wiley
    if '10.1002/' in doi:
        urls.append(f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true')
    
    # Science/AAAS
    if '10.1126/' in doi:
        urls.append(f'https://www.science.org/doi/pdf/{doi}?download=true')
    
    # Springer
    if '10.1007/' in doi:
        urls.append(f'https://link.springer.com/content/pdf/{doi}.pdf')
    
    # Elsevier
    if '10.1016/' in doi or '10.1186/' in doi or '10.3390/' in doi:
        urls.append(f'https://linkinghub.elsevier.com/retrieve/pii/{doi}/pdf')
    
    # Nature
    if '10.1038/' in doi:
        urls.append(f'https://www.nature.com/articles/{doi.split("/")[-1]}.pdf')
    
    # PNAS
    if '10.1073/' in doi:
        urls.append(f'https://www.pnas.org/doi/pdf/{doi}?download=true')
    
    # AIP/APL
    if '10.1063/' in doi:
        urls.append(f'https://pubs.aip.org/aip/article-pdf/{doi}')
    
    # IOP
    if '10.1088/' in doi:
        urls.append(f'https://iopscience.iop.org/article/{doi}/pdf')
    
    # IEEE
    if '10.1109/' in doi:
        urls.append(f'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={doi}')
    
    # BMJ
    if '10.1136/' in doi:
        urls.append(f'https://www.bmj.com/content/bmj/doi/{doi}.full.pdf')
    
    # BMC
    if '10.1186/' in doi:
        urls.append(f'https://link.springer.com/content/pdf/{doi}.pdf')
    
    # MDPI
    if '10.3390/' in doi:
        urls.append(f'https://mdpi.com/{doi}/pdf?version=1')
    
    # Frontiers
    if '10.3389/' in doi:
        urls.append(f'https://www.frontiersin.org/articles/{doi}/pdf')
    
    # OUP
    if '10.1093/' in doi:
        urls.append(f'https://academic.oup.com/view-large/{doi}')
    
    # General DOI → PDF redirect
    urls.append(f'https://doi.org/{doi}')
    
    for url in urls:
        size = stream_download(url, filepath, timeout=30)
        if size:
            return f'direct:{size//1024}KB'
    
    return None

def load_progress():
    """Load previously attempted DOIs to skip."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {'succeeded': [], 'failed': []}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

# Load papers
with open(PUBMED_FILE) as f:
    papers = json.load(f)

target = [(i, p) for i, p in enumerate(papers) if 
          'affiliation' in p.get('source', []) and 
          'innohk_acknowledgement' in p.get('source', []) and
          p.get('doi')]

print(f"Target papers: {len(target)}", flush=True)

# Load existing progress
progress = load_progress()
previously_succeeded = set(progress.get('succeeded', []))
previously_failed = set(progress.get('failed', []))

# Count already downloaded
already_downloaded = 0
for i, p in target:
    doi = p.get('doi', '')
    filename = sanitize_filename(p['title'], p.get('pmid', ''))
    itc_year = get_itc_year(p)
    filepath = os.path.join(PDF_DIR, f'ITC_{itc_year}', filename)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        already_downloaded += 1

print(f"Already downloaded: {already_downloaded}", flush=True)

downloaded = 0
failed = 0
skipped = 0

for idx, (orig_i, p) in enumerate(target):
    doi = p.get('doi', '')
    pmid = p.get('pmid', '')
    
    # Check if already succeeded
    if doi in previously_succeeded:
        skipped += 1
        continue
    
    # Check if already downloaded to disk
    filename = sanitize_filename(p['title'], pmid)
    itc_year = get_itc_year(p)
    year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
    os.makedirs(year_dir, exist_ok=True)
    filepath = os.path.join(year_dir, filename)
    
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        if doi not in previously_succeeded:
            previously_succeeded.add(doi)
            progress['succeeded'] = list(previously_succeeded)
        skipped += 1
        continue
    
    result = None
    
    # Strategy 1: Unpaywall
    result = download_from_unpaywall(doi, filepath)
    if result:
        downloaded += 1
        previously_succeeded.add(doi)
        progress['succeeded'] = list(previously_succeeded)
        save_progress(progress)
        print(f"  ✅ [{downloaded}] {p['title'][:55]} ({result}) unpaywall", flush=True)
        gc.collect()
        time.sleep(0.3)
        continue
    
    # Strategy 2: Direct publisher URL
    result = download_direct_publisher(doi, p, filepath)
    if result:
        downloaded += 1
        previously_succeeded.add(doi)
        progress['succeeded'] = list(previously_succeeded)
        save_progress(progress)
        print(f"  ✅ [{downloaded}] {p['title'][:55]} ({result}) direct", flush=True)
        gc.collect()
        time.sleep(0.3)
        continue
    
    # Strategy 3: arXiv
    result = download_from_arxiv(p, filepath)
    if result:
        downloaded += 1
        previously_succeeded.add(doi)
        progress['succeeded'] = list(previously_succeeded)
        save_progress(progress)
        print(f"  ✅ [{downloaded}] {p['title'][:55]} ({result}) arxiv", flush=True)
        gc.collect()
        time.sleep(0.3)
        continue
    
    # Failed
    failed += 1
    previously_failed.add(doi)
    progress['failed'] = list(previously_failed)
    save_progress(progress)
    if failed <= 10 or failed % 20 == 0:
        print(f"  ❌ {p['title'][:55]} (doi: {doi[:40]})", flush=True)
    
    gc.collect()
    time.sleep(0.2)
    
    if (idx + 1) % 20 == 0:
        print(f"  💾 Progress: {idx+1}/{len(target)} — {downloaded} ok, {skipped} skip, {failed} fail", flush=True)
        save_progress(progress)

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

print(f"Total target: {len(target)}", flush=True)
print(f"Already had: {already_downloaded}", flush=True)
print(f"Newly downloaded: {downloaded}", flush=True)
print(f"Still failed: {failed}", flush=True)
print(f"Total PDFs on disk: {total_pdfs}", flush=True)
print(f"Total size: {total_size//1024//1024} MB ({total_size//1024} KB)", flush=True)

save_progress(progress)
print(f"\nProgress saved to {PROGRESS_FILE}", flush=True)
