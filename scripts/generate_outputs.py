#!/usr/bin/env python3
"""
generate_outputs.py — Deterministic output generator for COCHE Paper Tracker
Reads coche_pubmed.json and produces ALL output files:
  README.md, FULL_LIST.md, COCHE_Weekly_Report.md, COCHE_Papers.xlsx, index.md

Usage: python3 scripts/generate_outputs.py [--workspace /path/to/workspace]

Rules (DO NOT MODIFY):
  - All dates are extracted from JSON fields as-is
  - Sorting: by pub_year DESC, pub_month DESC, pub_day DESC
  - "Recent 30 days" = papers where date >= (today - 30 days)
  - Supports "source" field: 'affiliation' and/or 'innohk_acknowledgement'
  - This script contains ZERO LLM-generated content — only deterministic logic
"""

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta

WORKSPACE = os.environ.get('COCHE_WORKSPACE', '/home/ubuntu/.openclaw/workspace')
args = sys.argv[1:]
for i, arg in enumerate(args):
    if arg == '--workspace' and i + 1 < len(args):
        WORKSPACE = args[i + 1]

PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')
PREV_FILE = os.path.join(WORKSPACE, 'coche_pubmed_previous.json')
README_FILE = os.path.join(WORKSPACE, 'README.md')
FULL_LIST_FILE = os.path.join(WORKSPACE, 'FULL_LIST.md')
REPORT_FILE = os.path.join(WORKSPACE, 'COCHE_Weekly_Report.md')
EXCEL_FILE = os.path.join(WORKSPACE, 'COCHE_Papers.xlsx')
INDEX_FILE = os.path.join(WORKSPACE, 'index.md')

MONTH_MAP = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
             'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}

def load_papers():
    with open(PUBMED_FILE, 'r') as f:
        papers = json.load(f)
    month_order = {'Jan':0,'Feb':1,'Mar':2,'Apr':3,'May':4,'Jun':5,
                   'Jul':6,'Aug':7,'Sep':8,'Oct':9,'Nov':10,'Dec':11}
    papers.sort(key=lambda p: (
        -int(p.get('pub_year','0') or '0'),
        -month_order.get((p.get('pub_month','Jan') or 'Jan')[:3], 0),
        -int((p.get('pub_day','01') or '01'))
    ))
    return papers

def format_date(p):
    y = p.get('pub_year','') or ''
    m = (p.get('pub_month','') or 'Jan')[:3]
    d = (p.get('pub_day','') or '01').zfill(2)
    mm = MONTH_MAP.get(m, '01')
    return f'{y}-{mm}-{d}'

def format_link(p):
    doi = p.get('doi','')
    if doi: return f'https://doi.org/{doi}'
    return f'https://pubmed.ncbi.nlm.nih.gov/{p["pmid"]}'

def format_authors(p, max_n=3, suffix=' et al.'):
    authors = p.get('coche_authors', [])
    if not authors: return 'N/A'
    shown = ','.join(authors[:max_n])
    if len(authors) > max_n: return f'{shown}{suffix}'
    return shown

def is_recent(p, threshold_date):
    return format_date(p) >= threshold_date

def generate_readme(papers, recent, now):
    affil_count = sum(1 for p in papers if 'affiliation' in p.get('source', []))
    innohk_count = sum(1 for p in papers if 'innohk_acknowledgement' in p.get('source', []))
    lines = []
    lines.append('# 🧠 COCHE Paper Tracker')
    lines.append('')
    lines.append('> **Hong Kong Centre for Cerebro-Cardiovascular Health Engineering**  ')
    lines.append('> 双通道搜索: 机构署名 (affiliation) + InnoHK 致谢 (ITC KPI 合规)')
    lines.append(f'> 📊 **{len(papers)} papers** | 🏷 InnoHK收录: {innohk_count} | 🆕 **{len(recent)} past 30d** | ⏰ {now.strftime("%Y-%m-%d %H:%M")} UTC+8')
    lines.append('')
    lines.append('📥 [Excel](COCHE_Papers.xlsx) | [JSON](coche_pubmed.json) | [Full Table](FULL_LIST.md) | [Report](COCHE_Weekly_Report.md)')
    lines.append('')
    lines.append('---')
    lines.append('')
    if recent:
        lines.append(f'## 🟡 Past 30 Days ({len(recent)})')
        lines.append('')
        for i, p in enumerate(recent, 1):
            sources = p.get('source', [])
            tag = ' 🏷️' if 'innohk_acknowledgement' in sources and 'affiliation' not in sources else ''
            lines.append(f'{i}. **[{p["title"]}]({format_link(p)})**{tag}')
            lines.append(f'   - 📅 {format_date(p)} | 📰 {(p.get("journal","") or "N/A")[:40]} | 👤 {format_authors(p)}')
        lines.append('')
    year_counts = Counter(p['pub_year'] for p in papers)
    lines.append('## 📋 All by Year')
    lines.append('')
    for year in sorted(year_counts.keys(), reverse=True):
        yr_papers = [p for p in papers if p['pub_year'] == year]
        yr_recent = sum(1 for p in yr_papers if is_recent(p, threshold_str))
        yr_innohk = sum(1 for p in yr_papers if 'innohk_acknowledgement' in p.get('source', []))
        badge = ''
        if yr_recent: badge += f' 🆕{yr_recent}'
        if yr_innohk: badge += f' 🏷{yr_innohk}'
        lines.append(f'<details>')
        lines.append(f'<summary><b>{year}</b> — {len(yr_papers)} papers{badge}</summary>')
        lines.append('')
        for i, p in enumerate(yr_papers, 1):
            sources = p.get('source', [])
            tag = ' 🏷' if 'innohk_acknowledgement' in sources else ''
            lines.append(f'{i}. [{p["title"]}]({format_link(p)}) — *{(p.get("journal","") or "N/A")[:30]}* ({format_date(p)}){tag}')
        lines.append('')
        lines.append('</details>')
        lines.append('')
    lines.append('---')
    lines.append('*Auto-updated weekly via PubMed API (dual-channel: affiliation + InnoHK acknowledgement) — all dates are first-published*')
    lines.append('')
    return '\n'.join(lines)

def generate_full_list(papers, now):
    lines = []
    lines.append('# COCHE All Papers')
    lines.append('')
    lines.append(f'> 📊 **{len(papers)}** papers | ⏰ {now.strftime("%Y-%m-%d %H:%M")} UTC+8 | [Home](README.md)')
    lines.append(f'> 搜索策略: 机构署名 + InnoHK 致谢 (ITC KPI 合规)')
    lines.append('')
    lines.append('---')
    lines.append('')
    year_counts = Counter(p['pub_year'] for p in papers)
    for year in sorted(year_counts.keys(), reverse=True):
        yr_papers = [p for p in papers if p['pub_year'] == year]
        lines.append(f'## {year} ({len(yr_papers)})')
        lines.append('')
        lines.append('| # | Title | Date | Journal | COCHE Authors | Source | PMID |')
        lines.append('|---|---|---|---|---|---|---|')
        for i, p in enumerate(yr_papers, 1):
            title_escaped = p['title'].replace('|', '\\|')
            sources = p.get('source', [])
            if 'innohk_acknowledgement' in sources:
                src = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
            else:
                src = 'affil'
            lines.append(f'| {i} | [{title_escaped[:100]}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:30]} | {format_authors(p, 99, "")} | {src} | {p["pmid"]} |')
        lines.append('')
    lines.append(f'---')
    lines.append(f'*Generated {now.strftime("%Y-%m-%d %H:%M:%S")} · Dual-channel search · All dates are first-published*')
    lines.append('')
    return '\n'.join(lines)

def generate_report(papers, recent, now):
    affil_count = sum(1 for p in papers if 'affiliation' in p.get('source', []))
    innohk_count = sum(1 for p in papers if 'innohk_acknowledgement' in p.get('source', []))
    innohk_only = sum(1 for p in papers if p.get('source') == ['innohk_acknowledgement'])
    lines = []
    lines.append(f'# COCHE Weekly Report')
    lines.append('')
    lines.append(f'**{now.strftime("%Y-%m-%d %H:%M")}** UTC+8')
    lines.append('')
    lines.append('## Summary')
    lines.append(f'- Total: {len(papers)} (affiliation: {affil_count} | InnoHK ack: {innohk_count} | InnoHK-only: {innohk_only})')
    lines.append(f'- Past 30d: {len(recent)}')
    lines.append('')
    lines.append('## Search Strategy')
    lines.append('Dual-channel search for ITC KPI compliance:')
    lines.append('1. Affiliation: COCHE/Cerebro-Cardiovascular Health Engineering + Hong Kong')
    lines.append('2. Acknowledgement: InnoHK + ITC/HKSAR Government')
    lines.append('')
    if recent:
        lines.append('## 🟡 Past 30 Days')
        lines.append('')
        lines.append('| # | Title | Date | Journal | COCHE Authors | Source |')
        lines.append('|---|---|---|---|---|---|')
        for i, p in enumerate(recent, 1):
            sources = p.get('source', [])
            if 'innohk_acknowledgement' in sources:
                src_label = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
            else:
                src_label = 'affil'
            lines.append(f'| {i} | [{p["title"][:60]}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:25]} | {format_authors(p, 2, " …")} | {src_label} |')
        lines.append('')
    lines.append('---')
    lines.append(f'*Generated {now.strftime("%Y-%m-%d %H:%M:%S")} · Dual-channel: affiliation + InnoHK*')
    lines.append('')
    return '\n'.join(lines)

def generate_index(papers, recent, now):
    innohk_count = sum(1 for p in papers if 'innohk_acknowledgement' in p.get('source', []))
    lines = []
    lines.append('# COCHE Paper Tracker')
    lines.append('')
    lines.append('> **Hong Kong Centre for Cerebro-Cardiovascular Health Engineering**')
    lines.append('> Weekly auto-update · Data: PubMed API · Dual-channel: affiliation + InnoHK')
    lines.append('')
    lines.append(f'📊 **Total: {len(papers)}** | 🏷 InnoHK: {innohk_count} | 🆕 Past 30d: {len(recent)} | ⏰ {now.strftime("%Y-%m-%d %H:%M")}')
    lines.append('')
    lines.append('---')
    lines.append('')
    if recent:
        lines.append(f'## 🟡 Past 30 Days ({len(recent)})')
        lines.append('')
        lines.append('| # | Title | Date | Journal | COCHE Authors | Source |')
        lines.append('|---|---|---|---|---|---|')
        for i, p in enumerate(recent, 1):
            title = p['title'][:70] + ('...' if len(p['title']) > 70 else '')
            sources = p.get('source', [])
            if 'innohk_acknowledgement' in sources:
                src = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
            else:
                src = 'affil'
            lines.append(f'| {i} | [{title}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:28]} | {format_authors(p, 2, " 等")} | {src} |')
        lines.append('')
    year_counts = Counter(p['pub_year'] for p in papers)
    lines.append(f'## 📋 Full List ({len(papers)})')
    lines.append('')
    for year in sorted(year_counts.keys(), reverse=True):
        yr_papers = [p for p in papers if p['pub_year'] == year]
        lines.append(f'### {year} ({len(yr_papers)})')
        lines.append('')
        lines.append('| # | Title | Date | Journal | Source |')
        lines.append('|---|---|---|---|---|')
        for i, p in enumerate(yr_papers, 1):
            title = p['title'][:70] + ('...' if len(p['title']) > 70 else '')
            sources = p.get('source', [])
            if 'innohk_acknowledgement' in sources:
                src = '🏷 InnoHK' if 'affiliation' not in sources else 'both'
            else:
                src = 'affil'
            lines.append(f'| {i} | [{title}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:26]} | {src} |')
        lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('📥 [Excel](COCHE_Papers.xlsx) | 📄 [JSON](coche_pubmed.json) | 📝 [Report](COCHE_Weekly_Report.md)')
    lines.append('')
    lines.append('> 🏷️ affil = affiliation match | InnoHK = acknowledgement match (ITC KPI compliant) | both = matched both')
    lines.append('')
    lines.append(f'*{now.strftime("%Y-%m-%d %H:%M:%S")} · PubMed API · Dual-channel search*')
    lines.append('')
    return '\n'.join(lines)

def generate_excel(papers, threshold_str):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    wb = Workbook()
    ws = wb.active
    ws.title = 'COCHE Papers'
    hdr_font = Font(bold=True, size=11, color='FFFFFF')
    hdr_fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
    hdr_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    yellow_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')
    green_fill = PatternFill(start_color='D9EAD3', end_color='D9EAD3', fill_type='solid')
    thin_border = Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
    headers = ['#','PMID','Title','DOI','First Published','Journal','COCHE Authors','Source','All Authors','Link']
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = hdr_font; c.fill = hdr_fill; c.alignment = hdr_align; c.border = thin_border
    col_widths = [5, 10, 55, 30, 14, 30, 30, 22, 50, 35]
    for i,w in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    for idx, p in enumerate(papers, 1):
        date_str = format_date(p)
        link = format_link(p)
        coche_auth = ', '.join(p.get('coche_authors', []))
        all_auth = ', '.join(str(a) for a in p.get('authors', [])[:8])
        if len(p.get('authors', [])) > 8: all_auth += ' ...'
        # Source label
        sources = p.get('source', [])
        if 'affiliation' in sources and 'innohk_acknowledgement' in sources:
            source_label = 'affiliation + InnoHK'
        elif 'innohk_acknowledgement' in sources:
            source_label = 'InnoHK acknowledgement'
        elif 'affiliation' in sources:
            source_label = 'affiliation'
        else:
            source_label = 'unknown'
        row_data = [idx, p['pmid'], p['title'], p.get('doi',''), date_str, p.get('journal',''), coche_auth, source_label, all_auth, link]
        is_rec = date_str >= threshold_str
        is_innohk_only = p.get('source') == ['innohk_acknowledgement']
        for col, val in enumerate(row_data, 1):
            c = ws.cell(row=idx + 1, column=col, value=val)
            c.font = Font(size=10, bold=is_rec); c.alignment = Alignment(vertical='top', wrap_text=True); c.border = thin_border
            if is_rec:
                c.fill = yellow_fill
            elif is_innohk_only:
                c.fill = green_fill
    legend_row = len(papers) + 3
    ws.cell(row=legend_row, column=1, value='🟡').font = Font(size=14)
    recent_count = len([p for p in papers if format_date(p) >= threshold_str])
    ws.cell(row=legend_row, column=2, value=f'Yellow = past 30 days ({recent_count} papers)')
    ws.merge_cells(start_row=legend_row, start_column=2, end_row=legend_row, end_column=10)
    legend_row2 = legend_row + 1
    innohk_only_count = sum(1 for p in papers if p.get('source') == ['innohk_acknowledgement'])
    ws.cell(row=legend_row2, column=1, value='🟢').font = Font(size=14)
    ws.cell(row=legend_row2, column=2, value=f'Green = InnoHK acknowledgement only (no COCHE affiliation, {innohk_only_count} papers)')
    ws.merge_cells(start_row=legend_row2, start_column=2, end_row=legend_row2, end_column=10)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    wb.save(EXCEL_FILE)
    return len(papers)

def main():
    papers = load_papers()
    now = datetime.now()
    threshold = (now - timedelta(days=30))
    global threshold_str
    threshold_str = threshold.strftime('%Y-%m-%d')
    recent = [p for p in papers if is_recent(p, threshold_str)]
    precise = sum(1 for p in papers if p.get('date_is_precise', True))
    print(f"Papers: {len(papers)} total, {len(recent)} recent 30d")
    print(f"Dates: {precise} precise, {len(papers)-precise} approximate")
    print(f"Threshold: {threshold_str}")
    print()
    print("Generating README.md...")
    with open(README_FILE, 'w') as f: f.write(generate_readme(papers, recent, now))
    print(f"  OK")
    print("Generating FULL_LIST.md...")
    with open(FULL_LIST_FILE, 'w') as f: f.write(generate_full_list(papers, now))
    print(f"  OK")
    print("Generating COCHE_Weekly_Report.md...")
    with open(REPORT_FILE, 'w') as f: f.write(generate_report(papers, recent, now))
    print(f"  OK")
    print("Generating index.md...")
    with open(INDEX_FILE, 'w') as f: f.write(generate_index(papers, recent, now))
    print(f"  OK")
    print("Generating COCHE_Papers.xlsx...")
    count = generate_excel(papers, threshold_str)
    xlsx_kb = os.path.getsize(EXCEL_FILE) / 1024
    print(f"  OK ({count} papers, {xlsx_kb:.0f} KB)")
    with open(PREV_FILE, 'w') as f: json.dump(papers, f, indent=None, ensure_ascii=False)
    print(f"  Snapshot saved")
    print()
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] All outputs generated.")

if __name__ == '__main__':
    main()
