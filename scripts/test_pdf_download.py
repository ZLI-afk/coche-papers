#!/usr/bin/env python3
"""Test PDF download with first 5 InnoHK papers."""
import json, requests, re, os
from urllib.parse import urljoin

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
TEST_DIR = os.path.join(WORKSPACE, 'pdfs', 'test')
os.makedirs(TEST_DIR, exist_ok=True)

with open(PUBMED_FILE) as f:
    papers = json.load(f)

target = [(i, p) for i, p in enumerate(papers) if 
          'affiliation' in p.get('source', []) and 
          'innohk_acknowledgement' in p.get('source', []) and
          p.get('doi')]

print(f"Testing with first 5 of {len(target)} InnoHK papers", flush=True)

cookies = {
    'ezproxy': 'e1~Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyl': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
    'ezproxyn': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
}
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': 'text/html,application/pdf,*/*',
}

for idx, (orig_i, p) in enumerate(target[:5]):
    doi = p.get('doi', '')
    print(f"\n[{idx+1}] {p['title'][:60]}", flush=True)
    print(f"    DOI: {doi}", flush=True)
    
    doi_url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    
    try:
        resp = requests.get(doi_url, headers=headers, cookies=cookies, timeout=20, allow_redirects=True)
        html = resp.text
        final_url = resp.url
        print(f"    → {final_url[:80]}", flush=True)
        print(f"    Content-Type: {resp.headers.get('content-type', 'N/A')[:50]}", flush=True)
        print(f"    Size: {len(html)} bytes", flush=True)
        
        if 'application/pdf' in resp.headers.get('content-type', ''):
            filename = f"test_{idx+1}.pdf"
            filepath = os.path.join(TEST_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(resp.content)
            print(f"    ✅ PDF downloaded: {os.path.getsize(filepath)//1024}KB", flush=True)
            continue
        
        # Look for PDF links
        pdf_patterns = [
            r'href="([^"]*\.pdf[^"]*)"',
            r'<meta[^>]*citation_pdf_url[^>]*content="([^"]*)"',
            r'data-url="([^"]*\.pdf[^"]*)"',
        ]
        pdf_url = None
        for pat in pdf_patterns:
            matches = re.findall(pat, html, re.IGNORECASE)
            for m in matches[:5]:
                if m and 'supplementary' not in m.lower():
                    pdf_url = urljoin(final_url, m)
                    print(f"    PDF link: {pdf_url[:100]}", flush=True)
                    break
            if pdf_url:
                break
        
        if pdf_url:
            if 'eproxy.lib.hku.hk' not in pdf_url:
                pdf_url = f'https://eproxy.lib.hku.hk/login?url={pdf_url}'
            pdf_resp = requests.get(pdf_url, headers=headers, cookies=cookies, timeout=30, allow_redirects=True, stream=True)
            ct = pdf_resp.headers.get('content-type', '')
            print(f"    PDF response: {ct[:60]}, size: {len(pdf_resp.content)} bytes", flush=True)
            if 'application/pdf' in ct or pdf_resp.content[:4] == b'%PDF':
                filename = f"test_{idx+1}.pdf"
                filepath = os.path.join(TEST_DIR, filename)
                with open(filepath, 'wb') as f:
                    f.write(pdf_resp.content)
                print(f"    ✅ PDF downloaded: {os.path.getsize(filepath)//1024}KB", flush=True)
            else:
                print(f"    ❌ Not a PDF", flush=True)
        else:
            print(f"    ❌ No PDF link found", flush=True)
            
    except Exception as e:
        print(f"    ❌ Error: {e}", flush=True)
