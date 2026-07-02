#!/bin/bash
# ==============================================================
# COCHE Paper Tracker — Weekly Update Script
# Schedule: Every Monday 09:00 Asia/Shanghai (cron-managed)
#
# Flow:
#   1. Fetch NEW papers only from PubMed (dual-channel search)
#   2. Merge new papers → coche_pubmed.json (preserving existing data)
#   3. Scan new papers for InnoHK via PMC full-text
#   4. Scan new papers for InnoHK/ITC via HKU EZproxy (full-text publisher pages)
#   5. Generate all outputs (README.md, Excel, etc.)
#   6. Commit & push to GitHub
#
# NOTE: This script NEVER re-fetches existing papers — coche_pubmed.json
# is the single source of truth. All existing InnoHK tags are preserved.
# ==============================================================
set -e

WORKSPACE="/home/ubuntu/.openclaw/workspace"
SCRIPT_DIR="$WORKSPACE/scripts"

# Load GitHub token
if [ -f "$WORKSPACE/.gh_token" ]; then
  source "$WORKSPACE/.gh_token"
fi

PUBMED_FILE="$WORKSPACE/coche_pubmed.json"
LOG_FILE="$WORKSPACE/coche_weekly_update.log"
NEW_PAPERS_FILE="/tmp/coche_new_papers.json"

echo "" | tee -a "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ====== COCHE Weekly Update ======" | tee -a "$LOG_FILE"

# ==============================================================
# Step 1: Fetch new papers from PubMed (dual-channel)
# ==============================================================
echo "[$(date '+%H:%M:%S')] [1/6] Fetching new papers from PubMed..." | tee -a "$LOG_FILE"

python3 < "$SCRIPT_DIR/coche_weekly_update.sh" 2>/dev/null || python3 << 'PYEOF'
import json, requests, time, xml.etree.ElementTree as ET, os, re

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

# Load existing PMIDs
existing_pmids = set()
if os.path.exists(PUBMED_FILE):
    with open(PUBMED_FILE) as f:
        existing = json.load(f)
        existing_pmids = {p['pmid'] for p in existing}
print(f"  Existing papers in database: {len(existing_pmids)}")

# ── COCHE affiliation check ──
def is_coche_affiliation(aff_text):
    if not aff_text: return False
    aff = aff_text.lower()
    coche_terms = [
        'cerebro-cardiovascular health engineering',
        'cerebra-cardiovascular health engineering',
        'cerebrocardiovascular health engineering',
        'cerebro cardiovascular health engineering',
        'cerebra cardiovascular health engineering',
    ]
    hk_terms = ['hong kong', 'hongkong', 'shatin', 'kowloon', 'cityu', 'city university',
                'hk science', 'hksar', 'hkstp', 'new territories', 'pak shek kok']
    has_coche = any(t in aff for t in coche_terms)
    has_hk = any(t in aff for t in hk_terms)
    venezuela = any(t in aff for t in ['venezuela', 'caracas', 'periferico', 'periférico'])
    return has_coche and has_hk and not venezuela

# ── Queries ──
AFFILIATION_QUERIES = [
    '"Hong Kong Centre for Cerebro-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebra-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebro-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebra-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebrocardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebrocardiovascular Health Engineering"[Affiliation]',
    '"COCHE"[Affiliation]',
    '("Cerebro-cardiovascular Health Engineering"[All Fields] OR "Cerebra-cardiovascular Health Engineering"[All Fields] OR "Cerebrocardiovascular Health Engineering"[All Fields]) AND ("Hong Kong"[All Fields] OR "Hong Kong Science Park"[All Fields])',
    'COCHE[Affiliation] AND (Hong Kong[Affiliation] OR cerebro-cardiovascular[All Fields])',
]

INNOHK_QUERIES = [
    '"InnoHK"[All Fields] AND ("cerebro-cardiovascular"[All Fields] OR "cerebra-cardiovascular"[All Fields] OR "cerebrocardiovascular"[All Fields] OR "COCHE"[All Fields])',
]

all_queries = AFFILIATION_QUERIES + INNOHK_QUERIES
seen_pmids = set()
new_pmid_list = []

def fetch_ids(query):
    ids = []
    retstart = 0
    while True:
        resp = requests.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi', params={
            'db': 'pubmed', 'term': query, 'retstart': retstart,
            'retmax': 500, 'retmode': 'json', 'sort': 'date'
        }, timeout=30)
        data = resp.json()
        idlist = data.get('esearchresult', {}).get('idlist', [])
        total = int(data.get('esearchresult', {}).get('count', '0'))
        for pid in idlist:
            if pid not in seen_pmids and pid not in existing_pmids:
                ids.append(pid)
                seen_pmids.add(pid)
        if not idlist or retstart + 500 >= total:
            break
        retstart += 500
        time.sleep(0.4)
    return ids

all_ids = []
for q in all_queries:
    ids = fetch_ids(q)
    all_ids.extend(ids)
    time.sleep(0.3)

print(f"  New PMIDs found: {len(all_ids)}")

if not all_ids:
    print("  No new papers — skipping fetch.")
    with open('/tmp/coche_new_papers.json', 'w') as f:
        json.dump([], f)
else:
    # ── Fetch details ──
    papers = []
    for i in range(0, len(all_ids), 100):
        batch = all_ids[i:i+100]
        resp = requests.post('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi', data={
            'db': 'pubmed', 'id': ','.join(batch), 'retmode': 'xml', 'rettype': 'abstract'
        }, timeout=60)
        root = ET.fromstring(resp.content)
        for article in root.findall('.//PubmedArticle'):
            try:
                pmid = article.find('.//PMID').text
                title_e = article.find('.//ArticleTitle')
                title = title_e.text if title_e is not None else ''
                if title is None: title = ''
                
                abstract_parts = []
                for abs_elem in article.findall('.//Abstract/AbstractText'):
                    t = abs_elem.text or ''
                    abstract_parts.append(t)
                abstract_text = ' '.join(abstract_parts)
                
                # Grant info
                grant_texts = []
                for grant in article.findall('.//Grant'):
                    gid = grant.find('./GrantID')
                    ag = grant.find('./Agency')
                    parts = []
                    if gid is not None and gid.text: parts.append(gid.text)
                    if ag is not None and ag.text: parts.append(ag.text)
                    grant_texts.append(' '.join(parts))
                grant_combined = ' '.join(grant_texts)
                
                # Authors
                authors, coche_authors = [], []
                for author in article.findall('.//Author'):
                    last = author.find('./LastName')
                    fore = author.find('./ForeName')
                    name = f'{fore.text} {last.text}' if fore is not None and last is not None else ''
                    in_coche = False
                    for aff in author.findall('.//AffiliationInfo/Affiliation'):
                        aff_text = aff.text or ''
                        if is_coche_affiliation(aff_text):
                            in_coche = True
                        authors.append(aff_text) if aff_text else None
                    if in_coche and name:
                        coche_authors.append(name.strip())
                    authors.append(name.strip() if name else '')
                
                journal = article.find('.//Journal/Title')
                journal_name = journal.text if journal is not None else ''
                doi = ''
                for eid in article.findall('.//ELocationID'):
                    if eid.get('EIdType') == 'doi':
                        doi = eid.text or ''; break
                
                pub_date = article.find('.//PubDate')
                y = pub_date.find('Year'); y = y.text if y is not None else ''
                m = pub_date.find('Month'); m = m.text if m is not None else ''
                d = pub_date.find('Day'); d = d.text if d is not None else ''
                
                # Get PMC ID
                pmc = ''
                for other_id in article.findall('.//ArticleId'):
                    if other_id.get('IdType') == 'pmc':
                        pmc = other_id.text or ''
                        break
                
                papers.append({
                    'pmid': pmid, 'doi': doi, 'title': title,
                    'journal': journal_name, 'pub_year': y, 'pub_month': m, 'pub_day': d,
                    'authors': authors, 'coche_authors': coche_authors,
                    'source': ['affiliation'] if coche_authors else [],
                    'pmc': pmc,
                    'date_is_precise': True,
                })
            except:
                continue
        time.sleep(0.5)
    
    papers.sort(key=lambda x: (int(x.get('pub_year','0') or '0'), 
                                {'Jan':0,'Feb':1,'Mar':2,'Apr':3,'May':4,'Jun':5,'Jul':6,'Aug':7,'Sep':8,'Oct':9,'Nov':10,'Dec':11}.get((x.get('pub_month','Jan') or 'Jan')[:3], 0),
                                int((x.get('pub_day','01') or '01'))), reverse=True)
    
    with open('/tmp/coche_new_papers.json', 'w') as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)
    print(f"  Fetched {len(papers)} new paper details")
PYEOF

# ==============================================================
# Step 2: Merge new papers into coche_pubmed.json
# ==============================================================
echo "[$(date '+%H:%M:%S')] [2/6] Merging new papers..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
import json

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = f'{WORKSPACE}/coche_pubmed.json'
NEW_FILE = '/tmp/coche_new_papers.json'

with open(NEW_FILE) as f:
    new_papers = json.load(f)

if not new_papers:
    print("  No new papers to merge")
else:
    with open(PUBMED_FILE) as f:
        existing = json.load(f)
    
    existing_pmids = {p['pmid'] for p in existing}
    added = 0
    for p in new_papers:
        if p['pmid'] not in existing_pmids:
            existing.append(p)
            existing_pmids.add(p['pmid'])
            added += 1
    
    # Re-sort by date
    mo = {'Jan':0,'Feb':1,'Mar':2,'Apr':3,'May':4,'Jun':5,'Jul':6,'Aug':7,'Sep':8,'Oct':9,'Nov':10,'Dec':11}
    existing.sort(key=lambda x: (
        -int(x.get('pub_year','0') or '0'),
        -mo.get((x.get('pub_month','Jan') or 'Jan')[:3], 0),
        -int((x.get('pub_day','01') or '01'))
    ))
    
    with open(PUBMED_FILE, 'w') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    
    affil = sum(1 for p in existing if 'affiliation' in p.get('source', []))
    innohk = sum(1 for p in existing if 'innohk_acknowledgement' in p.get('source', []))
    both = sum(1 for p in existing if 'affiliation' in p.get('source', []) and 'innohk_acknowledgement' in p.get('source', []))
    print(f"  Merged {added} new papers")
    print(f"  Total: {len(existing)} | ⭐ Dual-Channel: {both} | InnoHK total: {innohk}")
PYEOF

# ==============================================================
# Step 3: Scan new papers for InnoHK via PMC full-text
# ==============================================================
echo "[$(date '+%H:%M:%S')] [3/6] Scanning new papers via PMC full-text..." | tee -a "$LOG_FILE"

# Use the existing PMC scanner script — only scans papers without innohk tag
python3 "$SCRIPT_DIR/scan_innohk_pmc.py" 2>&1 | tee -a "$LOG_FILE" || echo "  PMC scan skipped (no new PMC papers or error)"

# ==============================================================
# Step 4: Scan new papers for InnoHK/ITC via EZproxy
# ==============================================================
echo "[$(date '+%H:%M:%S')] [4/6] Scanning new papers via EZproxy (InnoHK + ITC full-name)..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
"""EZproxy scan for NEW papers only — check for InnoHK and Innovation and Technology Commission."""
import json, requests, re, time, os

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = f'{WORKSPACE}/coche_pubmed.json'

with open(PUBMED_FILE) as f:
    papers = json.load(f)

# Only scan papers WITHOUT innohk tag AND have a DOI
target = [p for p in papers if 'innohk_acknowledgement' not in p.get('source', []) and p.get('doi')]
print(f"  Papers to scan: {len(target)}")

if not target:
    print("  No papers to scan — all already tagged")
    exit(0)

cookies = {
    'ezproxy': os.environ.get('EZPROXY_COOKIE', 'e1~4OZOdetOtmObrqJb8X4ivYqj96nmr1e'),
    'ezproxyl': os.environ.get('EZPROXYL_COOKIE', '4OZOdetOtmObrqJb8X4ivYqj96nmr1e'),
    'ezproxyn': os.environ.get('EZPROXYN_COOKIE', '4OZOdetOtmObrqJb8X4ivYqj96nmr1e'),
}
headers = {'User-Agent': 'Mozilla/5.0'}

# Combined patterns: InnoHK + ITC full name
patterns = [
    re.compile(r'InnoHK', re.IGNORECASE),
    re.compile(r'Innovation\s+and\s+Technology\s+Commission.*?(?:through|project|grant|support|fund|award|InnoHK|COCHE|Centre|Center|Health)', re.IGNORECASE),
    re.compile(r'(?:supported|funded|sponsored)\s+(?:by|in\s+part\s+by).*?Innovation\s+and\s+Technology\s+Commission', re.IGNORECASE),
]

def has_ack_context(html, match_pos):
    before = html[max(0, match_pos-800):match_pos].lower()
    if re.search(r'(?:acknowledg|funding|support|grant|financial|this\s+work\s+(?:was|is)\s+(?:supported|funded))', before):
        return True
    if re.search(r'(?:RGC|GRF|CRF|Research\s+Grant|project\s+(?:no|number))', before, re.IGNORECASE):
        return True
    after_len = len(html) - match_pos
    if after_len < 3000:
        if not re.search(r'(?:affiliation|department\s+of|corresponding\s+author|author\s+contributions?|conflict\s+of\s+interest)', before[-400:]):
            return True
    return False

new_finds = 0
for p in target:
    doi = p['doi']
    url = f'https://eproxy.lib.hku.hk/login?url=https://doi.org/{doi}'
    
    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=25, allow_redirects=True)
        html = resp.text
        
        if 'login' in resp.url and 'eproxy' in resp.url:
            print(f"  ❌ EZproxy cookie expired — skipping remaining scans")
            print(f"  👉 Please update cookies in environment and re-run")
            break
        
        found = False
        for pat in patterns:
            m = pat.search(html)
            if m:
                if not has_ack_context(html, m.start()):
                    continue
                idx = m.start()
                snippet = re.sub(r'<[^>]+>', ' ', html[max(0,idx-80):idx+300])
                snippet = re.sub(r'\s+', ' ', snippet).strip()
                
                p.setdefault('source', []).append('innohk_acknowledgement')
                p['innohk_snippet'] = snippet[:300]
                p['innohk_source'] = f'ezproxy_{"itc_fullname" if "commission" in m.group().lower() else "innohk"}'
                new_finds += 1
                found = True
                print(f"  ✅ PMID {p['pmid']}: {p['title'][:70]}")
                break
        
    except Exception as e:
        pass
    
    time.sleep(0.25)

# Save
# Clean: remove source duplicates and empty source fields
for p in papers:
    if 'source' in p:
        # Dedup
        seen = set()
        p['source'] = [s for s in p['source'] if not (s in seen or seen.add(s))]
        if not p['source']:
            p['source'] = ['affiliation']  # default

with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

both_final = sum(1 for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[]))
io_final = sum(1 for p in papers if p.get('source') == ['innohk_acknowledgement'])
print(f"  EZproxy scan done: {new_finds} new InnoHK/ITC finds")
print(f"  Total: {len(papers)} | ⭐ Dual-Channel: {both_final} | InnoHK-only: {io_final}")
PYEOF

# ==============================================================
# Step 5: Generate all outputs
# ==============================================================
echo "[$(date '+%H:%M:%S')] [5/6] Generating outputs..." | tee -a "$LOG_FILE"
python3 "$SCRIPT_DIR/generate_outputs.py" 2>&1 | tee -a "$LOG_FILE"

# ==============================================================
# Step 6: Commit and push to GitHub
# ==============================================================
echo "[$(date '+%H:%M:%S')] [6/6] Pushing to GitHub..." | tee -a "$LOG_FILE"
cd "$WORKSPACE"
git add COCHE_Papers.xlsx COCHE_Weekly_Report.md coche_pubmed.json README.md FULL_LIST.md index.md scripts/
git commit -m "Weekly COCHE update $(date '+%Y-%m-%d')" || echo "  No changes to commit"

# Push via proxy (trojan SOCKS5 on localhost:1080)
if [ -n "$GH_TOKEN" ]; then
    git -c http.proxy=socks5://127.0.0.1:1080 push "https://${GH_TOKEN}@github.com/ZLI-afk/coche-papers.git" main 2>/dev/null || \
    git -c http.proxy=socks5://127.0.0.1:1080 push origin main 2>/dev/null
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ====== Update Complete ======" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
