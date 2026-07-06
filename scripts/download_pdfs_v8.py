#!/usr/bin/env python3
"""
Phase 8: Full curl-based download for ALL remaining papers.
Uses: Unpaywall, PMC central, Semantic Scholar → arXiv, and 
direct publisher access via curl.
"""
import json, re, time, os, gc, subprocess
from urllib.parse import quote

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')

os.makedirs(PDF_DIR, exist_ok=True)
headers_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

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

def curl_pdf(url, out_path, referer=None, timeout=60):
    """Download PDF via curl. Returns (success, size)."""
    cmd = ['curl', '-sL', '--connect-timeout', '12', '--max-time', str(timeout),
           '-A', headers_agent, '-o', out_path]
    if referer:
        cmd += ['-e', referer]
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        if os.path.exists(out_path):
            size = os.path.getsize(out_path)
            if size > 2000:
                with open(out_path, 'rb') as f:
                    magic = f.read(4)
                if magic == b'%PDF':
                    return True, size
                if b'<!DOCTYPE' in magic or b'<html' in magic:
                    os.remove(out_path)
                    return False, 0
            os.remove(out_path)
            return False, 0
    except:
        if os.path.exists(out_path):
            os.remove(out_path)
    return False, 0

def curl_get(url, timeout=15):
    cmd = ['curl', '-sL', '--connect-timeout', '10', '--max-time', str(timeout),
           '-A', headers_agent, url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        return result.stdout
    except:
        return ''

def copy_pdf(src, p):
    year_dir = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}')
    os.makedirs(year_dir, exist_ok=True)
    dst = os.path.join(year_dir, sanitize_filename(p['title'], p['pmid']))
    if os.path.exists(dst) and os.path.getsize(dst) > 2000:
        os.remove(src)
        return None, 0
    os.rename(src, dst)
    return dst, os.path.getsize(dst)

# Load papers
with open(PUBMED_FILE) as f:
    papers = json.load(f)

target = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[]) and p.get('doi')]

# Find missing
missing = []
for p in target:
    fp = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], p.get('pmid','')))
    if not (os.path.exists(fp) and os.path.getsize(fp) > 2000):
        missing.append(p)

print(f"Still missing: {len(missing)}", flush=True)
downloaded = 0

# Strategy 1: Semantic Scholar → arXiv + PMC
print("\n--- Phase 8a: Semantic Scholar → arXiv/PMC ---", flush=True)
for idx, p in enumerate(missing):
    doi = p['doi']
    pmid = p['pmid']
    fp = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], pmid))
    if os.path.exists(fp) and os.path.getsize(fp) > 2000:
        continue
    
    try:
        ss_url = f'https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=externalIds'
        ss_raw = curl_get(ss_url, 10)
        if not ss_raw:
            continue
        ss = json.loads(ss_raw)
        ext = ss.get('externalIds', {})
        
        # arXiv
        arxiv_id = ext.get('ArXiv')
        if arxiv_id:
            tmp = f'/tmp/arxiv8_{pmid}.pdf'
            ok, size = curl_pdf(f'https://arxiv.org/pdf/{arxiv_id}.pdf', tmp, timeout=60)
            if ok:
                cp = copy_pdf(tmp, p)
                if cp[0]:
                    downloaded += 1
                    print(f"  ✅ [{downloaded}] arXiv: {p['title'][:55]} ({size//1024}KB)", flush=True)
                    continue
        
        # PMC
        pmcid = ext.get('PubMedCentral')
        if pmcid:
            tmp = f'/tmp/pmc8_{pmid}.pdf'
            ok, size = curl_pdf(f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/', tmp, timeout=60)
            if ok:
                cp = copy_pdf(tmp, p)
                if cp[0]:
                    downloaded += 1
                    print(f"  ✅ [{downloaded}] PMC: {p['title'][:55]} ({size//1024}KB)", flush=True)
                    continue
    except:
        pass
    
    gc.collect()
    time.sleep(0.15)
    if (idx+1) % 20 == 0:
        print(f"  💾 S2: {idx+1}/{len(missing)} — {downloaded} found", flush=True)

# Strategy 2: Unpaywall (more thorough)
print("\n--- Phase 8b: Unpaywall re-check ---", flush=True)
for idx, p in enumerate(missing):
    doi = p['doi']
    pmid = p['pmid']
    fp = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], pmid))
    if os.path.exists(fp) and os.path.getsize(fp) > 2000:
        continue
    
    try:
        up_raw = curl_get(f'https://api.unpaywall.org/v2/{doi}?email=coche@cityu.edu.hk', 10)
        if not up_raw:
            continue
        up = json.loads(up_raw)
        oa = up.get('best_oa_location', {})
        if oa and oa.get('url_for_pdf'):
            tmp = f'/tmp/up8_{pmid}.pdf'
            ok, size = curl_pdf(oa['url_for_pdf'], tmp, timeout=60)
            if ok:
                cp = copy_pdf(tmp, p)
                if cp[0]:
                    downloaded += 1
                    print(f"  ✅ [{downloaded}] OA: {p['title'][:55]} ({size//1024}KB)", flush=True)
                    continue
    except:
        pass
    
    gc.collect()
    time.sleep(0.1)

# Strategy 3: Direct publisher links via curl
print("\n--- Phase 8c: Direct Publisher ---", flush=True)
for idx, p in enumerate(missing):
    doi = p['doi']
    pmid = p['pmid']
    title = p['title']
    fp = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(title, pmid))
    if os.path.exists(fp) and os.path.getsize(fp) > 2000:
        continue
    
    urls = []
    doi_article = doi.split('/')[-1]
    
    if '10.1002/' in doi:
        urls = [
            (f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true', f'https://onlinelibrary.wiley.com/doi/{doi}'),
            (f'https://onlinelibrary.wiley.com/doi/pdf/{doi}', None),
        ]
    elif '10.1126/' in doi:
        urls = [
            (f'https://www.science.org/doi/pdf/{doi}?download=true', f'https://www.science.org/doi/{doi}'),
            (f'https://www.science.org/doi/epdf/{doi}', None),
        ]
    elif '10.1021/' in doi:
        urls = [
            (f'https://pubs.acs.org/doi/pdf/{doi}?download=true', f'https://pubs.acs.org/doi/{doi}'),
            (f'https://pubs.acs.org/doi/pdf/{doi}', None),
        ]
    elif '10.1039/' in doi:
        urls = [
            (f'https://pubs.rsc.org/en/content/articlepdf/{p.get("pub_year","2024")}/{doi}', f'https://pubs.rsc.org/en/content/articlelanding/{doi}'),
        ]
    elif '10.1038/' in doi:
        urls = [
            (f'https://www.nature.com/articles/{doi_article}.pdf', f'https://www.nature.com/articles/{doi_article}'),
        ]
    elif '10.1073/' in doi:
        urls = [
            (f'https://www.pnas.org/doi/pdf/{doi}?download=true', f'https://www.pnas.org/doi/{doi}'),
        ]
    elif '10.3390/' in doi:
        doi_part = doi.replace('10.3390/', '')
        urls = [
            (f'https://www.mdpi.com/{doi_part}/pdf', None),
            (f'https://mdpi.com/{doi_part}/pdf?version=1', None),
        ]
    elif '10.1093/' in doi:
        urls = [
            (f'https://academic.oup.com/view-large/{doi}', None),
        ]
    elif '10.1007/' in doi:
        urls = [
            (f'https://link.springer.com/content/pdf/{doi}.pdf', f'https://link.springer.com/article/{doi}'),
            (f'https://link.springer.com/content/pdf/{doi}', None),
        ]
    elif '10.1016/' in doi:
        urls = [
            (f'https://linkinghub.elsevier.com/retrieve/pii/{doi_article}/pdf', None),
        ]
    elif '10.1088/' in doi:
        urls = [
            (f'https://iopscience.iop.org/article/{doi}/pdf', None),
        ]
    elif '10.1136/' in doi:
        urls = [
            (f'https://www.bmj.com/content/bmj/doi/{doi}.full.pdf', None),
        ]
    elif '10.3389/' in doi:
        urls = [
            (f'https://www.frontiersin.org/articles/{doi}/pdf', None),
        ]
    elif '10.1186/' in doi:
        urls = [
            (f'https://link.springer.com/content/pdf/{doi}.pdf', None),
        ]
    
    for url, ref in urls:
        tmp = f'/tmp/direct8_{pmid}.pdf'
        ok, size = curl_pdf(url, tmp, referer=ref, timeout=50)
        if ok:
            cp = copy_pdf(tmp, p)
            if cp[0]:
                downloaded += 1
                print(f"  ✅ [{downloaded}] Direct: {title[:55]} ({size//1024}KB)", flush=True)
                break
    
    gc.collect()
    time.sleep(0.1)
    if (idx+1) % 25 == 0:
        print(f"  💾 Direct: {idx+1}/{len(missing)} — {downloaded} found", flush=True)

# Final
total_pdfs = 0
total_size = 0
for root, dirs, files in os.walk(PDF_DIR):
    for f in files:
        if f.endswith('.pdf'):
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            total_pdfs += 1
            total_size += sz

remaining = 0
for p in target:
    fp = os.path.join(PDF_DIR, f'ITC_{get_itc_year(p)}', sanitize_filename(p['title'], p.get('pmid','')))
    if not (os.path.exists(fp) and os.path.getsize(fp) > 2000):
        remaining += 1

print(f"\n{'='*60}", flush=True)
print(f"Phase 8 Complete", flush=True)
print(f"Newly downloaded: {downloaded}", flush=True)
print(f"Total PDFs: {total_pdfs}", flush=True)
print(f"Total size: {total_size//1024//1024} MB", flush=True)
print(f"Still remaining: {remaining}", flush=True)
