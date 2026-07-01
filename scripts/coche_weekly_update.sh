#!/bin/bash
# ==============================================================
# COCHE Paper Tracker — Weekly Update Script
# Runs every Monday 9:00 AM Asia/Shanghai via cron
# 1. Fetch latest PubMed papers with COCHE affiliation
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
# Step 1: Fetch from PubMed (all keywords, all variants)
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 1: Fetching PubMed..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
import requests, json, time, xml.etree.ElementTree as ET, os

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

seen_pmids = set()

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
            if pid not in seen_pmids:
                ids.append(pid)
                seen_pmids.add(pid)
        if not idlist or retstart + 500 >= total:
            break
        retstart += 500
        time.sleep(0.4)
    return ids

all_ids = []
for q in AFFILIATION_QUERIES + TEXT_QUERIES:
    ids = fetch_ids(q)
    all_ids.extend(ids)
    time.sleep(0.3)

print(f"  Fetched {len(all_ids)} unique PMIDs")

# Fetch details
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
            authors, coche_authors = [], []
            for author in article.findall('.//Author'):
                last = author.find('./LastName')
                fore = author.find('./ForeName')
                name = f'{fore.text} {last.text}' if fore is not None and last is not None else ''
                affs, in_coche = [], False
                for aff in author.findall('.//AffiliationInfo/Affiliation'):
                    aff_text = aff.text or ''
                    affs.append(aff_text)
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
            
            papers.append({
                'pmid': pmid, 'doi': doi, 'title': title,
                'journal': journal_name, 'pub_year': y, 'pub_month': m, 'pub_day': d,
                'authors': authors, 'coche_authors': coche_authors,
            })
        except:
            continue
    time.sleep(0.5)

# Filter
cleaned = []
for p in papers:
    for a in p.get('authors', []):
        for aff in a.get('affiliations', []):
            if is_coche_affiliation(aff):
                cleaned.append(p)
                break
        else:
            continue
        break

cleaned.sort(key=lambda x: (x.get('pub_year','0'), x.get('pub_month','0'), x.get('pub_day','0')), reverse=True)

# Slim down: keep only author names (not full affiliations) to reduce file size
for p in cleaned:
    p['authors'] = [a.get('name', a) if isinstance(a, dict) else a for a in p.get('authors', [])]
    p.pop('all_affiliations', None)
    p.pop('coche_in_grants', None)

output_path = '/home/ubuntu/.openclaw/workspace/coche_pubmed.json'
with open(output_path, 'w') as f:
    json.dump(cleaned, f, indent=2, ensure_ascii=False)

print(f"  Saved {len(cleaned)} papers to coche_pubmed.json")
PYEOF

echo "[$(date '+%H:%M:%S')] PubMed fetch complete" | tee -a "$LOG_FILE"

# ==============================================================
# Step 2: Compare with previous, identify new papers
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 2: Comparing with previous week..." | tee -a "$LOG_FILE"

python3 << 'PYEOF'
import json, os
from datetime import datetime, timedelta

WORKSPACE = '/home/ubuntu/.openclaw/workspace'

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
    month_map = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
                 'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
    mm = month_map.get(m[:3], '01')
    dd = d.zfill(2)
    date_str = f'{y}-{mm}-{dd}'
    if date_str >= thirty_days_ago:
        recent_papers.append(p)

new_file = f'{WORKSPACE}/coche_new_papers.json'
with open(new_file, 'w') as f:
    json.dump(new_papers, f, indent=2, ensure_ascii=False)

recent_file = f'{WORKSPACE}/coche_recent_30d.json'
with open(recent_file, 'w') as f:
    json.dump(recent_papers, f, indent=2, ensure_ascii=False)

print(f"  New this week: {len(new_papers)}")
print(f"  Recent 30 days: {len(recent_papers)}")
print(f"  Total: {len(current)}")
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
border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
border_bottom = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='medium'))

headers = ['序号', 'PMID', '论文标题', 'DOI', '出版日期', '期刊', 'COCHE 作者', '全部作者', '链接']
for col, h in enumerate(headers, 1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = hdr_font; c.fill = hdr_fill; c.alignment = hdr_align; c.border = border

widths = [5, 10, 55, 30, 12, 30, 30, 50, 35]
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
    
    pmid_str = str(p.get('pmid', ''))
    
    vals = [idx, pmid_str, p.get('title', ''), doi, date_display, 
            p.get('journal', ''), coche_authors, all_authors, link]
    
    is_recent = date_str >= thirty_days_ago
    
    for col, val in enumerate(vals, 1):
        c = ws.cell(row=idx+1, column=col, value=val)
        c.font = Font(size=10)
        c.alignment = Alignment(vertical='top', wrap_text=True)
        c.border = border
        if is_recent:
            c.fill = recent_fill
            c.font = Font(size=10, bold=True)

# Add a legend row at the bottom
legend_row = len(papers) + 3
ws.cell(row=legend_row, column=1, value='🟡').font = Font(size=14)
ws.cell(row=legend_row, column=2, value=f'黄色高亮 = 近30天发表 ({len([p for p in papers if f"{p.get("pub_year","")}-{month_map.get((p.get("pub_month","") or "Jan")[:3],"01")}-{(p.get("pub_day","") or "01").zfill(2)}" >= thirty_days_ago])} 篇)')
ws.merge_cells(start_row=legend_row, start_column=2, end_row=legend_row, end_column=9)

ws.freeze_panes = 'A2'
ws.auto_filter.ref = ws.dimensions

output_path = f'{WORKSPACE}/COCHE_Papers.xlsx'
wb.save(output_path)
print(f"  Excel saved: {output_path}")
PYEOF

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

now = datetime.now()
report = []
report.append(f"# COCHE Paper Tracker — Weekly Report")
report.append(f"**更新时间**: {now.strftime('%Y-%m-%d %H:%M')} (Asia/Shanghai)")
report.append(f"")
report.append(f"## 📊 概要")
report.append(f"- **COCHE 论文总数**: {len(current)} 篇")
report.append(f"- **本周新增**: {len(new_papers)} 篇")
report.append(f"- **近30天发表**: {len(recent_papers)} 篇")
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
        report.append(f"**{i}. {p.get('title', '')}**")
        report.append(f"- 📅 {date_str} | 📰 {p.get('journal', '')}")
        report.append(f"- 👤 COCHE Authors: {coche_authors or 'N/A'}")
        report.append(f"- 🔗 [{link}]({link})")
        report.append(f"")

if recent_papers:
    report.append(f"## 🟡 近30天发表 ({len(recent_papers)} 篇)")
    report.append(f"")
    report.append(f"| # | 标题 | 日期 | 期刊 | COCHE 作者 |")
    report.append(f"|---|------|------|------|------------|")
    for i, p in enumerate(recent_papers[:30], 1):  # max 30 in table
        date_str = f"{p.get('pub_year','')}-{p.get('pub_month','')}-{p.get('pub_day','')}".strip('-')
        title = p.get('title', '')[:60] + ('...' if len(p.get('title', '')) > 60 else '')
        coche_authors = ', '.join(p.get('coche_authors', [])[:2])
        if len(p.get('coche_authors', [])) > 2:
            coche_authors += ' 等'
        report.append(f"| {i} | {title} | {date_str} | {p.get('journal', '')[:25]} | {coche_authors or 'N/A'} |")
    if len(recent_papers) > 30:
        report.append(f"| ... | ... | ... | ... | ... |")
    report.append(f"")

report.append(f"---")
report.append(f"*自动生成于 {now.strftime('%Y-%m-%d %H:%M:%S')} | 数据来源: PubMed API*")

with open(f'{WORKSPACE}/COCHE_Weekly_Report.md', 'w') as f:
    f.write('\n'.join(report))

print(f"  Report saved")

# ==============================================================
# Generate index.md for GitHub Pages rendering
# ==============================================================
from collections import Counter
from datetime import datetime, timedelta

thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

def get_date(p):
    y = p.get('pub_year', '')
    m = p.get('pub_month', '') or 'Jan'
    d = p.get('pub_day', '') or '01'
    mm = month_map.get(m[:3], '01')
    return f'{y}-{mm.zfill(2)}-{d.zfill(2)}'

recent_idx = []
older_idx = []
for p in current:
    if get_date(p) >= thirty_days_ago:
        recent_idx.append(p)
    else:
        older_idx.append(p)

year_cnt = Counter(p.get('pub_year', '?') for p in current)

idx = []
idx.append('# COCHE Paper Tracker')
idx.append('')
idx.append(f'> **Hong Kong Centre for Cerebro-Cardiovascular Health Engineering**')
idx.append(f'> 每周一自动更新 | 数据来源: PubMed API')
idx.append(f'')
idx.append(f'📊 **总论文数: {len(current)} 篇** | 🆕 近30天: {len(recent_idx)} 篇 | ⏰ 更新: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
idx.append('')
idx.append('---')
idx.append('')

if recent_idx:
    idx.append(f'## 🟡 近30天发表 ({len(recent_idx)} 篇)')
    idx.append('')
    idx.append('| # | 标题 | 日期 | 期刊 | COCHE 作者 |')
    idx.append('|---|------|------|------|------------|')
    for i, p in enumerate(recent_idx, 1):
        doi = p.get('doi', '')
        pmid = p.get('pmid', '')
        link = f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}'
        title = p.get('title', '')
        title_display = title[:75] + ('...' if len(title) > 75 else '')
        date = get_date(p)
        journal = p.get('journal', '')[:30]
        authors = ', '.join(p.get('coche_authors', [])[:2])
        if len(p.get('coche_authors', [])) > 2:
            authors += ' 等'
        idx.append(f'| {i} | [{title_display}]({link}) | {date} | {journal} | {authors or "N/A"} |')
    idx.append('')

idx.append(f'## 📋 全部论文 ({len(current)} 篇)')
idx.append('')
for year in sorted(year_cnt.keys(), reverse=True):
    yr_papers = [p for p in current if p.get('pub_year') == year]
    idx.append(f'### {year} ({len(yr_papers)} 篇)')
    idx.append('')
    idx.append('| # | 标题 | 日期 | 期刊 |')
    idx.append('|---|------|------|------|')
    for i, p in enumerate(yr_papers, 1):
        doi = p.get('doi', '')
        pmid = p.get('pmid', '')
        link = f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}'
        title_display = p.get('title', '')[:75] + ('...' if len(p.get('title', '')) > 75 else '')
        date = get_date(p)
        journal = p.get('journal', '')[:28]
        idx.append(f'| {i} | [{title_display}]({link}) | {date} | {journal} |')
    idx.append('')

idx.append('---')
idx.append('')
idx.append(f'📥 [下载 Excel](COCHE_Papers.xlsx) | 📄 [下载 JSON](coche_pubmed.json) | 📝 [周报](COCHE_Weekly_Report.md)')
idx.append('')
idx.append(f'*自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} · Powered by PubMed API*')

with open(f'{WORKSPACE}/index.md', 'w') as f:
    f.write('\n'.join(idx))

print(f"  index.md generated")
PYEOF

# ==============================================================
# Step 5: Save current as previous for next comparison
# ==============================================================
cp "$PUBMED_FILE" "$PREV_FILE"
echo "[$(date '+%H:%M:%S')] Step 5: Saved snapshot for next week" | tee -a "$LOG_FILE"

# ==============================================================
# Step 6: Commit and push to GitHub
# ==============================================================
echo "[$(date '+%H:%M:%S')] Step 6: Pushing to GitHub..." | tee -a "$LOG_FILE"
cd "$WORKSPACE"
git add COCHE_Papers.xlsx COCHE_Weekly_Report.md coche_pubmed.json coche_pubmed_previous.json index.html .nojekyll scripts/coche_weekly_update.sh
git commit -m "Weekly COCHE paper update $(date '+%Y-%m-%d')" || echo "  No new changes"
gh auth setup-git -h github.com 2>/dev/null
git push origin main || echo "  Push failed"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === COCHE Weekly Update Complete ===" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
