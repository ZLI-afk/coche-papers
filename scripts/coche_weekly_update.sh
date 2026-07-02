#!/bin/bash
# ==============================================================
# COCHE Paper Tracker — Weekly Update Script
# Runs every Monday 9:00 AM Asia/Shanghai via cron
# Dual search strategy (ITC KPI compliant):
#   Channel A: COCHE affiliation match (existing)
#   Channel B: InnoHK acknowledgement match (NEW for ITC KPI)
# 1. Fetch from PubMed via both channels, deduplicate
# 2. Compare with previous week, identify new papers
# 3. Generate Excel (full list + highlight recent 30 days)
# 4. Generate Markdown weekly report
# 5. Commit & push to GitHub
# ==============================================================
set -e

WORKSPACE="/home/ubuntu/.openclaw/workspace"

# Load GitHub token if available
if [ -f "$WORKSPACE/.gh_token" ]; then
  source "$WORKSPACE/.gh_token"
fi
PUBMED_FILE="$WORKSPACE/coche_pubmed.json"
PREV_FILE="$WORKSPACE/coche_pubmed_previous.json"
EXCEL_FILE="$WORKSPACE/COCHE_Papers.xlsx"
REPORT_FILE="$WORKSPACE/COCHE_Weekly_Report.md"
LOG_FILE="$WORKSPACE/coche_weekly_update.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === COCHE Weekly Update Start ===" | tee "$LOG_FILE"

# ==============================================================
# Step 1: Dual-source PubMed fetch
#   Channel A — COCHE affiliation (existing)
#   Channel B — InnoHK acknowledgement (NEW for ITC KPI)
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 1: Fetching PubMed (dual channel)..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
import requests, json, time, xml.etree.ElementTree as ET, os

# ── Helpers ────────────────────────────────────────────────────
def is_coche_affiliation(aff_text):
    if not aff_text: return False
    aff = aff_text.lower()
    coche_terms = [
        'cerebro-cardiovascular health engineering',
        'cerebra-cardiovascular health engineering',
        'cerebrocardiovascular health engineering',
        'cerebro cardiovascular health engineering',
        'cerebra cardiovascular health engineering',
        'cerebro-cardiovascular health',
        'cerebra-cardiovascular health',
        'cerebrocardiovascular health',
    ]
    hk_terms = ['hong kong', 'hongkong', 'shatin', 'kowloon', 'cityu', 'city university',
                'hk science', 'hksar', 'hkstp', 'new territories', 'pak shek kok']
    has_coche = any(t in aff for t in coche_terms)
    has_hk = any(t in aff for t in hk_terms)
    venezuela = any(t in aff for t in ['venezuela', 'caracas', 'periferico', 'periférico'])
    return has_coche and has_hk and not venezuela

def is_innohk_ack(text):
    """Check if text contains an InnoHK acknowledgement for COCHE.
    
    PubMed XML may contain InnoHK in these fields:
    - Abstract (funding statement at end)
    - Grant/Agency (grant acknowledgement)
    - Affiliation (author institution)
    
    We accept ANY text that mentions InnoHK — the upstream query already
    ANDs with COCHE/Cerebro keywords, so false positives are minimal.
    False negatives are worse for ITC KPI reporting.
    """
    if not text: return False
    t = text.lower()
    return 'innohk' in t or 'inno hk' in t

# ── Channel A: COCHE affiliation queries ───────────────────────
AFFILIATION_QUERIES = [
    '"Hong Kong Centre for Cerebro-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebra-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebro-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebra-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebrocardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebrocardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebra Cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebro Cardiovascular Health Engineering"[Affiliation]',
    '"COCHE"[Affiliation]',
]

TEXT_QUERIES = [
    '("Cerebro-cardiovascular Health Engineering"[All Fields] OR "Cerebra-cardiovascular Health Engineering"[All Fields] OR "Cerebrocardiovascular Health Engineering"[All Fields]) AND ("Hong Kong"[All Fields] OR "Hong Kong Science Park"[All Fields])',
    'COCHE[Affiliation] AND (Hong Kong[Affiliation] OR cerebro-cardiovascular[All Fields])',
]

# ── Channel B: InnoHK acknowledgement queries ──────────────────
# Strategy: search for "InnoHK" AND COCHE/Cerebro keywords anywhere
# PubMed indexes acknowledgements/grant fields in [All Fields] and [Grant Number]
# Only papers mentioning BOTH InnoHK AND COCHE-related terms are relevant
INNOHK_QUERIES = [
    '"InnoHK"[All Fields] AND ("cerebro-cardiovascular"[All Fields] OR "cerebra-cardiovascular"[All Fields] OR "cerebrocardiovascular"[All Fields] OR "COCHE"[All Fields])',
    '"InnoHK"[Grant Number] AND ("cerebro-cardiovascular"[All Fields] OR "cerebra-cardiovascular"[All Fields] OR "cerebrocardiovascular"[All Fields] OR "COCHE"[All Fields])',
]

CHANNEL_A_QUERIES = AFFILIATION_QUERIES + TEXT_QUERIES
CHANNEL_B_QUERIES = INNOHK_QUERIES

seen_pmids = set()
channel_a_pmids = set()
channel_b_pmids = set()

def fetch_ids(query, label=''):
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
            if pid not in seen_pmids:
                ids.append(pid)
                seen_pmids.add(pid)
        if not idlist or retstart + 500 >= total:
            break
        retstart += 500
        time.sleep(0.4)
    return ids

# Fetch Channel A (existing COCHE affiliation)
all_ids_a = []
for q in CHANNEL_A_QUERIES:
    ids = fetch_ids(q, 'A')
    all_ids_a.extend(ids)
    channel_a_pmids.update(ids)
    time.sleep(0.3)

# Fetch Channel B (InnoHK acknowledgement)
all_ids_b = []
for q in CHANNEL_B_QUERIES:
    ids = fetch_ids(q, 'B')
    all_ids_b.extend(ids)
    channel_b_pmids.update(ids)
    time.sleep(0.3)

# Only fetch B-pmids that are NOT already in A (dedup)
new_b_ids = [pid for pid in all_ids_b if pid not in channel_a_pmids]
all_ids = all_ids_a + new_b_ids

print(f"  Channel A (affiliation): {len(all_ids_a)} PMIDs")
print(f"  Channel B (InnoHK ack):  {len(all_ids_b)} PMIDs ({len(new_b_ids)} new unique)")
print(f"  Total unique: {len(all_ids)}")

# ── Fetch full details ────────────────────────────────────────
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

            # ── Abstract text (for InnoHK ack check) ──
            abstract_parts = []
            for abs_elem in article.findall('.//Abstract/AbstractText'):
                t = abs_elem.text or ''
                abstract_parts.append(t)
            abstract_text = ' '.join(abstract_parts)

            # ── Grant info (also checked for InnoHK) ──
            grant_texts = []
            for grant in article.findall('.//Grant'):
                grant_id = grant.find('./GrantID')
                agency = grant.find('./Agency')
                g_parts = []
                if grant_id is not None and grant_id.text:
                    g_parts.append(grant_id.text)
                if agency is not None and agency.text:
                    g_parts.append(agency.text)
                grant_texts.append(' '.join(g_parts))
            grant_combined = ' '.join(grant_texts)

            # ── Determine source channels ──
            in_affiliation = pmid in channel_a_pmids

            # For InnoHK detection: scan ALL text in the article XML
            # (abstract, grant, affiliation, comment, etc.)
            # This catches papers where InnoHK appears in various PubMed fields
            article_xml = ET.tostring(article, encoding='unicode')
            in_innohk_ack = (
                pmid in channel_b_pmids or
                is_innohk_ack(article_xml)
            )

            # ── Authors ──
            authors, coche_authors = [], []
            all_affiliations = []
            for author in article.findall('.//Author'):
                last = author.find('./LastName')
                fore = author.find('./ForeName')
                name = f'{fore.text} {last.text}' if fore is not None and last is not None else ''
                affs, in_coche = [], False
                for aff in author.findall('.//AffiliationInfo/Affiliation'):
                    aff_text = aff.text or ''
                    affs.append(aff_text)
                    all_affiliations.append(aff_text)
                    if is_coche_affiliation(aff_text):
                        in_coche = True
                authors.append({'name': name.strip() if name else '', 'affiliations': affs})
                if in_coche and name:
                    coche_authors.append(name.strip())

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
            date_completed = None
            date_completed = None  # xml.etree has no getparent()
            if date_completed is None:
                for ancestor in article.iterancestors('MedlineCitation'):
                    date_completed = ancestor.find('DateCompleted')
                    if date_completed is not None:
                        break
            if date_completed is not None:
                cy = date_completed.find('Year')
                cm = date_completed.find('Month')
                cd = date_completed.find('Day')
                completed_date = (cy.text if cy is not None else ''), (cm.text if cm is not None else ''), (cd.text if cd is not None else '')
            else:
                completed_date = None

            # ── Determine source string ──
            sources = []
            if in_affiliation:
                sources.append('affiliation')
            if in_innohk_ack:
                sources.append('innohk_acknowledgement')
            if not sources:
                sources.append('unknown')

            # ── Find matching InnoHK snippet from full article XML ──
            innohk_snippet = ''
            if in_innohk_ack:
                idx = article_xml.lower().find('innohk')
                if idx >= 0:
                    start = max(0, idx - 60)
                    end = min(len(article_xml), idx + 200)
                    # Strip XML tags for cleaner display
                    import re
                    raw = article_xml[start:end]
                    raw = re.sub(r'<[^>]+>', ' ', raw)
                    raw = re.sub(r'\s+', ' ', raw).strip()
                    innohk_snippet = raw

            papers.append({
                'pmid': pmid, 'doi': doi, 'title': title,
                'journal': journal_name, 'pub_year': y, 'pub_month': m, 'pub_day': d,
                'completed_year': completed_date[0] if completed_date else '',
                'completed_month': completed_date[1] if completed_date else '',
                'completed_day': completed_date[2] if completed_date else '',
                'authors': authors, 'coche_authors': coche_authors,
                'source': sources,
                'innohk_snippet': innohk_snippet,
            })
        except:
            continue
    time.sleep(0.5)

# ── Filter: keep papers matching EITHER channel ──
cleaned = []
for p in papers:
    # Channel A: has COCHE in affiliation
    match_a = False
    for a in p.get('authors', []):
        for aff in a.get('affiliations', []):
            if is_coche_affiliation(aff):
                match_a = True
                break
        if match_a:
            break

    # Channel B: has InnoHK acknowledgement
    match_b = 'innohk_acknowledgement' in p.get('source', [])

    if match_a or match_b:
        # If only Channel B matched (no COCHE affiliation), still set source correctly
        if not match_a:
            p['source'] = ['innohk_acknowledgement']
            # Keep coche_authors empty — these papers acknowledge InnoHK but authors
            # may not have COCHE in their affiliation string
        cleaned.append(p)

cleaned.sort(key=lambda x: (x.get('pub_year','0'), x.get('pub_month','0'), x.get('pub_day','0')), reverse=True)

# Slim down: keep only author names (not full affiliations) to reduce file size
for p in cleaned:
    p['authors'] = [a.get('name', a) if isinstance(a, dict) else a for a in p.get('authors', [])]
    p.pop('all_affiliations', None)
    p.pop('coche_in_grants', None)

# Stats
count_a = sum(1 for p in cleaned if 'affiliation' in p.get('source', []))
count_b = sum(1 for p in cleaned if 'innohk_acknowledgement' in p.get('source', []))
count_both = sum(1 for p in cleaned if 'affiliation' in p.get('source', []) and 'innohk_acknowledgement' in p.get('source', []))
count_b_only = sum(1 for p in cleaned if p.get('source') == ['innohk_acknowledgement'])

output_path = '/home/ubuntu/.openclaw/workspace/coche_pubmed.json'
with open(output_path, 'w') as f:
    json.dump(cleaned, f, indent=2, ensure_ascii=False)

print(f"  Saved {len(cleaned)} papers to coche_pubmed.json")
print(f"    via affiliation:         {count_a}")
print(f"    via InnoHK ack:          {count_b}")
print(f"    both channels:           {count_both}")
print(f"    InnoHK ack ONLY (new):   {count_b_only}")
PYEOF

echo "[$(date '+%H:%M:%S')] Dual-channel PubMed fetch complete" | tee -a "$LOG_FILE"

# ==============================================================
# Step 2: Compare with previous, identify new papers
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 2: Comparing with previous week..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
import json, os
from datetime import datetime, timedelta

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
month_map = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
             'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}

with open(f'{WORKSPACE}/coche_pubmed.json') as f:
    current = json.load(f)

prev_pmids = set()
prev_file = f'{WORKSPACE}/coche_pubmed_previous.json'
if os.path.exists(prev_file):
    with open(prev_file) as f:
        prev = json.load(f)
        prev_pmids = {p.get('pmid') for p in prev}

curr_pmids = {p.get('pmid') for p in current}
new_pmids = curr_pmids - prev_pmids

new_papers = [p for p in current if p.get('pmid') in new_pmids]

# Also identify papers from last 30 days
thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
recent_papers = []
for p in current:
    y = p.get('pub_year', '')
    m = p.get('pub_month', '') or 'Jan'
    d = p.get('pub_day', '') or '01'
    mm = month_map.get(m[:3], '01')
    dd = d.zfill(2)
    date_str = f'{y}-{mm}-{dd}'
    if date_str >= thirty_days_ago:
        recent_papers.append(p)

# Separate stats by source
affil_count = sum(1 for p in current if 'affiliation' in p.get('source', []))
innohk_count = sum(1 for p in current if 'innohk_acknowledgement' in p.get('source', []))
innohk_only = sum(1 for p in current if p.get('source') == ['innohk_acknowledgement'])

new_innohk_only = sum(1 for p in new_papers if p.get('source') == ['innohk_acknowledgement'])
recent_innohk_only = sum(1 for p in recent_papers if p.get('source') == ['innohk_acknowledgement'])

new_file = f'{WORKSPACE}/coche_new_papers.json'
with open(new_file, 'w') as f:
    json.dump(new_papers, f, indent=2, ensure_ascii=False)

recent_file = f'{WORKSPACE}/coche_recent_30d.json'
with open(recent_file, 'w') as f:
    json.dump(recent_papers, f, indent=2, ensure_ascii=False)

print(f"  New this week: {len(new_papers)} (InnoHK-only: {new_innohk_only})")
print(f"  Recent 30 days: {len(recent_papers)} (InnoHK-only: {recent_innohk_only})")
print(f"  Total: {len(current)}")
print(f"  By source: {affil_count} via affiliation | {innohk_count} via InnoHK ack | {innohk_only} InnoHK-only")
PYEOF

# ==============================================================
# Step 3: Generate Excel
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 3: Generating Excel..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
import json, os
from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
with open(f'{WORKSPACE}/coche_pubmed.json') as f:
    papers = json.load(f)

wb = Workbook()
ws = wb.active
ws.title = "COCHE Papers"

# Styles
hdr_font = Font(bold=True, size=11, color="FFFFFF")
hdr_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
hdr_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
recent_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # light yellow highlight
innohk_fill = PatternFill(start_color="D9EAD3", end_color="D9EAD3", fill_type="solid")  # light green = InnoHK source
border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
border_bottom = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='medium'))

headers = ['序号', 'PMID', '论文标题', 'DOI', '出版日期', '期刊', 'COCHE 作者', '来源渠道', '全部作者', '链接']
for col, h in enumerate(headers, 1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = hdr_font; c.fill = hdr_fill; c.alignment = hdr_align; c.border = border

widths = [5, 10, 55, 30, 12, 30, 25, 22, 45, 35]
for i, w in enumerate(widths, 1):
    ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
month_map = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
             'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}

for idx, p in enumerate(papers, 1):
    y = p.get('pub_year', '')
    m = p.get('pub_month', '') or 'Jan'
    d = p.get('pub_day', '') or '01'
    mm = month_map.get(m[:3], '01')
    dd = d.zfill(2)
    date_str = f'{y}-{mm}-{dd}'
    date_display = date_str if y else ''
    
    doi = p.get('doi', '')
    link = f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{p.get("pmid","")}'
    
    coche_authors = ', '.join(p.get('coche_authors', []))
    all_authors = ', '.join([a['name'] for a in p.get('authors', [])[:8]])
    if len(p.get('authors', [])) > 8:
        all_authors += ' ...'
    
    # Source channel label
    sources = p.get('source', [])
    if 'affiliation' in sources and 'innohk_acknowledgement' in sources:
        source_label = 'affiliation + InnoHK'
    elif 'innohk_acknowledgement' in sources:
        source_label = 'InnoHK acknowledgement'
    elif 'affiliation' in sources:
        source_label = 'affiliation'
    else:
        source_label = 'unknown'
    
    pmid_str = str(p.get('pmid', ''))
    
    vals = [idx, pmid_str, p.get('title', ''), doi, date_display, 
            p.get('journal', ''), coche_authors, source_label, all_authors, link]
    
    is_recent = date_str >= thirty_days_ago
    is_innohk_only = sources == ['innohk_acknowledgement']
    
    for col, val in enumerate(vals, 1):
        c = ws.cell(row=idx+1, column=col, value=val)
        c.font = Font(size=10)
        c.alignment = Alignment(vertical='top', wrap_text=True)
        c.border = border
        if is_recent:
            c.fill = recent_fill
            c.font = Font(size=10, bold=True)
        elif is_innohk_only:
            c.fill = innohk_fill  # green = InnoHK-only papers

# Legend
legend_row = len(papers) + 3
ws.cell(row=legend_row, column=1, value='🟡').font = Font(size=14)
recent_count = len([p for p in papers if f"{p.get('pub_year','')}-{month_map.get((p.get('pub_month','') or 'Jan')[:3],'01')}-{(p.get('pub_day','') or '01').zfill(2)}" >= thirty_days_ago])
ws.cell(row=legend_row, column=2, value=f'黄色高亮 = 近30天发表 ({recent_count} 篇)')
ws.merge_cells(start_row=legend_row, start_column=2, end_row=legend_row, end_column=10)

legend_row2 = legend_row + 1
innohk_only_count = sum(1 for p in papers if p.get('source') == ['innohk_acknowledgement'])
ws.cell(row=legend_row2, column=1, value='🟢').font = Font(size=14)
ws.cell(row=legend_row2, column=2, value=f'绿色高亮 = InnoHK致谢收录 (无COCHE机构署名, {innohk_only_count} 篇)')
ws.merge_cells(start_row=legend_row2, start_column=2, end_row=legend_row2, end_column=10)

ws.freeze_panes = 'A2'
ws.auto_filter.ref = ws.dimensions

output_path = f'{WORKSPACE}/COCHE_Papers.xlsx'
wb.save(output_path)
print(f"  Excel saved: {output_path}")
PYEOF

# ==============================================================
# ==============================================================
# Step 4: Generate Markdown Weekly Report
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 4: Generating report..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
import json
from datetime import datetime

WORKSPACE = '/home/ubuntu/.openclaw/workspace'

with open(f'{WORKSPACE}/coche_pubmed.json') as f:
    current = json.load(f)

with open(f'{WORKSPACE}/coche_new_papers.json') as f:
    new_papers = json.load(f)

with open(f'{WORKSPACE}/coche_recent_30d.json') as f:
    recent_papers = json.load(f)

# Stats
affil_count = sum(1 for p in current if 'affiliation' in p.get('source', []))
innohk_count = sum(1 for p in current if 'innohk_acknowledgement' in p.get('source', []))
innohk_only = sum(1 for p in current if p.get('source') == ['innohk_acknowledgement'])
new_innohk_only = sum(1 for p in new_papers if p.get('source') == ['innohk_acknowledgement'])

now = datetime.now()
report = []
report.append(f"# COCHE Paper Tracker — Weekly Report")
report.append(f"**更新时间**: {now.strftime('%Y-%m-%d %H:%M')} (Asia/Shanghai)")
report.append(f"")
report.append(f"## 📊 概要")
report.append(f"- **论文总数**: {len(current)} 篇")
report.append(f"  - 机构署名 (affiliation): {affil_count} 篇")
report.append(f"  - InnoHK致谢收录: {innohk_count} 篇")
report.append(f"  - 纯InnoHK致谢 (无COCHE署名): {innohk_only} 篇")
report.append(f"- **本周新增**: {len(new_papers)} 篇 (其中 InnoHK-only: {new_innohk_only} 篇)")
report.append(f"- **近30天发表**: {len(recent_papers)} 篇")
report.append(f"")
report.append(f"## 📝 搜索策略")
report.append(f"采用双通道搜索，以满足ITC KPI申报要求：")
report.append(f"1. **机构署名匹配** — 作者affiliation包含COCHE/Cerebro-Cardiovascular Health Engineering + Hong Kong")
report.append(f"2. **InnoHK致谢匹配** — 论文acknowledgement/grant中包含InnoHK + ITC/HKSAR Government")
report.append(f"")
report.append(f"ITC认可致谢声明模板：")
report.append(f"> *Fully supported:* \"This study was supported by the InnoHK initiative of the Innovation and Technology Commission of the Hong Kong Special Administrative Region Government.\"")
report.append(f"> *Partly supported:* \"This study was funded in part by the InnoHK initiative of the Innovation and Technology Commission of the Hong Kong Special Administrative Region Government...\"")
report.append(f"")

if new_papers:
    report.append(f"## 🆕 本周新增 ({len(new_papers)} 篇)")
    report.append(f"")
    for i, p in enumerate(new_papers, 1):
        doi = p.get('doi', '')
        pmid = p.get('pmid', '')
        link = f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}'
        coche_authors = ', '.join(p.get('coche_authors', []))
        date_str = f"{p.get('pub_year','')}-{p.get('pub_month','')}-{p.get('pub_day','')}".strip('-')
        sources = p.get('source', [])
        src_tag = ' 🏷️ InnoHK' if 'innohk_acknowledgement' in sources else ''
        report.append(f"**{i}. {p.get('title', '')}**{src_tag}")
        report.append(f"- 📅 {date_str} | 📰 {p.get('journal', '')}")
        report.append(f"- 👤 COCHE Authors: {coche_authors or 'N/A'}")
        report.append(f"- 📡 Source: {', '.join(sources)}")
        innohk_snippet = p.get('innohk_snippet', '')
        if innohk_snippet:
            report.append(f"- 💬 InnoHK snippet: \"...{innohk_snippet[:150]}...\"")
        report.append(f"- 🔗 [{link}]({link})")
        report.append(f"")

if recent_papers:
    report.append(f"## 🟡 近30天发表 ({len(recent_papers)} 篇)")
    report.append(f"")
    report.append(f"| # | 标题 | 日期 | 期刊 | COCHE 作者 | 来源 |")
    report.append(f"|---|------|------|------|------------|------|")
    for i, p in enumerate(recent_papers[:50], 1):
        date_str = f"{p.get('pub_year','')}-{p.get('pub_month','')}-{p.get('pub_day','')}".strip('-')
        title = p.get('title', '')[:55] + ('...' if len(p.get('title', '')) > 55 else '')
        coche_authors = ', '.join(p.get('coche_authors', [])[:2])
        if len(p.get('coche_authors', [])) > 2:
            coche_authors += ' 等'
        sources = p.get('source', [])
        if 'innohk_acknowledgement' in sources:
            src_label = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
        else:
            src_label = 'affil'
        report.append(f"| {i} | {title} | {date_str} | {p.get('journal', '')[:25]} | {coche_authors or 'N/A'} | {src_label} |")
    if len(recent_papers) > 50:
        report.append(f"| ... | ... | ... | ... | ... | ... |")
    report.append(f"")

report.append(f"---")
report.append(f"*自动生成于 {now.strftime('%Y-%m-%d %H:%M:%S')} | 数据来源: PubMed API (双通道: affiliation + InnoHK acknowledgement)*")

with open(f'{WORKSPACE}/COCHE_Weekly_Report.md', 'w') as f:
    f.write('\n'.join(report))

print(f"  Report saved")

# Generate FULL_LIST.md (per-year markdown tables)
print(f"  Generating FULL_LIST.md...")
from collections import Counter

month_map = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
             'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}

full = []
full.append('# COCHE 全部论文列表')
full.append(f'')
full.append(f'> 📊 **{len(current)} 篇** | ⏰ 更新: {datetime.now().strftime("%Y-%m-%d %H:%M")} UTC+8')
full.append(f'> 搜索策略: 机构署名 (affiliation) + InnoHK 致谢 (ITC KPI 合规)')
full.append(f'> 数据来源: PubMed · [返回首页](README.md)')
full.append('')
full.append('---')
full.append('')

year_cnt = Counter(p.get('pub_year', '?') for p in current)
for year in sorted(year_cnt.keys(), reverse=True):
    yr_papers = [p for p in current if p.get('pub_year') == year]
    full.append(f'## {year} ({len(yr_papers)} 篇)')
    full.append('')
    full.append('| # | 标题 | 日期 | 期刊 | COCHE 作者 | 来源 | PMID |')
    full.append('|---|------|------|------|------------|------|------|')
    for i, p in enumerate(yr_papers, 1):
        doi = p.get('doi', '')
        pmid = p.get('pmid', '')
        link = f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}'
        title = p.get('title', '').replace('|', '\\\\|')
        m = month_map.get((p.get('pub_month','') or 'Jan')[:3], '01')
        date_str = f"{p.get('pub_year','')}-{m}-{(p.get('pub_day','') or '01').zfill(2)}"
        authors = ', '.join(p.get('coche_authors', [])[:3])
        if len(p.get('coche_authors', [])) > 3:
            authors += ' et al.'
        journal = (p.get('journal', '') or '')[:30]
        sources = p.get('source', [])
        if 'innohk_acknowledgement' in sources:
            src = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
        else:
            src = 'affil'
        full.append(f'| {i} | [{title}]({link}) | {date_str} | {journal} | {authors or "N/A"} | {src} | {pmid} |')
    full.append('')

full.append('---')
full.append(f'*自动生成 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} · 双通道搜索 (affiliation + InnoHK) · [返回首页](README.md)*')

with open(f'{WORKSPACE}/FULL_LIST.md', 'w') as f:
    f.write('\n'.join(full))
print(f"  FULL_LIST.md generated")

# ==============================================================
# Generate index.md for GitHub Pages rendering
# ==============================================================
from collections import Counter
from datetime import datetime, timedelta

thirty_days_ago_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

def get_date(p):
    y = p.get('pub_year', '')
    m = p.get('pub_month', '') or 'Jan'
    d = p.get('pub_day', '') or '01'
    mm = month_map.get(m[:3], '01')
    date_str = f'{y}-{mm.zfill(2)}-{d.zfill(2)}'
    if date_str > datetime.now().strftime('%Y-%m-%d') and p.get('completed_year'):
        cy = p.get('completed_year', '')
        cm = p.get('completed_month', '') or 'Jan'
        cd = p.get('completed_day', '') or '01'
        cmm = month_map.get(cm[:3], '01')
        date_str = f'{cy}-{cmm.zfill(2)}-{cd.zfill(2)}'
    return date_str

recent_idx = []
older_idx = []
for p in current:
    if get_date(p) >= thirty_days_ago_date:
        recent_idx.append(p)
    else:
        older_idx.append(p)

year_cnt = Counter(p.get('pub_year', '?') for p in current)

idx = []
idx.append('# COCHE Paper Tracker')
idx.append('')
idx.append(f'> **Hong Kong Centre for Cerebro-Cardiovascular Health Engineering**')
idx.append(f'> 双通道搜索: 机构署名 + InnoHK 致谢 (ITC KPI 合规)')
idx.append(f'> 每周一自动更新 | 数据来源: PubMed API')
idx.append(f'')
idx.append(f'📊 **总论文数: {len(current)} 篇** | 🏷 InnoHK 收录: {innohk_count} 篇 | 🆕 近30天: {len(recent_idx)} 篇 | ⏰ 更新: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
idx.append('')
idx.append('---')
idx.append('')

if recent_idx:
    idx.append(f'## 🟡 近30天发表 ({len(recent_idx)} 篇)')
    idx.append('')
    idx.append('| # | 标题 | 日期 | 期刊 | COCHE 作者 | 来源 |')
    idx.append('|---|------|------|------|------------|------|')
    for i, p in enumerate(recent_idx, 1):
        doi = p.get('doi', '')
        pmid = p.get('pmid', '')
        link = f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}'
        title = p.get('title', '')
        title_display = title[:70] + ('...' if len(title) > 70 else '')
        date = get_date(p)
        journal = p.get('journal', '')[:28]
        authors = ', '.join(p.get('coche_authors', [])[:2])
        if len(p.get('coche_authors', [])) > 2:
            authors += ' 等'
        sources = p.get('source', [])
        if 'innohk_acknowledgement' in sources:
            src = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
        else:
            src = 'affil'
        idx.append(f'| {i} | [{title_display}]({link}) | {date} | {journal} | {authors or "N/A"} | {src} |')
    idx.append('')

idx.append(f'## 📋 全部论文 ({len(current)} 篇)')
idx.append('')
for year in sorted(year_cnt.keys(), reverse=True):
    yr_papers = [p for p in current if p.get('pub_year') == year]
    idx.append(f'### {year} ({len(yr_papers)} 篇)')
    idx.append('')
    idx.append('| # | 标题 | 日期 | 期刊 | 来源 |')
    idx.append('|---|------|------|------|------|')
    for i, p in enumerate(yr_papers, 1):
        doi = p.get('doi', '')
        pmid = p.get('pmid', '')
        link = f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}'
        title_display = p.get('title', '')[:70] + ('...' if len(p.get('title', '')) > 70 else '')
        date = get_date(p)
        journal = p.get('journal', '')[:26]
        sources = p.get('source', [])
        if 'innohk_acknowledgement' in sources:
            src = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
        else:
            src = 'affil'
        idx.append(f'| {i} | [{title_display}]({link}) | {date} | {journal} | {src} |')
    idx.append('')

idx.append('---')
idx.append('')
idx.append('📥 [下载 Excel](COCHE_Papers.xlsx) | 📄 [下载 JSON](coche_pubmed.json) | 📝 [周报](COCHE_Weekly_Report.md)')
idx.append('')
idx.append('> 🏷️ **来源标注说明**: affil = 机构署名匹配 | InnoHK = InnoHK致谢收录 (ITC KPI 合规) | both = 双通道匹配')
idx.append('')
idx.append(f'*自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} · 双通道搜索 · Powered by PubMed API*')

with open(f'{WORKSPACE}/index.md', 'w') as f:
    f.write('\n'.join(idx))

print(f"  index.md generated")
PYEOF

# Step 5: Save current as previous for next comparison
# ==============================================================
cp "$PUBMED_FILE" "$PREV_FILE"
echo "[$(date '+%H:%M:%S')] Step 5: Saved snapshot for next week" | tee -a "$LOG_FILE"

# ==============================================================
# Step 6: Commit and push to GitHub
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 6: Pushing to GitHub..." | tee -a "$LOG_FILE"
cd "$WORKSPACE"
git add COCHE_Papers.xlsx COCHE_Weekly_Report.md coche_pubmed.json coche_pubmed_previous.json README.md FULL_LIST.md index.md index.html scripts/coche_weekly_update.sh scripts/generate_outputs.py
git commit -m "Weekly COCHE paper update $(date '+%Y-%m-%d')" || echo "  No new changes"
gh auth setup-git -h github.com 2>/dev/null
git push origin main || echo "  Push failed"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === COCHE Weekly Update Complete ===" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
