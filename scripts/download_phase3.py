#!/usr/bin/env python3
"""
Final run: download remaining 38 papers using Playwright + timeouts.
Uses 'commit' wait (fastest) + long timeout for Wiley slow pages.
Also uses requests for MDPI easier cases.
"""
import json, os, re, asyncio, requests
from playwright.async_api import async_playwright

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
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml',
}

rs = requests.Session()
rs.cookies.update(COOKIES)
rs.headers.update(HEADERS)

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

print(f"Remaining: {len(targets)} papers", flush=True)
wiley = [p for p in targets if '10.1002/' in p['doi']]
mdpi = [p for p in targets if '10.3390/' in p['doi']]
print(f"  Wiley: {len(wiley)}")
print(f"  MDPI: {len(mdpi)}")
print()

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

def save_pdf(filepath, content):
    with open(filepath, 'wb') as f:
        f.write(content)
    return len(content)

# ===== Phase 1: Try MDPI with requests =====
print("Phase 1: MDPI via requests...")
for p in mdpi:
    doi = p['doi']
    pmid = p['pmid']
    filename = sanitize_filename(p['title'], pmid)
    itc_year = get_itc_year(p)
    year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
    os.makedirs(year_dir, exist_ok=True)
    filepath = os.path.join(year_dir, filename)
    
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        print(f"  ⏭️ Exists: {p['title'][:50]}")
        continue
    
    title = p['title'][:50]
    downloaded = False
    
    # Try direct MDPI
    try:
        doi_url = f'https://doi.org/{doi}'
        r = rs.get(doi_url, timeout=15, allow_redirects=True)
        page_url = r.url
        pdf_url = page_url.rstrip('/') + '/pdf'
        
        pr = rs.get(pdf_url, timeout=30, allow_redirects=True)
        if pr.content[:4] == b'%PDF' and len(pr.content) > 5000:
            size = save_pdf(filepath, pr.content)
            print(f"  ✅ [MDPI] {title} (direct:{size//1024}KB)")
            downloaded = True
    except:
        pass
    
    if not downloaded:
        # Try ezproxy
        try:
            ez_pdf = f'https://eproxy.lib.hku.hk/login?url=https://www.mdpi.com/{doi.split("/")[-1]}/pdf'
            pr = rs.get(ez_pdf, timeout=30, allow_redirects=True)
            if pr.content[:4] == b'%PDF' and len(pr.content) > 5000:
                size = save_pdf(filepath, pr.content)
                print(f"  ✅ [MDPI] {title} (ezproxy:{size//1024}KB)")
                downloaded = True
        except:
            pass
    
    if not downloaded:
        # Try via doi
        try:
            doi_url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
            r = rs.get(doi_url, timeout=15, allow_redirects=True)
            from urllib.parse import urljoin
            m = re.search(r'citation_pdf_url["\'][^>]*content=["\']([^"\']+)', r.text, re.IGNORECASE)
            if m:
                pr = rs.get(m.group(1), timeout=30, allow_redirects=True)
                if pr.content[:4] == b'%PDF' and len(pr.content) > 5000:
                    size = save_pdf(filepath, pr.content)
                    print(f"  ✅ [MDPI] {title} (cite_pdf:{size//1024}KB)")
                    downloaded = True
        except:
            pass
    
    if not downloaded:
        print(f"  ❌ [MDPI] no_pdf: {title}")

print()

# ===== Phase 2: Try Wiley with browser (longer timeouts) =====
print("Phase 2: Wiley via Playwright browser...")

async def wiley_download(page, p, filepath):
    doi = p['doi']
    
    # Try the epdf direct URL first (renders PDF in browser for authorized users)
    # We need to go through ezproxy
    urls_to_try = [
        # Through ezproxy to doi which redirects to Wiley
        f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}',
        # Direct Wiley epdf (may be blocked without ezproxy)
        f'https://onlinelibrary.wiley.com/doi/epdf/{doi}',
    ]
    
    for url in urls_to_try:
        try:
            # Use 'commit' which fires once navigation committed (no waiting for resources)
            await page.goto(url, wait_until='load', timeout=90000)
            await asyncio.sleep(5)
            
            # Check if PDF rendered
            ct = await page.evaluate('document.contentType')
            if ct == 'application/pdf':
                content = await page.evaluate('''async () => {
                    const r = await fetch(window.location.href);
                    const buf = await r.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }''')
                if content and len(content) > 5000:
                    save_pdf(filepath, bytes(content))
                    return len(content)
            
            # Check for citation_pdf_url 
            pdf_url = await page.evaluate('''() => {
                const meta = document.querySelector('meta[name="citation_pdf_url"]');
                if (meta) return meta.content;
                const link = document.querySelector('link[type="application/pdf"]');
                if (link) return link.href;
                return null;
            }''')
            
            if pdf_url:
                await page.goto(pdf_url, wait_until='load', timeout=30000)
                await asyncio.sleep(3)
                ct2 = await page.evaluate('document.contentType')
                if ct2 == 'application/pdf':
                    content = await page.evaluate('''async () => {
                        const r = await fetch(window.location.href);
                        const buf = await r.arrayBuffer();
                        return Array.from(new Uint8Array(buf));
                    }''')
                    if content and len(content) > 5000:
                        save_pdf(filepath, bytes(content))
                        return len(content)
            
        except Exception as e:
            continue
    
    return 0

async def browser_phase():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800}
        )
        await context.add_cookies([
            {'name': 'ezproxy', 'value': 'e1~Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv', 'domain': '.lib.hku.hk', 'path': '/'},
            {'name': 'ezproxyl', 'value': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv', 'domain': '.lib.hku.hk', 'path': '/'},
            {'name': 'ezproxyn', 'value': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv', 'domain': '.lib.hku.hk', 'path': '/'},
        ])
        page = await context.new_page()
        
        wiley_downloaded = 0
        wiley_failed = 0
        
        for idx, p in enumerate(wiley):
            doi = p['doi']
            pmid = p['pmid']
            filename = sanitize_filename(p['title'], pmid)
            itc_year = get_itc_year(p)
            year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
            os.makedirs(year_dir, exist_ok=True)
            filepath = os.path.join(year_dir, filename)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
                print(f"  ⏭️ Exists: {p['title'][:50]}")
                continue
            
            size = await wiley_download(page, p, filepath)
            title = p['title'][:50]
            
            if size > 0:
                wiley_downloaded += 1
                print(f"  ✅ [{wiley_downloaded}] Wiley: {title} ({size//1024}KB)")
            else:
                wiley_failed += 1
                print(f"  ❌ [{idx+1}] Wiley: {title} [{doi[:30]}]")
            
            if (idx + 1) % 5 == 0:
                print(f"  📊 {idx+1}/{len(wiley)}: {wiley_downloaded} ok, {wiley_failed} fail")
        
        await browser.close()
        return wiley_downloaded, wiley_failed

wiley_ok, wiley_fail = asyncio.run(browser_phase())

# Final stats
total = sum(1 for _ in os.walk(PDF_DIR) for f in _[2] if f.endswith('.pdf'))
total_size = sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(PDF_DIR) for f in fs if f.endswith('.pdf'))
print(f"\n=== Final ===")
print(f"Total PDFs: {total} ({total_size/1024/1024:.1f} MB)")
print(f"Wiley: {wiley_ok} ok, {wiley_fail} fail")
