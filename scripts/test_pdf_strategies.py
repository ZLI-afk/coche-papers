#!/usr/bin/env python3
"""Test PDF download strategies per publisher."""
import json, requests, re, time, os
from urllib.parse import urljoin, unquote

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
TEST_DIR = os.path.join(WORKSPACE, 'pdfs', 'test2')
os.makedirs(TEST_DIR, exist_ok=True)

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
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': '*/*',
}

# Pick one paper per publisher
test_papers = {
    'Wiley': None,
    'ACS': None,
    'Science': None,
    'IEEE': None,
    'Springer': None,
    'Elsevier': None,
}

for _, p in target:
    doi = p.get('doi', '').lower()
    if not test_papers.get('Wiley') and '10.1002/' in doi:
        test_papers['Wiley'] = p
    elif not test_papers.get('ACS') and '10.1021/' in doi:
        test_papers['ACS'] = p
    elif not test_papers.get('Science') and '10.1126/' in doi:
        test_papers['Science'] = p
    elif not test_papers.get('IEEE') and '10.1109/' in doi:
        test_papers['IEEE'] = p
    elif not test_papers.get('Springer') and '10.1007/' in doi:
        test_papers['Springer'] = p
    elif not test_papers.get('Elsevier') and '10.1016/' in doi:
        test_papers['Elsevier'] = p

for pub, p in test_papers.items():
    if not p:
        continue
    doi = p.get('doi', '')
    print(f"\n{'='*60}")
    print(f"📚 {pub}: {p['title'][:70]}")
    print(f"   DOI: {doi}")
    
    doi_url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    
    try:
        resp = requests.get(doi_url, headers=headers, cookies=cookies, timeout=20, allow_redirects=True)
        html = resp.text
        final_url = resp.url
        print(f"   → {final_url[:100]}")
        
        # Strategy 1: citation_pdf_url meta tag
        m = re.search(r'citation_pdf_url["\'][^>]*content=["\']([^"\']+)', html, re.IGNORECASE)
        if m:
            pdf_url = m.group(1)
            print(f"   citation_pdf_url: {pdf_url[:100]}")
        
        # Strategy 2: Look for all PDF links
        pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.IGNORECASE)
        if pdf_links:
            print(f"   PDF links found: {len(pdf_links)}")
            for link in pdf_links[:5]:
                full = urljoin(final_url, link)
                print(f"     → {full[:120]}")
        
        # Strategy 3: Try publisher-specific direct PDF URLs
        direct_urls = []
        doi_part = doi.split('/')[-1] if '/' in doi else doi
        
        if 'wiley.com' in final_url:
            # Wiley: https://...doi/epdf/DOI or ...doi/pdf/DOI
            base = final_url.split('?')[0]
            direct_urls.append(f"{base}/epdf/{doi_part}")
            direct_urls.append(f"{base}/pdf/{doi_part}")
            # Also try the PDA strategy
            direct_urls.append(final_url.replace('/doi/', '/doi/pdf/'))
        elif 'acs.org' in final_url:
            # ACS: /doi/pdf/DOI
            base = final_url.split('?')[0].replace('/doi/abs/', '/doi/pdf/').replace('/doi/full/', '/doi/pdf/').replace('/doi/', '/doi/pdf/')
            direct_urls.append(base)
        elif 'science.org' in final_url:
            direct_urls.append(final_url.replace('/doi/', '/doi/pdf/'))
        elif 'ieee' in final_url:
            direct_urls.append(final_url.replace('/document/', '/stamp/stamp.jsp?arnumber=').split('?')[0] + '?file=pdf')
        elif 'springer' in final_url:
            direct_urls.append(final_url.replace('/article/', '/content/pdf/') + '.pdf')
        elif 'elsevier' in final_url:
            direct_urls.append(final_url.replace('/science/article/pii/', '/science/article/pii/') + '/pdf')
        
        for url in direct_urls[:3]:
            if 'eproxy.lib.hku.hk' not in url:
                pdf_ez = f'https://eproxy.lib.hku.hk/login?url={url}'
            else:
                pdf_ez = url
            
            try:
                pr = requests.get(pdf_ez, headers=headers, cookies=cookies, timeout=30, allow_redirects=True)
                ct = pr.headers.get('content-type', '')
                is_pdf = pr.content[:4] == b'%PDF' or 'application/pdf' in ct
                size = len(pr.content)
                print(f"   Try: {url[:100]}")
                print(f"     → {ct[:60]}, {size} bytes, isPDF={is_pdf}")
                if is_pdf and size > 2000:
                    fname = f"{pub}_{doi_part[:20]}.pdf"
                    with open(os.path.join(TEST_DIR, fname), 'wb') as f:
                        f.write(pr.content)
                    print(f"     ✅ SAVED: {fname} ({size//1024}KB)")
            except Exception as e:
                print(f"     ❌ Error: {e}")
            
        # Strategy 4: Try Unpaywall API for open access version
        doi_clean = doi.strip()
        try:
            up_resp = requests.get(f'https://api.unpaywall.org/v2/{doi_clean}?email=coche@cityu.edu.hk', timeout=10)
            if up_resp.status_code == 200:
                up = up_resp.json()
                oa = up.get('best_oa_location', {})
                if oa and oa.get('url_for_pdf'):
                    print(f"   Unpaywall OA: {oa['url_for_pdf'][:100]}")
                    # Try to download
                    try:
                        upr = requests.get(oa['url_for_pdf'], headers=headers, timeout=30, allow_redirects=True)
                        if upr.content[:4] == b'%PDF' and len(upr.content) > 2000:
                            fname = f"{pub}_OA_{doi_part[:20]}.pdf"
                            with open(os.path.join(TEST_DIR, fname), 'wb') as f:
                                f.write(upr.content)
                            print(f"     ✅ OA SAVED: {fname} ({len(upr.content)//1024}KB)")
                    except: pass
        except: pass
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
