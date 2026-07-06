#!/usr/bin/env python3
"""Phase 7: Use Semantic Scholar API + PMC to find OA versions."""
import requests, json, re, time, os, gc, subprocess

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')

os.makedirs(PDF_DIR, exist_ok=True)

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

def curl_download(url, output_path, timeout=45):
    cmd = ['curl', '-sL', '--connect-timeout', '10', '--max-time', str(timeout),
           '-A', 'Mozilla/5.0', '-o', output_path, url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 2000:
                with open(output_path, 'rb') as f:
                    header = f.read(4)
                if header == b'%PDF':
                    return True, size
            os.remove(output_path)
            return False, 0
    except:
        if os.path.exists(output_path):
            os.remove(output_path)
    return False, 0

# Load papers
with open(PUBMED_FILE) as f:
    papers = json.load(f)

target = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[]) and p.get('doi')]

# Find ones not on disk
missing = []
for p in target:
    fpath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], p.get('pmid','')))
    if not (os.path.exists(fpath) and os.path.getsize(fpath) > 2000):
        missing.append(p)

print(f"Still missing: {len(missing)}", flush=True)
headers = {'User-Agent': 'Mozilla/5.0'}

downloaded = 0

for idx, p in enumerate(missing):
    doi = p['doi']
    pmid = p['pmid']
    title = p['title']
    
    fpath = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(title, pmid))
    
    # Strategy 1: Semantic Scholar API for OA PDF
    try:
        ss = requests.get(f'https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf,externalIds', 
                         timeout=10, headers=headers).json()
        
        # Check for OA PDF
        oa = ss.get('openAccessPdf')
        if oa and oa.get('url'):
            tmp = f'/tmp/ss_{pmid}.pdf'
            ok, size = curl_download(oa['url'], tmp, timeout=45)
            if ok:
                year_dir = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}')
                os.makedirs(year_dir, exist_ok=True)
                os.rename(tmp, fpath)
                downloaded += 1
                print(f"  ✅ [{downloaded}] SS: {title[:55]} ({size//1024}KB)", flush=True)
                gc.collect()
                time.sleep(0.3)
                continue
        
        # Check for arXiv ID from Semantic Scholar
        arxiv_id = ss.get('externalIds', {}).get('ArXiv')
        if arxiv_id:
            tmp = f'/tmp/arxiv_ss_{pmid}.pdf'
            ok, size = curl_download(f'https://arxiv.org/pdf/{arxiv_id}.pdf', tmp, timeout=45)
            if ok:
                year_dir = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}')
                os.makedirs(year_dir, exist_ok=True)
                os.rename(tmp, fpath)
                downloaded += 1
                print(f"  ✅ [{downloaded}] ArXiv(S2): {title[:55]} ({size//1024}KB)", flush=True)
                gc.collect()
                time.sleep(0.3)
                continue
        
        # Check for PubMedCentral ID
        pmcid = ss.get('externalIds', {}).get('PubMedCentral')
        if pmcid:
            tmp = f'/tmp/pmc_{pmid}.pdf'
            ok, size = curl_download(f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/', tmp, timeout=45)
            if ok:
                year_dir = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}')
                os.makedirs(year_dir, exist_ok=True)
                os.rename(tmp, fpath)
                downloaded += 1
                print(f"  ✅ [{downloaded}] PMC: {title[:55]} ({size//1024}KB)", flush=True)
                gc.collect()
                time.sleep(0.3)
                continue
        
    except Exception as e:
        pass
    
    # Progress
    gc.collect()
    time.sleep(0.2)
    
    if (idx + 1) % 15 == 0:
        print(f"  💾 SS search: {idx+1}/{len(missing)} — {downloaded} found so far", flush=True)

# Final summary
print(f"\n{'='*60}", flush=True)
total_pdfs = 0
total_size = 0
for root, dirs, files in os.walk(PDF_DIR):
    for f in files:
        if f.endswith('.pdf'):
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            total_pdfs += 1
            total_size += sz

print(f"Newly downloaded via Semantic Scholar: {downloaded}", flush=True)
print(f"Total PDFs: {total_pdfs}", flush=True)
print(f"Total size: {total_size//1024//1024} MB", flush=True)
