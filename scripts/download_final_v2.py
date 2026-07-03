#!/usr/bin/env python3
"""
Final attempt for Wiley+MDPI: use Playwright browser with HKU ezproxy.
Key fix: go through eproxy.lib.hku.hk for Wiley access.
"""
import json, os, re, asyncio
from playwright.async_api import async_playwright

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

print(f"Remaining: {len(targets)} papers", flush=True)
for prefix in ['10.1002', '10.3390']:
    print(f"  {prefix}: {len([p for p in targets if prefix+'/' in p['doi']])}", flush=True)
print(flush=True)

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

async def download_wiley(page, p, filepath):
    """Wiley: go through HKU ezproxy to the article abstract page, then find PDF."""
    doi = p.get('doi', '')
    
    try:
        # Step 1: Go to abstract page via ezproxy
        ez_doi_url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
        resp = await page.goto(ez_doi_url, wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)
        
        # Step 2: Find citation_pdf_url
        pdf_url = await page.evaluate('''() => {
            const meta = document.querySelector('meta[name="citation_pdf_url"]');
            if (meta) return meta.content;
            // Also try link[type="application/pdf"]
            const link = document.querySelector('link[type="application/pdf"]');
            if (link) return link.href;
            // Look for "PDF" links
            const pdf_links = document.querySelectorAll('a[href*="/doi/pdf/"]');
            for (const l of pdf_links) {
                if (l.href.includes('.pdf')) return l.href;
            }
            return null;
        }''')
        
        if pdf_url:
            # Step 3: Navigate to PDF URL (already in ezproxy domain)
            await page.goto(pdf_url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)
            
            # Check content type
            ct = await page.evaluate('document.contentType')
            if ct == 'application/pdf':
                content = await page.evaluate('''async () => {
                    const r = await fetch(window.location.href);
                    const buf = await r.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }''')
                if content and len(content) > 5000:
                    with open(filepath, 'wb') as f:
                        f.write(bytes(content))
                    return f'wiley-pdf:{len(content)//1024}KB', len(content)
                
            # If not PDF, we might have hit a login/paywall page
            # Try reading the URL for a redirect
            await asyncio.sleep(2)
            ct2 = await page.evaluate('document.contentType')
            if ct2 == 'application/pdf':
                content = await page.evaluate('''async () => {
                    const r = await fetch(window.location.href);
                    const buf = await r.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }''')
                if content and len(content) > 5000:
                    with open(filepath, 'wb') as f:
                        f.write(bytes(content))
                    return f'wiley-pdf2:{len(content)//1024}KB', len(content)
        
        # Step 4: Try Wiley-specific patterns via ezproxy
        ez_patterns = [
            f'https://eproxy.lib.hku.hk/login?url=https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}',
            f'https://eproxy.lib.hku.hk/login?url=https://onlinelibrary.wiley.com/doi/epdf/{doi}',
        ]
        
        for ez_pdf_url in ez_patterns:
            try:
                await page.goto(ez_pdf_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(3)
                ct = await page.evaluate('document.contentType')
                if ct == 'application/pdf':
                    content = await page.evaluate('''async () => {
                        const r = await fetch(window.location.href);
                        const buf = await r.arrayBuffer();
                        return Array.from(new Uint8Array(buf));
                    }''')
                    if content and len(content) > 5000:
                        with open(filepath, 'wb') as f:
                            f.write(bytes(content))
                        return f'wiley-ez:{len(content)//1024}KB', len(content)
            except:
                continue
        
        return 'wiley_no_pdf', 0
        
    except Exception as e:
        return f'wiley-err:{str(e)[:40]}', 0

async def download_mdpi(page, p, filepath):
    """MDPI: open access, JS-heavy website."""
    doi = p.get('doi', '')
    
    try:
        # Go directly to mdpi.com
        doi_url = f'https://doi.org/{doi}'
        await page.goto(doi_url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(3)
        
        # Try to construct PDF URL from page URL
        page_url = page.url
        # e.g. https://www.mdpi.com/2306-5354/13/2/190
        pdf_url = page_url.rstrip('/') + '/pdf'
        
        await page.goto(pdf_url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(2)
        
        ct = await page.evaluate('document.contentType')
        if ct == 'application/pdf':
            content = await page.evaluate('''async () => {
                const r = await fetch(window.location.href);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }''')
            if content and len(content) > 5000:
                with open(filepath, 'wb') as f:
                    f.write(bytes(content))
                return f'mdpi:{len(content)//1024}KB', len(content)
        
        # Try ezproxy
        ez_pdf_url = f'https://eproxy.lib.hku.hk/login?url={pdf_url}'
        await page.goto(ez_pdf_url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(2)
        
        ct2 = await page.evaluate('document.contentType')
        if ct2 == 'application/pdf':
            content = await page.evaluate('''async () => {
                const r = await fetch(window.location.href);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }''')
            if content and len(content) > 5000:
                with open(filepath, 'wb') as f:
                    f.write(bytes(content))
                return f'mdpi-ez:{len(content)//1024}KB', len(content)
        
        return 'mdpi_no_pdf', 0
        
    except Exception as e:
        return f'mdpi-err:{str(e)[:40]}', 0

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1280, 'height': 800},
            # Set cookies for ezproxy
            storage_state=None
        )
        
        # Set cookies
        await context.add_cookies([
            {'name': 'ezproxy', 'value': 'e1~Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
             'domain': '.lib.hku.hk', 'path': '/'},
            {'name': 'ezproxyl', 'value': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
             'domain': '.lib.hku.hk', 'path': '/'},
            {'name': 'ezproxyn', 'value': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv',
             'domain': '.lib.hku.hk', 'path': '/'},
        ])
        
        page = await context.new_page()
        downloaded = 0
        failed = 0
        
        for idx, p in enumerate(targets):
            doi = p.get('doi', '')
            pmid = p.get('pmid', '')
            title = p['title']
            filename = sanitize_filename(title, pmid)
            itc_year = get_itc_year(p)
            year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
            os.makedirs(year_dir, exist_ok=True)
            filepath = os.path.join(year_dir, filename)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
                print(f"  ⏭️ [{idx+1}] Exists", flush=True)
                continue
            
            is_wiley = '10.1002/' in doi
            is_mdpi = '10.3390/' in doi
            
            if is_wiley:
                result, size = await download_wiley(page, p, filepath)
            elif is_mdpi:
                result, size = await download_mdpi(page, p, filepath)
            else:
                result, size = 'unknown', 0
            
            tag = 'Wiley' if is_wiley else 'MDPI'
            
            if size > 0:
                downloaded += 1
                print(f"  ✅ [{downloaded}/{idx+1}] [{tag}] {title[:50]} ({result})", flush=True)
            else:
                failed += 1
                print(f"  ❌ [{idx+1}] [{tag}] {result}: {title[:40]} [{doi[:30]}]", flush=True)
            
            if (idx + 1) % 5 == 0:
                print(f"  📊 {idx+1}/{len(targets)}: {downloaded} ok, {failed} fail", flush=True)
        
        await browser.close()
    
    total = sum(1 for _ in os.walk(PDF_DIR) for f in _[2] if f.endswith('.pdf'))
    total_size = sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(PDF_DIR) for f in fs if f.endswith('.pdf'))
    print(f"\n=== Done ===", flush=True)
    print(f"New: {downloaded} | Failed: {failed}", flush=True)
    print(f"Total PDFs: {total} ({total_size/1024/1024:.1f} MB)", flush=True)

asyncio.run(main())
