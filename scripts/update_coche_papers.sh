#!/bin/bash
# COCHE Paper Tracker - Weekly Update Script
# Uses PubMed (NCBI) API + OpenAlex API to fetch COCHE-affiliated papers

set -e

WORKSPACE_DIR="/home/ubuntu/.openclaw/workspace"
PREVIOUS_PUBMED="$WORKSPACE_DIR/coche_pubmed_previous.json"
PUBMED_FILE="$WORKSPACE_DIR/coche_pubmed.json"
OA_FILE="$WORKSPACE_DIR/coche_papers.json"
EXCEL_FILE="$WORKSPACE_DIR/COCHE_Papers.xlsx"
REPORT_FILE="$WORKSPACE_DIR/coche_weekly_report.md"
TIMESTAMP=$(date '+%Y-%m-%dT%H:%M:%SZ')

echo "[$(date)] Starting COCHE paper tracker update..."

# Step 1: Fetch from PubMed
python3 << 'PYEOF'
import requests, json, time, xml.etree.ElementTree as ET

query = '(Hong Kong Centre for Cerebro-cardiovascular Health Engineering[Affiliation] OR Hong Kong Center for Cerebro-cardiovascular Health Engineering[Affiliation] OR COCHE[Affiliation])'

# Get all IDs
all_ids = []
retstart = 0
while True:
    resp = requests.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi', params={
        'db': 'pubmed', 'term': query, 'retstart': retstart,
        'retmax': 500, 'retmode': 'json', 'sort': 'date'
    }, timeout=15)
    data = resp.json()
    ids = data.get('esearchresult', {}).get('idlist', [])
    total = int(data.get('esearchresult', {}).get('count', '0'))
    all_ids.extend(ids)
    if len(all_ids) >= total:
        break
    retstart += 500
    time.sleep(0.5)

# Fetch details
papers = []
for i in range(0, len(all_ids), 100):
    batch = all_ids[i:i+100]
    resp = requests.post('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi', data={
        'db': 'pubmed', 'id': ','.join(batch),
        'retmode': 'xml', 'rettype': 'abstract'
    }, timeout=30)
    
    root = ET.fromstring(resp.content)
    for article in root.findall('.//PubmedArticle'):
        try:
            pmid = article.find('.//PMID').text
            title_elem = article.find('.//ArticleTitle')
            title = title_elem.text if title_elem is not None else ''
            
            authors = []
            coche_authors = []
            for author in article.findall('.//Author'):
                last = author.find('./LastName')
                fore = author.find('./ForeName')
                name = f'{fore.text} {last.text}' if fore is not None and last is not None else ''
                
                affs = []
                in_coche = False
                for aff in author.findall('.//AffiliationInfo/Affiliation'):
                    aff_text = aff.text or ''
                    affs.append(aff_text)
                    if 'cerebro-cardiovascular' in aff_text.lower() or 'cerebrocardiovascular' in aff_text.lower() or 'coche' in aff_text.lower():
                        in_coche = True
                authors.append({'name': name.strip(), 'affiliations': affs})
                if in_coche:
                    coche_authors.append(name.strip())
            
            journal = article.find('.//Journal/Title')
            journal_name = journal.text if journal is not None else ''
            doi_elem = article.find('.//ArticleId[@IdType="doi"]')
            doi = doi_elem.text if doi_elem is not None else ''
            pub_date = article.find('.//PubDate')
            year = pub_date.find('Year')
            year = year.text if year is not None else ''
            month = pub_date.find('Month')
            month = month.text if month is not None else ''
            day = pub_date.find('Day')
            day = day.text if day is not None else ''
            
            papers.append({
                'pmid': pmid, 'doi': doi, 'title': title,
                'journal': journal_name, 'pub_year': year,
                'pub_month': month, 'pub_day': day,
                'authors': authors, 'coche_authors': coche_authors
            })
        except:
            continue
    time.sleep(0.5)

papers.sort(key=lambda x: x.get('pub_year', ''), reverse=True)

# Clean: remove non-COCHE papers (Venezuela hospital, Belgian author "Coche", etc.)
import re
def is_coche_affiliation(aff_text):
    aff = aff_text.lower()
    has_coche_term = any(t in aff for t in [
        'cerebro-cardiovascular health engineering',
        'cerebrocardiovascular health engineering',
        'cerebro-cardiovascular health',
        'coche',
    ])
    has_hk_context = any(t in aff for t in [
        'hong kong', 'hongkong', 'shatin', 'kowloon', 'cityu', 'city university',
        'oxford-cityu', 'hk science', 'hksar',
    ])
    is_venezuela = any(t in aff for t in ['venezuela', 'caracas', 'periferico', 'periférico'])
    return has_coche_term and has_hk_context and not is_venezuela

cleaned = []
removed = 0
for p in papers:
    is_real = any(is_coche_affiliation(aff) for a in p.get('authors', []) for aff in a.get('affiliations', []))
    if is_real:
        cleaned.append(p)
    else:
        removed += 1

with open('/home/ubuntu/.openclaw/workspace/coche_pubmed.json', 'w') as f:
    json.dump(cleaned, f, indent=2, ensure_ascii=False)

print(f'PubMed: {len(cleaned)} papers (removed {removed} non-COCHE)')
PYEOF

# Step 2: Enrich with Semantic Scholar citations
python3 << 'PYEOF'
import json, time, urllib.request, urllib.error, os

S2_KEY = '***'
BATCH_SIZE = 20
PUBMED_FILE = os.path.expanduser('~/.openclaw/workspace/coche_pubmed.json')
S2_FILE = os.path.expanduser('~/.openclaw/workspace/coche_s2_citations.json')

with open(PUBMED_FILE) as f:
    papers = json.load(f)

# Load existing S2 data
enriched = []
existing = {}
if os.path.exists(S2_FILE):
    with open(S2_FILE) as f:
        existing_list = json.load(f)
        existing = {p.get('pmid', ''): p for p in existing_list}

for p in papers:
    pmid = p.get('pmid', '')
    doi = p.get('doi', '')
    if pmid in existing and existing[pmid].get('s2_citations') is not None:
        enriched.append(existing[pmid])
    else:
        enriched.append({'pmid': pmid, 'doi': doi, 'title': p.get('title', ''), 's2_citations': None, 's2_paper_id': None})

todo = [(e['pmid'], e['doi']) for e in enriched if e['s2_citations'] is None and e['doi']]
print(f'S2 enrichment: {len(todo)} papers to look up')

for i in range(0, len(todo), BATCH_SIZE):
    batch = todo[i:i+BATCH_SIZE]
    ids = [f'DOI:{doi}' for _, doi in batch]
    data = json.dumps({'ids': ids}).encode()
    req = urllib.request.Request(
        'https://api.semanticscholar.org/graph/v1/paper/batch?fields=citationCount,paperId',
        data=data,
        headers={'x-api-key': S2_KEY, 'Content-Type': 'application/json'}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        results = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(35)
            i -= BATCH_SIZE
            continue
        break
    result_map = {}
    for r in (results or []):
        if r:
            ext = r.get('externalIds', {}) or {}
            d = ext.get('DOI', '').lower()
            if d:
                result_map[d] = r
    for pmid, doi in batch:
        r = result_map.get(doi.lower(), {})
        for e in enriched:
            if e['pmid'] == pmid:
                e['s2_citations'] = r.get('citationCount')
                e['s2_paper_id'] = r.get('paperId', '')
                break
    time.sleep(2.5)

with open(S2_FILE, 'w') as f:
    json.dump(enriched, f, indent=2)
    
with_cit = sum(1 for e in enriched if e['s2_citations'] is not None)
print(f'S2 done: {with_cit}/{len(enriched)} papers with citations')
PYEOF

# Step 3: Fetch from OpenAlex (for citation counts and OA info)
python3 << 'PYEOF'
import requests, json, time

all_papers = {}
seen_ids = set()
search_terms = [
    'Hong Kong Centre for Cerebro-cardiovascular Health Engineering',
    'Hong Kong Center for Cerebro-cardiovascular Health Engineering',
    'Hong Kong Centre for Cerebrocardiovascular Health Engineering',
    'Hong Kong Center for Cerebrocardiovascular Health Engineering',
    'Cerebro-Cardiovascular Health Engineering Hong Kong',
]

for query in search_terms:
    page = 1
    while True:
        try:
            resp = requests.get('https://api.openalex.org/works', params={
                'search': query, 'per_page': 200,
                'sort': 'publication_date:desc', 'page': page
            }, timeout=30)
            if resp.status_code != 200:
                break
        except:
            break
        data = resp.json()
        results = data.get('results', [])
        if not results:
            break
        for w in results:
            wid = w.get('id')
            if wid in seen_ids:
                continue
            has_coche = False
            for a in w.get('authorships', []):
                for aff in a.get('raw_affiliation_strings', []):
                    afl = aff.lower()
                    if 'cerebro-cardiovascular' in afl or 'cerebrocardiovascular' in afl or 'coche' in afl:
                        has_coche = True
                        break
                if has_coche:
                    break
            if not has_coche:
                continue
            seen_ids.add(wid)
            doi = w.get('doi', '')
            all_papers[doi.replace('https://doi.org/', '')] = {
                'doi': doi, 'title': w.get('title', ''),
                'publication_date': w.get('publication_date', ''),
                'publication_year': w.get('publication_year', None),
                'cited_by_count': w.get('cited_by_count', 0),
                'source': (w.get('primary_location', {}) or {}).get('source', {}).get('display_name', '') if w.get('primary_location') else '',
                'landing_page': (w.get('primary_location', {}) or {}).get('landing_page_url', ''),
                'is_oa': w.get('open_access', {}).get('is_oa', False),
                'oa_url': w.get('open_access', {}).get('oa_url', '') if w.get('open_access', {}).get('is_oa') else '',
                'pmid': w.get('ids', {}).get('pmid', ''),
                'type': w.get('type', ''),
                'coche_authors': []
            }
            for a in w.get('authorships', []):
                for aff in a.get('raw_affiliation_strings', []):
                    if 'cerebro-cardiovascular' in aff.lower() or 'cerebrocardiovascular' in aff.lower() or 'coche' in aff.lower():
                        all_papers[doi.replace('https://doi.org/', '')]['coche_authors'].append(
                            a.get('author', {}).get('display_name', ''))
                        break
        if len(results) < 200:
            break
        page += 1
        time.sleep(0.3)

sorted_papers = sorted(all_papers.values(), key=lambda x: x.get('publication_date', '') or '', reverse=True)
output = {
    'source': 'OpenAlex API',
    'total_papers': len(sorted_papers),
    'fetched_at': '"$TIMESTAMP"',
    'papers': sorted_papers
}
with open('/home/ubuntu/.openclaw/workspace/coche_papers.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f'OpenAlex: {len(sorted_papers)} papers')
PYEOF

# Step 4: Merge and generate Excel
python3 << 'PYEOF'
import json
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

with open('/home/ubuntu/.openclaw/workspace/coche_pubmed.json') as f:
    pubmed = json.load(f)
with open('/home/ubuntu/.openclaw/workspace/coche_papers.json') as f:
    oa_data = json.load(f)

oa_by_doi = {}
for p in oa_data['papers']:
    d = p.get('doi', '').replace('https://doi.org/', '')
    if d:
        oa_by_doi[d] = p

merged = []
for p in pubmed:
    doi = p.get('doi', '')
    oa = oa_by_doi.get(doi, {})
    merged.append({
        'pmid': p.get('pmid', ''),
        'doi': doi,
        'title': p.get('title', ''),
        'journal': p.get('journal', ''),
        'pub_year': p.get('pub_year', ''),
        'pub_month': p.get('pub_month', ''),
        'pub_day': p.get('pub_day', ''),
        'coche_authors': ', '.join(p.get('coche_authors', [])),
        'authors': ', '.join([a['name'] for a in p.get('authors', [])[:10]]),
        'cited_by': oa.get('cited_by_count', 0),
        'oa_status': '🔓 OA' if oa.get('is_oa') else ('🔒 非OA' if oa else ''),
        'landing_page': oa.get('landing_page', ''),
        'oa_url': oa.get('oa_url', ''),
        'source_db': 'PubMed + OpenAlex' if oa else 'PubMed',
    's2_citations': None
    })

merged.sort(key=lambda x: x.get('pub_year', ''), reverse=True)

wb = Workbook()
ws = wb.active
ws.title = "COCHE Papers"

header_font = Font(bold=True, size=11, color="FFFFFF")
header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

headers = ["序号","PMID","论文标题","DOI","出版日期","期刊","COCHE 作者","全部作者","被引次数","OA状态","链接"]
for col, h in enumerate(headers, 1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = header_font; c.fill = header_fill; c.alignment = header_align; c.border = border

widths = [5,10,50,30,12,25,25,50,8,8,30]
for i,w in enumerate(widths,1):
    ws.column_dimensions[ws.cell(row=1,column=i).column_letter].width = w

for idx, p in enumerate(merged, 1):
    date = f"{p['pub_year']}-{p['pub_month']}-{p['pub_day']}".strip('-')
    vals = [idx, p['pmid'], p['title'], p['doi'], date, p['journal'],
            p['coche_authors'], p['authors'], p['cited_by'], p['oa_status'], p['landing_page']]
    for col, val in enumerate(vals, 1):
        c = ws.cell(row=idx+1, column=col, value=val)
        c.font = Font(size=10); c.alignment = Alignment(vertical="top", wrap_text=True); c.border = border

ws.freeze_panes = 'A2'
ws.auto_filter.ref = ws.dimensions
# Add S2 citations
s2_map = {}
s2_file = '/home/ubuntu/.openclaw/workspace/coche_s2_citations.json'
if __import__('os').path.exists(s2_file):
    with open(s2_file) as f:
        s2_data = json.load(f)
    s2_map = {e['pmid']: e for e in s2_data}

for p in merged:
    s2 = s2_map.get(p['pmid'], {})
    p['s2_citations'] = s2.get('s2_citations')

# Update worksheet columns to include S2 citations
# Redo the worksheet with new header
ws.delete_rows(1, ws.max_row)

headers = ['序号','PMID','论文标题','DOI','出版日期','期刊','COCHE 作者','全部作者','S2 引用数','OA状态','链接']
for col, h in enumerate(headers, 1):
    c = ws.cell(row=1, column=col, value=h)
    c.font = header_font; c.fill = header_fill; c.alignment = header_align; c.border = border

widths = [5,10,50,30,12,25,25,45,9,9,30]
for i,w in enumerate(widths,1):
    ws.column_dimensions[ws.cell(row=1,column=i).column_letter].width = w

for idx, p in enumerate(merged, 1):
    date = f"{p['pub_year']}-{p['pub_month']}-{p['pub_day']}".strip('-')
    vals = [idx, p['pmid'], p['title'], p['doi'], date, p['journal'],
            p['coche_authors'], p['authors'], p.get('s2_citations', ''), p['oa_status'], p['landing_page']]
    for col, val in enumerate(vals, 1):
        c = ws.cell(row=idx+1, column=col, value=val)
        c.font = Font(size=10); c.alignment = Alignment(vertical='top', wrap_text=True); c.border = border

ws.freeze_panes = 'A2'
ws.auto_filter.ref = ws.dimensions
wb.save('/home/ubuntu/.openclaw/workspace/COCHE_Papers.xlsx')

# Detect new papers
new_count = 0
new_papers = []
if __import__('os').path.exists('/home/ubuntu/.openclaw/workspace/coche_pubmed_previous.json'):
    with open('/home/ubuntu/.openclaw/workspace/coche_pubmed_previous.json') as f:
        prev = json.load(f)
    prev_pmids = {p.get('pmid') for p in prev}
    current_pmids = {p.get('pmid') for p in pubmed}
    new_pmids = current_pmids - prev_pmids
    new_papers = [p for p in merged if p['pmid'] in new_pmids]
    new_count = len(new_papers)

# Generate report
report = [f"# COCHE Paper Tracker - Weekly Update\n**Date**: {len(pubmed)}\n"]
report.append(f"## Summary")
report.append(f"- **Total COCHE papers**: {len(pubmed)} (PubMed) + {oa_data['total_papers']} (OpenAlex)")
report.append(f"- **New this week**: {new_count}\n")

if new_papers:
    report.append(f"## New Papers ({new_count})\n")
    for i, p in enumerate(new_papers, 1):
        report.append(f"**{i}. {p['title']}**")
        report.append(f"- DOI: {p['doi'] or 'N/A'}")
        report.append(f"- Journal: {p['journal']}")
        report.append(f"- COCHE Authors: {p['coche_authors']}")
        report.append(f"- Date: {p['pub_year']}-{p['pub_month']}")
        if p['landing_page']:
            report.append(f"- Link: {p['landing_page']}")
        report.append("")
else:
    report.append("No new COCHE papers this week.\n")

with open('/home/ubuntu/.openclaw/workspace/coche_weekly_report.md', 'w') as f:
    f.write('\n'.join(report))

print(f'Merged: {len(merged)} papers | New: {new_count}')
PYEOF

# Step 4: Save current as previous for next comparison
cp /home/ubuntu/.openclaw/workspace/coche_pubmed.json /home/ubuntu/.openclaw/workspace/coche_pubmed_previous.json

echo "[$(date)] Update complete."
