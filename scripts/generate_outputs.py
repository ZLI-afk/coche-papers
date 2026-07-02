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
    both = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[])]
    single = [p for p in papers if p not in both]
    both_recent = [p for p in recent if p in both]
    
    lines = []
    lines.append('# 🧠 COCHE Paper Tracker')
    lines.append('')
    lines.append('> **Hong Kong Centre for Cerebro-Cardiovascular Health Engineering**  ')
    lines.append(f'> 📊 **{len(papers)} papers** | ⭐ 双通道: {len(both)} | ⏰ {now.strftime("%Y-%m-%d %H:%M")} UTC+8')
    lines.append('')
    lines.append('📥 [Excel](COCHE_Papers.xlsx) | [JSON](coche_pubmed.json) | [Full Table](FULL_LIST.md) | [Report](COCHE_Weekly_Report.md)')
    lines.append('')
    lines.append('---')
    lines.append('')
    
    # ⭐ Tier 1: Both channels — always prominent
    if both_recent:
        lines.append(f'## ⭐ 近期发表 — 机构+致谢双满足 ({len(both_recent)})')
        lines.append('')
        for i, p in enumerate(both_recent, 1):
            lines.append(f'{i}. **[{p["title"]}]({format_link(p)})**')
            lines.append(f'   - 📅 {format_date(p)} | 📰 {(p.get("journal","") or "N/A")[:40]} | 👤 {format_authors(p)}')
        lines.append('')
    
    # 📋 Other recent papers — collapsed
    other_recent = [p for p in recent if p not in both_recent]
    if other_recent:
        lines.append(f'<details><summary>📋 近30天其他 ({len(other_recent)} 篇，单通道)</summary>')
        lines.append('')
        for p in other_recent:
            tag = ' 🏷' if p.get('source')==['innohk_acknowledgement'] else ''
            lines.append(f'- [{p["title"][:80]}]({format_link(p)}) ({format_date(p)}){tag}')
        lines.append('')
        lines.append('</details>')
        lines.append('')
    
    # Full list by year — both first, single collapsed
    year_counts = Counter(p['pub_year'] for p in papers)
    lines.append('## 📋 全部论文（按年份）')
    lines.append('')
    for year in sorted(year_counts.keys(), reverse=True):
        yr = [p for p in papers if p['pub_year'] == year]
        yr_both = [p for p in yr if p in both]
        yr_single = [p for p in yr if p not in yr_both]
        yr_recent = sum(1 for p in yr if is_recent(p, threshold_str))
        badge = ''
        if yr_both: badge += f' ⭐{len(yr_both)}'
        if yr_recent: badge += f' 🆕{yr_recent}'
        lines.append(f'<details>')
        lines.append(f'<summary><b>{year}</b> — {len(yr)} papers{badge}</summary>')
        lines.append('')
        for i, p in enumerate(yr_both, 1):
            lines.append(f'{i}. ⭐ [{p["title"][:80]}]({format_link(p)}) — *{(p.get("journal","") or "N/A")[:30]}* ({format_date(p)})')
        if yr_single:
            yr_single_innohk = [p for p in yr_single if p.get('source')==['innohk_acknowledgement']]
            yr_single_affil = [p for p in yr_single if p not in yr_single_innohk]
            tail = ''
            if yr_single_affil: tail += f' +{len(yr_single_affil)} 机构署名'
            if yr_single_innohk: tail += f' +{len(yr_single_innohk)} InnoHK'
            lines.append(f'<details><summary>更多论文{tail}（单通道）</summary>')
            for p in yr_single:
                tag = ' 🏷' if p.get('source')==['innohk_acknowledgement'] else ''
                lines.append(f'- [{p["title"][:80]}]({format_link(p)}) ({format_date(p)}){tag}')
            lines.append('</details>')
        lines.append('')
        lines.append('</details>')
        lines.append('')
    lines.append('---')
    lines.append('> ⭐ **突出展示** = 机构署名 + InnoHK致谢 双满足 | 单通道论文默认折叠，点击展开')
    lines.append('')
    lines.append('*Auto-updated weekly via PubMed API — all dates are first-published*')
    lines.append('')
    return '\n'.join(lines)

def generate_full_list(papers, now):
    both = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[])]
    both_set = set(id(p) for p in both)
    lines = []
    lines.append('# COCHE All Papers')
    lines.append('')
    lines.append(f'> 📊 **{len(papers)}** papers | ⭐ 双通道: {len(both)} | ⏰ {now.strftime("%Y-%m-%d %H:%M")} UTC+8 | [Home](README.md)')
    lines.append('')
    lines.append('---')
    lines.append('')
    year_counts = Counter(p['pub_year'] for p in papers)
    for year in sorted(year_counts.keys(), reverse=True):
        yr_papers = [p for p in papers if p['pub_year'] == year]
        yr_both = [p for p in yr_papers if p in both]
        yr_single = [p for p in yr_papers if p not in yr_both]
        lines.append(f'## {year} ({len(yr_papers)})')
        lines.append('')
        lines.append('| # | Title | Date | Journal | COCHE Authors | Status | PMID |')
        lines.append('|---|---|---|---|---|---|---|')
        for i, p in enumerate(yr_both, 1):
            title_escaped = p['title'].replace('|', '\\|')
            lines.append(f'| {i} | ⭐ [{title_escaped[:100]}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:30]} | {format_authors(p, 99, "")} | **双满足** | {p["pmid"]} |')
        for p in yr_single:
            is_innohk = p.get('source')==['innohk_acknowledgement']
            title_escaped = p['title'].replace('|', '\\|')
            tag = '🏷 InnoHK' if is_innohk else 'affil'
            lines.append(f'| - | {title_escaped[:100]}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:25]} | {format_authors(p, 99, "")} | {tag} | {p["pmid"]} |')
        lines.append('')
    lines.append('---')
    lines.append('> ⭐ 双满足 = 机构署名 + InnoHK致谢 | 单通道论文以 `-` 序号弱化')
    lines.append(f'*Generated {now.strftime("%Y-%m-%d %H:%M:%S")}*')
    lines.append('')
    return '\n'.join(lines)

def generate_report(papers, recent, now):
    both = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[])]
    innohk_only = sum(1 for p in papers if p.get('source')==['innohk_acknowledgement'])
    both_recent = [p for p in recent if p in both]
    lines = []
    lines.append(f'# COCHE Weekly Report')
    lines.append('')
    lines.append(f'**{now.strftime("%Y-%m-%d %H:%M")}** UTC+8')
    lines.append('')
    lines.append('## Summary')
    lines.append(f'- Total: {len(papers)} | ⭐ 双满足: {len(both)} | 仅InnoHK致谢: {innohk_only}')
    lines.append(f'- Past 30d: {len(recent)} (双满足: {len(both_recent)})')
    lines.append('')
    if both_recent:
        lines.append('## ⭐ 近期 — 机构+致谢双满足')
        lines.append('')
        lines.append('| # | Title | Date | Journal | COCHE Authors |')
        lines.append('|---|---|---|---|---|')
        for i, p in enumerate(both_recent, 1):
            lines.append(f'| {i} | [{p["title"][:60]}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:25]} | {format_authors(p, 2, " …")} |')
        lines.append('')
    other_recent = [p for p in recent if p not in both_recent]
    if other_recent:
        lines.append('## 📋 近30天其他（单通道）')
        lines.append('')
        for p in other_recent:
            tag = '🏷 InnoHK' if p.get('source')==['innohk_acknowledgement'] else ''
            lines.append(f'- [{p["title"][:60]}]({format_link(p)}) | {format_date(p)} | {tag}')
        lines.append('')
    lines.append('---')
    lines.append(f'*Generated {now.strftime("%Y-%m-%d %H:%M:%S")} · ⭐=dual channel*')
    lines.append('')
    return '\n'.join(lines)

def generate_index(papers, recent, now):
    both = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[])]
    both_recent = [p for p in recent if p in both]
    lines = []
    lines.append('# COCHE Paper Tracker')
    lines.append('')
    lines.append('> **Hong Kong Centre for Cerebro-Cardiovascular Health Engineering**')
    lines.append('> Weekly auto-update · Dual-channel: affiliation + InnoHK · ⭐=both')
    lines.append('')
    lines.append(f'📊 **Total: {len(papers)}** | ⭐ 双满足: {len(both)} | 🆕 Past 30d: {len(recent)} | ⏰ {now.strftime("%Y-%m-%d %H:%M")}')
    lines.append('')
    lines.append('---')
    lines.append('')
    if both_recent:
        lines.append(f'## ⭐ 近期 — 机构+致谢双满足 ({len(both_recent)})')
        lines.append('')
        lines.append('| # | Title | Date | Journal | COCHE Authors |')
        lines.append('|---|---|---|---|---|')
        for i, p in enumerate(both_recent, 1):
            title = p['title'][:70] + ('...' if len(p['title']) > 70 else '')
            lines.append(f'| {i} | [{title}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:28]} | {format_authors(p, 2, " 等")} |')
        lines.append('')
    
    # Full list — both first, single collapsed
    year_counts = Counter(p['pub_year'] for p in papers)
    lines.append(f'## 📋 Full List ({len(papers)})')
    lines.append('')
    for year in sorted(year_counts.keys(), reverse=True):
        yr = [p for p in papers if p['pub_year'] == year]
        yr_both = [p for p in yr if p in both]
        yr_single = [p for p in yr if p not in yr_both]
        lines.append(f'### {year} ({len(yr)} papers)')
        lines.append('')
        lines.append('| # | Title | Date | Journal | Status |')
        lines.append('|---|---|---|---|---|')
        for i, p in enumerate(yr_both, 1):
            title = p['title'][:70] + ('...' if len(p['title']) > 70 else '')
            lines.append(f'| {i} | ⭐ [{title}]({format_link(p)}) | {format_date(p)} | {(p.get("journal","") or "N/A")[:26]} | 双满足 |')
        if yr_single:
            yr_si = [p for p in yr_single if p.get('source')==['innohk_acknowledgement']]
            yr_sa = [p for p in yr_single if p not in yr_si]
            tail = ''
            if yr_sa: tail += f' +{len(yr_sa)} 机构'
            if yr_si: tail += f' +{len(yr_si)} InnoHK'
            lines.append(f'<details><summary>单通道论文{tail}</summary>')
            for p in yr_single:
                tag = '🏷 InnoHK' if p.get('source')==['innohk_acknowledgement'] else 'affil'
                title = p['title'][:70] + ('...' if len(p['title']) > 70 else '')
                lines.append(f'- [{title}]({format_link(p)}) | {format_date(p)} | {tag}')
            lines.append('</details>')
        lines.append('')
    lines.append('---')
    lines.append('📥 [Excel](COCHE_Papers.xlsx) | 📄 [JSON](coche_pubmed.json) | 📝 [Report](COCHE_Weekly_Report.md)')
    lines.append('')
    lines.append(f'*{now.strftime("%Y-%m-%d %H:%M:%S")} · PubMed API · ⭐=机构署名+InnoHK致谢 双满足*')
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
    gold_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')  # both + recent
    gray_font = Font(size=10, color='999999')
    thin_border = Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
    headers = ['#','PMID','Title','DOI','First Published','Journal','COCHE Authors','Status','All Authors','Link']
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = hdr_font; c.fill = hdr_fill; c.alignment = hdr_align; c.border = thin_border
    col_widths = [5, 10, 55, 30, 14, 30, 30, 20, 50, 35]
    for i,w in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    
    # Sort: both-first, then date desc
    def sort_key(p):
        is_both = 0 if ('affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[])) else 1
        return (is_both, format_date(p))
    sorted_papers = sorted(papers, key=sort_key)
    # Actually: both-first + date-desc: both papers in date desc, then single papers in date desc
    both_papers = [p for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[])]
    single_papers = [p for p in papers if p not in both_papers]
    # Sort each section by date desc
    mo_ord = {'Jan':0,'Feb':1,'Mar':2,'Apr':3,'May':4,'Jun':5,'Jul':6,'Aug':7,'Sep':8,'Oct':9,'Nov':10,'Dec':11}
    both_papers.sort(key=lambda p: (int(p.get('pub_year','0')or'0'), mo_ord.get((p.get('pub_month','')or'Jan')[:3],0), int((p.get('pub_day','01')or'01'))), reverse=True)
    single_papers.sort(key=lambda p: (int(p.get('pub_year','0')or'0'), mo_ord.get((p.get('pub_month','')or'Jan')[:3],0), int((p.get('pub_day','01')or'01'))), reverse=True)
    # Interleave: both papers remain date-sorted, then single papers
    display_order = both_papers + single_papers
    
    for idx, p in enumerate(display_order, 1):
        date_str = format_date(p)
        link = format_link(p)
        coche_auth = ', '.join(p.get('coche_authors', []))
        all_auth = ', '.join(str(a) for a in p.get('authors', [])[:8])
        if len(p.get('authors', [])) > 8: all_auth += ' ...'
        is_both = 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[])
        is_innohk_only = p.get('source')==['innohk_acknowledgement']
        if is_both:
            status_label = '⭐ 双满足'
        elif is_innohk_only:
            status_label = '🏷 InnoHK'
        else:
            status_label = 'affil'
        row_data = [idx, p['pmid'], p['title'], p.get('doi',''), date_str, p.get('journal',''), coche_auth, status_label, all_auth, link]
        is_rec = date_str >= threshold_str
        for col, val in enumerate(row_data, 1):
            c = ws.cell(row=idx + 1, column=col, value=val)
            c.font = Font(size=10, bold=(is_both and is_rec), color=('999999' if not is_both and not is_rec else None))
            c.alignment = Alignment(vertical='top', wrap_text=True)
            c.border = thin_border
            if is_rec and is_both:
                c.fill = gold_fill
    legend_row = len(display_order) + 3
    ws.cell(row=legend_row, column=1, value='🟡').font = Font(size=14)
    both_count = len(both_papers)
    recent_both = sum(1 for p in both_papers if format_date(p) >= threshold_str)
    ws.cell(row=legend_row, column=2, value=f'⭐ 双满足 = 机构署名 + InnoHK致谢 ({both_count} 篇) | 黄色高亮 = 双满足 + 近30天发表 ({recent_both} 篇) | 灰色 = 单通道')
    ws.merge_cells(start_row=legend_row, start_column=2, end_row=legend_row, end_column=10)
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
