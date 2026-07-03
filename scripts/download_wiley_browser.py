#!/usr/bin/env python3
"""Download PDFs from Wiley/other JS-heavy publishers via Playwright."""
import json, os, re, asyncio, sys
from playwright.async_api import async_playwright

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PDF_DIR = os.path.join(WORKSPACE, 'pdfs')
os.makedirs(PDF_DIR, exist_ok=True)

with open(PUBMED_FILE) as f:
    papers = json.load(f)

existing_pmids = set()
for root, dirs, files in os.walk(PDF_DIR):
    for f in files:
        if f.endswith('.pdf') and f.startswith('PMID_'):
            existing_pmids.add(f.split('_')[1])

targets = [p for p in papers if 
           'affiliation' in p.get('source', []) and 
           'innohk_acknowledgement' in p.get('source', []) and
           p.get('doi') and p.get('pmid','') not in existing_pmids]

# Focus on Wiley first (44 papers), then others
wiley = [p for p in targets if '10.1002/' in p.get('doi','')]
others = [p for p in targets if '10.1002/' not in p.get('doi','')]
to_download = wiley + others

print(f"Total missing: {len(to_download)} (Wiley: {len(wiley)}, Other: {len(others)})", flush=True)

COOKIES = [
    {'name': 'ezproxy', 'value': 'e1~Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv', 'domain': '.lib.hku.hk', 'path': '/'},
    {'name': 'ezproxyl', 'value': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv', 'domain': '.lib.hku.hk', 'path': '/'},
    {'name': 'ezproxyn', 'value': 'Y8dcXMXEi6085Gk13ORhhG4T6sjCxzv', 'domain': '.lib.hku.hk', 'path': '/'},
]

def get_itc_year(p):
    y = int(p.get('pub_year', '0') or '0')
    m = (p.get('pub_month', 'Jan') or 'Jan')[:3]
    mn = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}.get(m, 1)
    return y + 1 if mn == 12 else y

def sanitize_filename(title, pmid):
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = re.sub(r'\s+', '_', safe)[:80]
    return f"PMID_{pmid}_{safe}.pdf"

async def process_wiley(page, p, filepath):
    """Wiley-specific: go to doi/epdf which renders PDF directly."""
    doi = p.get('doi', '')
    # Wiley's /doi/epdf/ redirects to a PDF reader page with download
    url = f'https://eproxy.lib.hku.hk/login?url=https://onlinelibrary.wiley.com/doi/epdf/{doi}'
    
    try:
        resp = await page.goto(url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(3)
        
        # Check if redirected to PDF directly
        ct = await page.evaluate('document.contentType')
        if ct == 'application/pdf':
            content = await page.evaluate('''async () => {
                const r = await fetch(window.location.href);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }''')
            if content and len(content) > 2000:
                with open(filepath, 'wb') as f:
                    f.write(bytes(content))
                return f'Wiley-direct:{len(content)//1024}KB'
        
        # The epdf page has an iframe or toolbar with a download button
        # Try clicking the download/toolbar PDF button
        for btn in ['a:has-text("PDF")', 'button:has-text("Download")', 
                     '.download-pdf', '#downloadPdf', '[title="PDF"]',
                     'a[href*=".pdf"]']:
            try:
                el = page.locator(btn).first
                if await el.count() > 0:
                    href = await el.get_attribute('href')
                    if href:
                        await page.goto(href, wait_until='networkidle', timeout=15000)
                        await asyncio.sleep(2)
                    else:
                        await el.click(timeout=5000)
                        await asyncio.sleep(3)
                    
                    ct2 = await page.evaluate('document.contentType')
                    if ct2 == 'application/pdf':
                        content = await page.evaluate('''async () => {
                            const r = await fetch(window.location.href);
                            const buf = await r.arrayBuffer();
                            return Array.from(new Uint8Array(buf));
                        }''')
                        if content and len(content) > 2000:
                            with open(filepath, 'wb') as f:
                                f.write(bytes(content))
                            return f'Wiley-{btn}:{len(content)//1024}KB'
            except:
                pass
        
        # Fallback: /doi/pdfdirect/
        await page.goto(f'https://eproxy.lib.hku.hk/login?url=https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}',
                       wait_until='networkidle', timeout=15000)
        await asyncio.sleep(3)
        ct3 = await page.evaluate('document.contentType')
        if ct3 == 'application/pdf':
            content = await page.evaluate('''async () => {
                const r = await fetch(window.location.href);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }''')
            if content and len(content) > 2000:
                with open(filepath, 'wb') as f:
                    f.write(bytes(content))
                return f'Wiley-pdfdirect:{len(content)//1024}KB'
        
        return 'Wiley-no-pdf'
    except Exception as e:
        return f'Wiley-err:{str(e)[:40]}'

async def process_generic(page, p, filepath):
    """Generic handler for non-Wiley publishers."""
    doi = p.get('doi', '')
    doi_url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    
    try:
        await page.goto(doi_url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(3)
        
        # Check if PDF directly
        if 'application/pdf' in await page.evaluate('document.contentType'):
            content = await page.evaluate('''async () => {
                const r = await fetch(window.location.href);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }''')
            if content and len(content) > 2000:
                with open(filepath, 'wb') as f:
                    f.write(bytes(content))
                return f'direct:{len(content)//1024}KB'
        
        # Look for PDF links
        pdf_href = await page.evaluate('''() => {
            const links = document.querySelectorAll('a[href*=".pdf"]');
            for (const l of links) {
                const h = l.href;
                if (!h.includes('suppl') && !h.includes('supplementary') && !h.includes('cover'))
                    return h;
            }
            // Try meta tag
            const meta = document.querySelector('meta[name="citation_pdf_url"]');
            if (meta) return meta.content;
            return null;
        }''')
        
        if pdf_href:
            await page.goto(pdf_href, wait_until='networkidle', timeout=15000)
            await asyncio.sleep(2)
            ct = await page.evaluate('document.contentType')
            if 'application/pdf' in ct:
                content = await page.evaluate('''async () => {
                    const r = await fetch(window.location.href);
                    const buf = await r.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }''')
                if content and len(content) > 2000:
                    with open(filepath, 'wb') as f:
                        f.write(bytes(content))
                    return f'link:{len(content)//1024}KB'
        
        # Try clicking PDF/Download buttons
        for sel in ['a:has-text("PDF")', 'a:has-text("Download PDF")',
                     'a:has-text("Download")', 'button:has-text("PDF")']:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click(timeout=5000)
                    await asyncio.sleep(3)
                    ct2 = await page.evaluate('document.contentType')
                    if 'application/pdf' in ct2:
                        content = await page.evaluate('''async () => {
                            const r = await fetch(window.location.href);
                            const buf = await r.arrayBuffer();
                            return Array.from(new Uint8Array(buf));
                        }''')
                        if content and len(content) > 2000:
                            with open(filepath, 'wb') as f:
                                f.write(bytes(content))
                            return f'click:{len(content)//1024}KB'
            except:
                pass
        
        # Try publisher-specific patterns
        if '10.1038/' in doi or '10.1039/' in doi:
            doi_part = doi.split('/')[-1]
            await page.goto(f'https://www.nature.com/articles/{doi_part}.pdf', wait_until='networkidle', timeout=15000)
            await asyncio.sleep(2)
        elif '10.1126/' in doi:
            await page.goto(f'https://www.science.org/doi/pdf/{doi}?download=true', wait_until='networkidle', timeout=15000)
            await asyncio.sleep(2)
        elif '10.1016/' in doi:
            await page.goto(f'https://linkinghub.elsevier.com/retrieve/pii/{doi.split("/")[-1]}.pdf', wait_until='networkidle', timeout=15000)
            await asyncio.sleep(2)
        
        ct3 = await page.evaluate('document.contentType')
        if 'application/pdf' in ct3:
            content = await page.evaluate('''async () => {
                const r = await fetch(window.location.href);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }''')
            if content and len(content) > 2000:
                with open(filepath, 'wb') as f:
                    f.write(bytes(content))
                return f'pattern:{len(content)//1024}KB'
        
        return 'no_pdf'
    except Exception as e:
        return f'err:{str(e)[:40]}'

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1280, 'height': 800}
        )
        await context.add_cookies(COOKIES)
        page = await context.new_page()
        
        downloaded = 0
        failed = 0
        
        for idx, p in enumerate(to_download):
            doi = p.get('doi', '')
            pmid = p.get('pmid', '')
            filename = sanitize_filename(p['title'], pmid)
            itc_year = get_itc_year(p)
            year_dir = os.path.join(PDF_DIR, f'ITC_{itc_year}')
            os.makedirs(year_dir, exist_ok=True)
            filepath = os.path.join(year_dir, filename)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
                continue
            
            is_wiley = '10.1002/' in doi
            result = await (process_wiley(page, p, filepath) if is_wiley else process_generic(page, p, filepath))
            
            if result and 'KB' in str(result):
                downloaded += 1
                title = p['title'][:50]
                print(f"  ✅ [{downloaded}/{idx+1}] {title} ({result})", flush=True)
            else:
                failed += 1
                title = p['title'][:40]
                pub = 'Wiley' if is_wiley else 'Other'
                print(f"  ❌ [{pub}] {result}: {title}", flush=True)
            
            if (idx + 1) % 15 == 0:
                print(f"  📊 {idx+1}/{len(to_download)}: {downloaded} ok, {failed} fail", flush=True)
        
        await browser.close()
        
        # Stats
        total_pdfs = sum(1 for _ in os.walk(PDF_DIR) for f in _[2] if f.endswith('.pdf'))
        total_size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(PDF_DIR) for f in fs if f.endswith('.pdf'))
        print(f"\n=== Done ===", flush=True)
        print(f"New downloaded: {downloaded}, Failed: {failed}", flush=True)
        print(f"Total PDFs: {total_pdfs} ({total_size/1024/1024:.1f} MB)", flush=True)

asyncio.run(main())
