#!/usr/bin/env python3
"""
backfill_dates.py — Backfill missing publication dates for COCHE papers.

For papers with an incomplete date (missing pub_month or pub_day), fill the
missing components from authoritative sources, using the FORMAL/PRINT
publication date (issue date), not the online-first (epub) date.

Priority for the formal/print date:
  1. Crossref 'published-print' date-parts
  2. PubMed esummary 'pubdate' (usually the journal issue date) when it has a day
  3. Crossref 'published' date-parts (fallback, only when no print date)

Dry-run by default (prints a plan). Use --write to actually update the JSON.
"""
import json
import os
import sys
import time

import requests

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

MONTH_MAP = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05',
             'Jun': '06', 'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10',
             'Nov': '11', 'Dec': '12'}
MONTH_NUM = {v: k for k, v in MONTH_MAP.items()}  # '01' -> 'Jan'

WRITE = '--write' in sys.argv
ONLY = None

S = requests.Session()
S.headers['User-Agent'] = 'COCHE-tracker/1.0 (mailto:tracker@example.com)'


def pubmed_pubdate(pmid):
    """Return (year, month_abbr, day) for the FORMAL pubdate, or None."""
    url = ('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
           f'esummary.fcgi?db=pubmed&id={pmid}&retmode=json')
    try:
        r = S.get(url, timeout=20)
        r.raise_for_status()
        d = r.json()
        rec = d['result'].get(pmid, {})
        pubdate = rec.get('pubdate', '')  # e.g. "2026 Jun" or "2026 Jun 5"
    except Exception:
        return None
    return parse_pubdate(pubdate)


def parse_pubdate(s):
    """Parse a PubMed 'pubdate' string like '2026 Jun' or '2026 Jun 5'."""
    if not s:
        return None
    parts = s.strip().split()
    if not parts:
        return None
    try:
        year = int(parts[0])
    except ValueError:
        return None
    month = None
    day = None
    if len(parts) >= 2:
        mm = parts[1][:3].title()
        if mm in MONTH_MAP:
            month = mm
    if len(parts) >= 3:
        try:
            day = int(parts[2])
        except ValueError:
            day = None
    return (str(year), month, day)


def crossref_print(doid):
    """Return (year, month_num, day) for published-print, or None."""
    url = f'https://api.crossref.org/works/{doid}'
    try:
        r = S.get(url, timeout=20)
        r.raise_for_status()
        m = r.json()['message']
    except Exception:
        return None
    # 1. published-print
    dp = m.get('published-print', {}).get('date-parts', [[None]])[0]
    if dp and dp[0]:
        return norm_dp(dp)
    # 2. published (fallback)
    dp = m.get('published', {}).get('date-parts', [[None]])[0]
    if dp and dp[0]:
        return norm_dp(dp)
    return None


def norm_dp(dp):
    """Normalize a Crossref date-parts list to (year, month_num, day)."""
    y = str(dp[0]) if dp and len(dp) > 0 and dp[0] else None
    m = f"{int(dp[1]):02d}" if dp and len(dp) > 1 and dp[1] else None
    d = int(dp[2]) if dp and len(dp) > 2 and dp[2] else None
    return (y, m, d)


def needs_fill(p):
    """True if the paper has a year but is missing month or day."""
    y = (p.get('pub_year') or '').strip()
    m = (p.get('pub_month') or '').strip()
    d = (p.get('pub_day') or '').strip()
    if not y:
        # no year at all — could still try to fill fully
        return True
    return (not m) or (not d)


def main():
    with open(PUBMED_FILE) as f:
        papers = json.load(f)

    candidates = [p for p in papers if needs_fill(p)]
    print(f"Total papers: {len(papers)}")
    print(f"Candidates needing date fill: {len(candidates)}")
    print(f"Mode: {'WRITE' if WRITE else 'DRY-RUN'}\n")

    filled = 0
    plan = []
    for p in candidates:
        pmid = (p.get('pmid') or '').strip()
        doi = (p.get('doi') or '').strip()
        year = (p.get('pub_year') or '').strip()
        month = (p.get('pub_month') or '').strip()
        day = (p.get('pub_day') or '').strip()

        new_year = year or None
        new_month = month or None
        new_day_str = day or None

        # Try Crossref print first (most reliable for formal/issue date)
        if doi:
            cr = crossref_print(doi)
            if cr:
                cy, cm, cd = cr
                if not year and cy:
                    new_year = cy
                if not month and cm:
                    new_month = MONTH_NUM.get(cm)
                if not day and cd:
                    new_day_str = str(cd)

        # Try PubMed pubdate (journal issue date)
        if pmid and ((not new_month) or (not new_day_str) or (not new_year)):
            pp = pubmed_pubdate(pmid)
            if pp:
                py, pm, pd = pp
                if not new_year and py:
                    new_year = py
                if not new_month and pm:
                    new_month = pm
                if not new_day_str and pd:
                    new_day_str = str(pd)

        # Determine what changed
        old = (year, month, day)
        new = (new_year or '', new_month or '', new_day_str or '')
        if old == new:
            continue

        rec = {
            'title': p['title'],
            'old': old,
            'new': new,
            'pmid': pmid,
            'doi': doi,
        }
        plan.append(rec)
        filled += 1

        if WRITE:
            p['pub_year'] = new_year or ''
            p['pub_month'] = new_month or ''
            p['pub_day'] = new_day_str or ''

        # rate limit politeness
        time.sleep(0.15)

    print(f"Records that would be/were filled: {filled}\n")
    for rec in plan:
        print(f"  {rec['old']} -> {rec['new']}  | {rec['title'][:50]}")
        print(f"      pmid={rec['pmid'] or '-'} doi={rec['doi'] or '-'}")

    if WRITE:
        with open(PUBMED_FILE, 'w') as f:
            json.dump(papers, f, indent=2, ensure_ascii=False)
        print(f"\n[WRITTEN] {PUBMED_FILE}")
    else:
        print("\n[dry-run] no changes written. Re-run with --write to apply.")


if __name__ == '__main__':
    main()
