#!/usr/bin/env python3
"""
Clean innohk_acknowledgement tags from papers whose snippets don't contain "InnoHK".
This ensures Channel B only flags papers with the actual word "InnoHK".
"""
import json

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = f'{WORKSPACE}/coche_pubmed.json'

with open(PUBMED_FILE) as f:
    papers = json.load(f)

removed = 0
for p in papers:
    if 'innohk_acknowledgement' in p.get('source', []):
        snip = p.get('innohk_snippet', '').lower()
        src = p.get('innohk_source', '')
        # Keep only if snippet contains 'innohk'
        if 'innohk' not in snip:
            # Check if this was an ITC pattern match (unreliable)
            if src in ('itc_fullname', 'ezproxy_ack_real'):
                p['source'] = [s for s in p['source'] if s != 'innohk_acknowledgement']
                p.pop('innohk_snippet', None)
                p.pop('innohk_source', None)
                removed += 1
                print(f"  Removed tag from PMID {p['pmid']}: {p['title'][:60]} (source={src})")

# Ensure source isn't empty
for p in papers:
    if not p.get('source'):
        p['source'] = ['affiliation']

with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

innohk_count = sum(1 for p in papers if 'innohk_acknowledgement' in p.get('source', []))
dual_count = sum(1 for p in papers if 'affiliation' in p.get('source', []) and 'innohk_acknowledgement' in p.get('source', []))
print(f"\nDone. Removed {removed} stale tags.")
print(f"⭐ InnoHK: {innohk_count} ({dual_count} dual)")
print(f"Total papers: {len(papers)}")
