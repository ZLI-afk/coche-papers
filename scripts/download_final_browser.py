#!/usr/bin/env python3
"""
Final attempt: download remaining PDFs using Playwright browser for
Wiley (via /doi/epdf/ which renders inline PDF) and MDPI (open access).
"""
import json, os, re, asyncio, time
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

print(f"Remaining: {len(targets)} papers")
print(f"  Wiley (10.1002): {len([p for p in targets if '10.1002/' in p['doi']])}")
print(f"  MDPI (10.3390): {len([p for p in targets if '10.3390/' in p['doi']])}")
print(f"  Other: {len([p for p in targets if '10.1002/' not in p['doi'] and '10.3390/' not in p['doi']])}")
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

async def download_via_browser(page, p):
    doi = p.get('doi', '')
    pmid = p.get('pmid', '')
    title = p['title']
    filename = sanitize_filename(title, pmid)
    itc_year = get_itc_year(p)
    year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
    os.makedirs(year_dir, exist_ok=True)
    filepath = os.path.join(year_dir, filename)
    
    if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
        return 'exists', 0
    
    is_wiley = '10.1002/' in doi
    is_mdpi = '10.3390/' in doi
    
    try:
        # Strategy for Wiley: go to the abstract page first, then find PDF link
        if is_wiley:
            # Directly try Wiley's PDF rendering page - /doi/epdf/ renders PDF inline via iframe
            url = f'https://onlinelibrary.wiley.com/doi/epdf/{doi}'
            
            # Set up download handler first
            page.on('download', lambda dl: None)
            download_file = None
            download_size = 0
            
            async def handle_download(download):
                nonlocal download_file, download_size
                download_file = filepath
                await download.save_as(filepath)
                download_size = os.path.getsize(filepath)
            
            page.on('download', handle_download)
            
            resp = await page.goto(url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(5)
            
            # Check if we got a PDF
            ct = await page.evaluate('document.contentType')
            if ct == 'application/pdf':
                pdf_url = page.url
                content = await page.evaluate('''async () => {
                    const r = await fetch(window.location.href);
                    const buf = await r.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }''')
                if content and len(content) > 5000:
                    with open(filepath, 'wb') as f:
                        f.write(bytes(content))
                    return 'wiley_inline', len(content)
            
            # The Wiley epdf page has a toolbar with download
            # Look for the PDF iframe
            iframe = page.frame_locator('iframe#iframe-pdf')
            try:
                iframe_count = await page.locator('iframe#iframe-pdf').count()
                if iframe_count > 0:
                    # Try to get the PDF URL from the iframe
                    pdf_src = await page.locator('iframe#iframe-pdf').get_attribute('src')
                    if pdf_src:
                        await page.goto(pdf_src, wait_until='networkidle', timeout=30000)
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
                                return 'wiley_iframe', len(content)
            except:
                pass
            
            # Wait for any download to fire  
            await asyncio.sleep(3)
            if download_file and download_size > 2000:
                return 'wiley_download', download_size
            
            return 'wiley_no_pdf', 0
        
        elif is_mdpi:
            # MDPI is open access - go to the article page
            doi_url = f'https://doi.org/{doi}'
            resp = await page.goto(doi_url, wait_until='networkidle', timeout=30000)
            await asyncio.sleep(3)
            
            # MDPI has a "Download PDF" link/button
            # Try clicking download buttons
            for sel in ['a:has-text("Download PDF")', 'a:has-text("PDF")',
                         'a[href*="/pdf"]', 'button:has-text("PDF")',
                         '.bib-holder a:has-text("Download")']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        href = await el.get_attribute('href')
                        if href:
                            if href.endswith('.pdf') or '/pdf' in href:
                                await page.goto(href if href.startswith('http') else 
                                               'https://www.mdpi.com' + href,
                                               wait_until='networkidle', timeout=30000)
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
                                        return 'mdpi_pdf', len(content)
                except:
                    pass
            
            # Direct PDF URL
            try:
                pdf_url = page.url.rstrip('/') + '/pdf'
                await page.goto(pdf_url, wait_until='networkidle', timeout=30000)
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
                        return 'mdpi_direct', len(content)
            except:
                pass
            
            return 'mdpi_no_pdf', 0
        
        else:
            # Generic: go to DOI
            doi_url = f'https://doi.org/{doi}'
            resp = await page.goto(doi_url, wait_until='networkidle', timeout=30000)
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
                    return 'direct', len(content)
            
            # Look for PDF links
            pdf_href = await page.evaluate('''() => {
                const meta = document.querySelector('meta[name="citation_pdf_url"]');
                if (meta) return meta.content;
                const links = document.querySelectorAll('a[href*=".pdf"]');
                for (const l of links) {
                    if (!l.href.includes('suppl') && !l.href.includes('supplementary'))
                        return l.href;
                }
                return null;
            }''')
            
            if pdf_href:
                await page.goto(pdf_href, wait_until='networkidle', timeout=30000)
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
                        return 'link', len(content)
            
            return 'no_pdf', 0
            
    except Exception as e:
        err = str(e)[:50]
        if 'Timeout' in err:
            return 'timeout', 0
        return f'err:{err}', 0

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        
        downloaded = 0
        failed = 0
        
        for idx, p in enumerate(targets):
            result, size = await download_via_browser(page, p)
            title = p['title'][:55]
            doi = p.get('doi', '')[:30]
            pub_type = 'Wiley' if '10.1002/' in doi else 'MDPI' if '10.3390/' in doi else 'Other'
            
            if result == 'exists':
                print(f"  ⏭️ [{idx+1}] Exists: {title}", flush=True)
            elif result and 'KB' not in str(result) and size > 0:
                downloaded += 1
                print(f"  ✅ [{downloaded}/{idx+1}] [{pub_type}] {title} ({result}:{size//1024}KB)", flush=True)
            else:
                failed += 1
                print(f"  ❌ [{idx+1}] [{pub_type}] {result}: {title} [{doi}]", flush=True)
            
            if (idx + 1) % 5 == 0:
                print(f"  📊 {idx+1}/{len(targets)}: {downloaded} ok, {failed} fail", flush=True)
        
        await browser.close()
    
    # Stats
    total = sum(1 for _ in os.walk(PDF_DIR) for f in _[2] if f.endswith('.pdf'))
    total_size = sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(PDF_DIR) for f in fs if f.endswith('.pdf'))
    print(f"\n=== Done ===")
    print(f"New downloaded: {downloaded}, Failed: {failed}")
    print(f"Total PDFs: {total} ({total_size/1024/1024:.1f} MB)")

asyncio.run(main())
