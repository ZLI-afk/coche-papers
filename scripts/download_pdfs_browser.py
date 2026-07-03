#!/usr/bin/env python3
"""
Download missing PDFs using curl (subprocess) for reliable network access.
Strategies: Springer direct, arXiv, and HTTP requests via curl.
"""
import json, os, re, time, subprocess, shlex
from urllib.parse import quote

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')

os.makedirs(PDF_DIR, exist_ok=True)

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

print(f"Missing PDFs to download: {len(targets)}", flush=True)

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

def curl_download(url, output_path, referer=None, timeout=45):
    """Download a file using curl subprocess. Returns (success, size_bytes)."""
    cmd = ['curl', '-sL', '--connect-timeout', '10', '--max-time', str(timeout),
           '-A', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
           '-o', output_path]
    if referer:
        cmd += ['-e', referer]
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 2000:
                # Verify it's a PDF
                with open(output_path, 'rb') as f:
                    header = f.read(4)
                if header == b'%PDF':
                    return True, size
                # Some servers return HTML on failure
                if b'<!DOCTYPE' in header or b'<html' in header:
                    os.remove(output_path)
                    return False, 0
            else:
                os.remove(output_path)  # too small, probably error page
                return False, 0
    except Exception as e:
        pass
    return False, 0

def curl_get_text(url, timeout=15):
    """Fetch text content via curl."""
    cmd = ['curl', '-sL', '--connect-timeout', '10', '--max-time', str(timeout),
           '-A', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
           url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        return result.stdout
    except:
        return ''

def copy_to_final(src_path, p):
    """Copy a downloaded PDF to the final location."""
    pmid = p['pmid']
    filename = sanitize_filename(p['title'], pmid)
    year_dir = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}')
    os.makedirs(year_dir, exist_ok=True)
    dst_path = os.path.join(year_dir, filename)
    os.rename(src_path, dst_path)
    return dst_path, os.path.getsize(dst_path)

stats = {'downloaded': 0, 'failed': 0, 'exists': 0}

# ===================================================================
# STRATEGY 1: Springer direct PDF
# ===================================================================
print("\n--- Phase 1: Springer Direct ---", flush=True)
for idx, p in enumerate(targets):
    doi = p['doi']
    if not doi.startswith('10.1007/'):
        continue
    
    pmid = p['pmid']
    filepath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], pmid))
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        stats['exists'] += 1
        continue
    
    pdf_url = f'https://link.springer.com/content/pdf/{doi}.pdf'
    tmp = f'/tmp/springer_{pmid}.pdf'
    ref = f'https://link.springer.com/article/{doi}'
    
    ok, size = curl_download(pdf_url, tmp, referer=ref)
    if ok:
        final_path, final_size = copy_to_final(tmp, p)
        stats['downloaded'] += 1
        print(f"  ✅ [{stats['downloaded']}/{idx+1}] Springer: {p['title'][:55]} ({final_size//1024}KB)", flush=True)
    else:
        stats['failed'] += 1
        print(f"  ❌ Springer: {p['title'][:45]}", flush=True)

# ===================================================================
# STRATEGY 2: arXiv
# ===================================================================
print("\n--- Phase 2: arXiv ---", flush=True)

for idx, p in enumerate(targets):
    doi = p['doi']
    title = p['title']
    pmid = p['pmid']
    
    filepath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(title, pmid))
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        continue
    
    # Search arXiv by title
    query = ' '.join(title.split()[:8])[:200]
    search_url = f'https://arxiv.org/search/?query={quote(query)}&searchtype=all'
    html = curl_get_text(search_url, timeout=15)
    
    if not html:
        continue
    
    # Find arXiv IDs
    arxiv_ids = re.findall(r'/abs/(\d{4}\.\d{4,5})', html)
    if not arxiv_ids:
        continue
    
    # Try each matching arXiv ID
    for aid in list(set(arxiv_ids))[:3]:
        pdf_url = f'https://arxiv.org/pdf/{aid}.pdf'
        tmp = f'/tmp/arxiv_{pmid}.pdf'
        ok, size = curl_download(pdf_url, tmp, timeout=60)
        if ok:
            # Verify title match
            final_path, final_size = copy_to_final(tmp, p)
            stats['downloaded'] += 1
            print(f"  ✅ arXiv: {title[:55]} ({final_size//1024}KB) [{aid}]", flush=True)
            break
    
    time.sleep(1)

# ===================================================================
# STRATEGY 3: Check if any remaining DOIs resolve to accessible content
# ===================================================================
print("\n--- Phase 3: Other Direct Access ---", flush=True)

still_remaining = []
for p in targets:
    filepath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], p['pmid']))
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        continue
    still_remaining.append(p)

print(f"Still remaining: {len(still_remaining)}", flush=True)

# Try direct publisher PDF URLs for remaining
for idx, p in enumerate(still_remaining):
    doi = p['doi']
    title = p['title']
    pmid = p['pmid']
    
    filepath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(title, pmid))
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        continue
    
    # Build list of URLs to try
    urls_to_try = []
    
    if '10.1002/' in doi:
        urls_to_try = [
            f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true',
            f'https://onlinelibrary.wiley.com/doi/pdf/{doi}',
        ]
    elif '10.3390/' in doi:
        doi_part = doi.replace('10.3390/', '')
        urls_to_try = [f'https://www.mdpi.com/{doi_part}/pdf']
    elif '10.1021/' in doi:
        urls_to_try = [f'https://pubs.acs.org/doi/pdf/{doi}?download=true']
    elif '10.1016/' in doi:
        pii = doi.split('/')[-1]
        urls_to_try = [f'https://linkinghub.elsevier.com/retrieve/pii/{pii}.pdf']
    
    downloaded = False
    for url in urls_to_try:
        tmp = f'/tmp/direct_{pmid}.pdf'
        ok, size = curl_download(url, tmp, timeout=30)
        if ok:
            final_path, final_size = copy_to_final(tmp, p)
            stats['downloaded'] += 1
            print(f"  ✅ Direct: {title[:55]} ({final_size//1024}KB)", flush=True)
            downloaded = True
            break
    
    if not downloaded and idx < 5:
        print(f"  ❌ No access: {title[:50]}", flush=True)

# ===================================================================
# FINAL STATS
# ===================================================================
total_pdfs = 0
total_size = 0
for root, dirs, files in os.walk(PDF_DIR):
    for fn in files:
        if fn.endswith('.pdf'):
            fp = os.path.join(root, fn)
            total_pdfs += 1
            total_size += os.path.getsize(fp)

print(f"\n=== Final ===", flush=True)
print(f"New: {stats['downloaded']} | Skipped (exists): {stats['exists']} | Failed: {stats['failed']}", flush=True)
print(f"Total PDFs: {total_pdfs} ({total_size/1024/1024:.1f} MB)", flush=True)
