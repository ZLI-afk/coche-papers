#!/usr/bin/env python3
"""
backfill_dates_v2.py — Second pass: fill any remaining obtainable month, and
mark records that truly cannot be dated with a warning field.

For remaining paper with missing month:
  - If it has a DOI, try Crossref 'published-online' (fallback to 'published')
    and use the most specific date available. Prefer online-first here because
    print-only gives only year for these early-access/conference records.
  - If nothing usable is found, set date_missing_warning with a reason.
  - Papers with no DOI/PMID (gs_only) are marked 'no_identifier'.

Write the following field on each paper that still lacks a full date after
filling:
    p['date_missing_warning'] = <reason string>
"""
import json
import os
import sys
import time

import requests

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

MONTH_NUM = {'01': 'Jan', '02': 'Feb', '03': 'Mar', '04': 'Apr', '05': 'May',
             '06': 'Jun', '07': 'Jul', '08': 'Aug', '09': 'Sep', '10': 'Oct',
             '11': 'Nov', '12': 'Dec'}

WRITE = '--write' in sys.argv
S = requests.Session()
S.headers['User-Agent'] = 'COCHE-tracker/1.0 (mailto:tracker@example.com)'


def crossref_date(doid):
    """Return most specific (year, month_abbr, day) available."""
    try:
        r = S.get(f'https://api.crossref.org/works/{doid}', timeout=20)
        if r.status_code != 200:
            return None
        m = r.json()['message']
    except Exception:
        return None

    candidates = []
    for key in ('published-print', 'published-online', 'published', 'issued'):
        dp = m.get(key, {}).get('date-parts', [[None]])[0]
        if dp and dp[0]:
            candidates.append(dp)
    if not candidates:
        return None
    # pick the most specific (most fields present)
    best = max(candidates, key=lambda d: sum(1 for x in d if x))
    y = str(best[0]) if len(best) > 0 and best[0] else None
    mo = MONTH_NUM.get(f"{int(best[1]):02d}") if len(best) > 1 and best[1] else None
    d = int(best[2]) if len(best) > 2 and best[2] else None
    return (y, mo, d)


def main():
    with open(PUBMED_FILE) as f:
        papers = json.load(f)

    filled = 0
    warned = 0
    for p in papers:
        y = (p.get('pub_year') or '').strip()
        mo = (p.get('pub_month') or '').strip()
        d = (p.get('pub_day') or '').strip()
        doi = (p.get('doi') or '').strip()
        pmid = (p.get('pmid') or '').strip()

        # already complete
        if y and mo and d:
            p.pop('date_missing_warning', None)
            continue

        # try to fill via crossref if DOI present
        filled_this = (y, mo, d)
        if doi:
            c = crossref_date(doi)
            if c:
                cy, cm, cd = c
                ny = y or cy or ''
                nm = mo or cm or ''
                nd = d or (str(cd) if cd else '')
                if (ny, nm, nd) != (y, mo, d) and (nm or nd):
                    if WRITE:
                        p['pub_year'] = ny
                        p['pub_month'] = nm
                        p['pub_day'] = nd
                    filled += 1
                    filled_this = (ny, nm, nd)
                    print(f"FILL  {doi} | {p['title'][:50]} | {d or '-'}->{nd or '-'}")
            time.sleep(0.15)

        # re-evaluate completeness
        y = (p.get('pub_year') or '').strip()
        mo = (p.get('pub_month') or '').strip()
        d = (p.get('pub_day') or '').strip()

        if not (y and mo and d):
            # still incomplete -> warn
            if not doi and not pmid:
                reason = 'no_identifier_gs_only'
            elif not y:
                reason = 'missing_year'
            elif not mo:
                reason = 'missing_month'
            else:
                reason = 'missing_day'
            if WRITE:
                p['date_missing_warning'] = reason
            warned += 1

    print(f"\nFilled (this pass): {filled}")
    print(f"Marked with warning: {warned}")

    if WRITE:
        with open(PUBMED_FILE, 'w') as f:
            json.dump(papers, f, indent=2, ensure_ascii=False)
        print(f"[WRITTEN] {PUBMED_FILE}")
    else:
        print("[dry-run] use --write to apply")


if __name__ == '__main__':
    main()
