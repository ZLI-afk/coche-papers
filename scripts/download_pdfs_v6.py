#!/usr/bin/env python3
"""Phase 6: arXiv search for failed papers, then Springer, then direct DOI."""
import subprocess, json, re, time, os, gc
from urllib.parse import quote

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')
PROGRESS_FILE = os.path.join(WORKSPACE, 'pdf_download_progress.json')

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

def curl_download(url, output_path, referer=None, timeout=45):
    cmd = ['curl', '-sL', '--connect-timeout', '10', '--max-time', str(timeout),
           '-A', 'Mozilla/5.0', '-o', output_path]
    if referer:
        cmd += ['-e', referer]
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 2000:
                with open(output_path, 'rb') as f:
                    header = f.read(4)
                if header == b'%PDF':
                    return True, size
                if b'<!DOCTYPE' in header or b'<html' in header:
                    os.remove(output_path)
                    return False, 0
            else:
                os.remove(output_path)
                return False, 0
    except:
        pass
    return False, 0

def curl_get_text(url, timeout=15):
    cmd = ['curl', '-sL', '--connect-timeout', '10', '--max-time', str(timeout),
           '-A', 'Mozilla/5.0', url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        return result.stdout
    except:
        return ''

def copy_to_final(src_path, p):
    pmid = p['pmid']
    filename = sanitize_filename(p['title'], pmid)
    year_dir = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}')
    os.makedirs(year_dir, exist_ok=True)
    dst_path = os.path.join(year_dir, filename)
    if os.path.exists(dst_path) and os.path.getsize(dst_path) > 2000:
        os.remove(src_path)
        return None, 0
    os.rename(src_path, dst_path)
    return dst_path, os.path.getsize(dst_path)

# Load data
with open(PUBMED_FILE) as f:
    papers = json.load(f)

progress = {}
if os.path.exists(PROGRESS_FILE):
    with open(progress_file := PROGRESS_FILE) as f:
        progress = json.load(f)

failed_dois = set(progress.get('failed', []))
target = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[]) and p.get('doi','') in failed_dois]

print(f"Papers to retry: {len(target)}", flush=True)

stats = {'downloaded': 0, 'failed': 0}

# Strategy 1: Springer Direct
print("\n--- Phase 6a: Springer Direct ---", flush=True)
for idx, p in enumerate(target):
    doi = p['doi']
    if '10.1007/' not in doi:
        continue
    
    pmid = p['pmid']
    tmp = f'/tmp/springer6_{pmid}.pdf'
    pdf_url = f'https://link.springer.com/content/pdf/{doi}.pdf'
    ref = f'https://link.springer.com/article/{doi}'
    
    ok, size = curl_download(pdf_url, tmp, referer=ref)
    if ok:
        final_path, final_size = copy_to_final(tmp, p)
        if final_path:
            stats['downloaded'] += 1
            print(f"  ✅ Springer: {p['title'][:55]} ({final_size//1024}KB)", flush=True)
    else:
        stats['failed'] += 1
        print(f"  ❌ Springer: {p['title'][:45]}", flush=True)

# Strategy 2: arXiv title search
print("\n--- Phase 6b: arXiv Title Search ---", flush=True)
for idx, p in enumerate(target):
    title = p['title']
    pmid = p['pmid']
    
    # Skip already downloaded
    fpath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(title, pmid))
    if os.path.exists(fpath) and os.path.getsize(fpath) > 2000:
        continue
    
    query = ' '.join(title.split()[:8])[:200]
    search_url = f'https://arxiv.org/search/?query={quote(query)}&searchtype=all'
    html = curl_get_text(search_url, timeout=15)
    
    if not html:
        continue
    
    arxiv_ids = list(set(re.findall(r'/abs/(\d{4}\.\d{4,5})', html)))
    if not arxiv_ids:
        continue
    
    for aid in arxiv_ids[:3]:
        pdf_url = f'https://arxiv.org/pdf/{aid}.pdf'
        tmp = f'/tmp/arxiv6_{pmid}.pdf'
        ok, size = curl_download(pdf_url, tmp, timeout=60)
        if ok:
            final_path, final_size = copy_to_final(tmp, p)
            if final_path:
                stats['downloaded'] += 1
                print(f"  ✅ arXiv: {title[:55]} ({final_size//1024}KB) [{aid}]", flush=True)
                break
    
    time.sleep(1.5)
    if (idx + 1) % 20 == 0:
        print(f"  💾 arXiv search: {idx+1}/{len(target)} — {stats['downloaded']} found so far", flush=True)

# Strategy 3: MDPI direct
print("\n--- Phase 6c: MDPI Direct ---", flush=True)
for idx, p in enumerate(target):
    doi = p['doi']
    if '10.3390/' not in doi:
        continue
    
    pmid = p['pmid']
    fpath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], pmid))
    if os.path.exists(fpath) and os.path.getsize(fpath) > 2000:
        continue
    
    doi_part = doi.replace('10.3390/', '')
    urls = [
        f'https://www.mdpi.com/{doi_part}/pdf',
        f'https://mdpi.com/{doi_part}/pdf?version=1',
    ]
    for url in urls:
        tmp = f'/tmp/mdpi6_{pmid}.pdf'
        ok, size = curl_download(url, tmp, timeout=30)
        if ok:
            final_path, final_size = copy_to_final(tmp, p)
            if final_path:
                stats['downloaded'] += 1
                print(f"  ✅ MDPI: {p['title'][:55]} ({final_size//1024}KB)", flush=True)
                break

# Strategy 4: Wiley via curl with different User-Agent
print("\n--- Phase 6d: Wiley Direct ---", flush=True)
for idx, p in enumerate(target):
    doi = p['doi']
    if '10.1002/' not in doi:
        continue
    
    pmid = p['pmid']
    fpath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], pmid))
    if os.path.exists(fpath) and os.path.getsize(fpath) > 2000:
        continue
    
    urls = [
        f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true',
        f'https://onlinelibrary.wiley.com/doi/pdf/{doi}',
    ]
    for url in urls:
        tmp = f'/tmp/wiley6_{pmid}.pdf'
        ok, size = curl_download(url, tmp, timeout=30)
        if ok:
            final_path, final_size = copy_to_final(tmp, p)
            if final_path:
                stats['downloaded'] += 1
                print(f"  ✅ Wiley: {p['title'][:55]} ({final_size//1024}KB)", flush=True)
                break

# Final count
total_pdfs = 0
total_size = 0
for root, dirs, files in os.walk(PDF_DIR):
    for f in files:
        if f.endswith('.pdf'):
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            total_pdfs += 1
            total_size += sz

print(f"\n{'='*60}", flush=True)
print(f"Phase 6 Complete", flush=True)
print(f"Newly downloaded: {stats['downloaded']}", flush=True)
print(f"Total PDFs: {total_pdfs}", flush=True)
print(f"Total size: {total_size//1024//1024} MB", flush=True)
