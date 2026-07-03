#!/usr/bin/env python3
"""
corresponding_author_scanner.py
Scans COCHE papers without corresponding-author annotations via EZproxy.
Updates author_list[].is_corresponding in coche_pubmed.json.
"""
import json, requests, re, time, os, sys

WORKSPACE = os.environ.get('COCHE_WORKSPACE', '/home/ubuntu/.openclaw/workspace')
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

with open(PUBMED_FILE) as f:
    papers = json.load(f)

# Only scan papers with DOIs that don't have any corresponding author yet
need_scan = []
for p in papers:
    author_list = p.get('author_list', [])
    has_corr = any(a.get('is_corresponding', False) for a in author_list)
    if not has_corr and p.get('doi'):
        need_scan.append(p)

print(f"Papers needing corresponding-author scan: {len(need_scan)}")

if not need_scan:
    print("All papers have corresponding author info — nothing to do.")
    sys.exit(0)

cookies = {
    'ezproxy': os.environ.get('EZPROXY_COOKIE', 'e1~4OZOdetOtmObrqJb8X4ivYqj96nmr1e'),
    'ezproxyl': os.environ.get('EZPROXYL_COOKIE', '4OZOdetOtmObrqJb8X4ivYqj96nmr1e'),
    'ezproxyn': os.environ.get('EZPROXYN_COOKIE', '4OZOdetOtmObrqJb8X4ivYqj96nmr1e'),
}
headers = {'User-Agent': 'Mozilla/5.0'}

# Patterns to detect corresponding authors in publisher HTML
corr_patterns = [
    # Direct "corresponding author" labels near author names
    re.compile(r'(?:corresponding|corr[.\s]*author|to\s+whom\s+correspondence\s+should\s+be\s+addressed)', re.IGNORECASE),
    # Email icon/asterisk patterns
    re.compile(r'(?:📧|✉|✉️|@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.IGNORECASE),
]

updated = 0
for p in need_scan:
    doi = p['doi']
    url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    
    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=25, allow_redirects=True)
        html = resp.text
        
        if 'login' in resp.url and 'eproxy' in resp.url:
            print(f"  ❌ EZproxy cookie expired — skipping remaining")
            break
        
        # Try to find corresponding author annotation section
        # Look for author names followed by email or corresponding mark
        author_list = p.get('author_list', [])
        
        for author in author_list:
            name = author.get('name', '')
            if not name:
                continue
            last_name = name.split()[-1] if ' ' in name else name
            
            # Look for this author name in the page near correspondence indicators
            name_idx = html.lower().find(last_name.lower())
            if name_idx == -1:
                continue
            
            # Check vicinity (next 500 chars) for corresponding indicators
            vicinity = html[max(0, name_idx-200):name_idx+500].lower()
            
            if re.search(r'(?:correspond|email:\s|📧|✉|\*correspond|\*to\s+whom)', vicinity, re.IGNORECASE):
                # Additional check: is there an actual email in this vicinity?
                if re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', vicinity):
                    author['is_corresponding'] = True
                    updated += 1
        
    except Exception as e:
        pass
    
    if (need_scan.index(p) + 1) % 50 == 0:
        print(f"  Scanned {need_scan.index(p)+1}/{len(need_scan)}, {updated} corresponding found")
    
    time.sleep(0.5)

# Save
with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

print(f"Done. {updated} corresponding author annotations added.")
