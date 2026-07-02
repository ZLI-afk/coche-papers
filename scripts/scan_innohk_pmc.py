#!/usr/bin/env python3
"""
Robust script v2: scan ALL papers for InnoHK using BOTH PubMed + PMC full text.
PMC (PubMed Central) full-text XML includes acknowledgements that PubMed abstracts do not.
"""
import json, requests, xml.etree.ElementTree as ET, time, sys, os, re

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = os.path.join(WORKSPACE, 'coche_pubmed.json')

print("=" * 60)
print("COCHE InnoHK Scanner v2 — PubMed + PMC Full Text")
print("=" * 60)

with open(PUBMED_FILE) as f:
    papers = json.load(f)
print(f"Loaded {len(papers)} papers")

# Step 1: bulk-fetch all PubMed XML (already has abstract+grant)
# This gets the known 21 tagged papers
pmids = [p['pmid'] for p in papers]

# Step 2: get PMC IDs for all papers
print("\nFetching PMC IDs...")
pmc_map = {}  # pmid -> pmcid
for i in range(0, len(pmids), 200):
    batch = pmids[i:i+200]
    resp = requests.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi', params={
        'db': 'pubmed', 'id': ','.join(batch), 'retmode': 'json'
    }, timeout=60)
    data = resp.json()
    for pid, info in data.get('result', {}).items():
        if pid == 'uids': continue
        for aid in info.get('articleids', []):
            if aid.get('idtype') == 'pmc':
                pmc_val = aid.get('value', '')
                if pmc_val and pmc_val.startswith('PMC'):
                    pmc_map[pid] = pmc_val
    time.sleep(0.3)

print(f"Papers with PMC IDs: {len(pmc_map)}")

# Step 3: scan PubMed XML for the ones we haven't checked yet
print("\nScanning PubMed abstracts for all papers...")
newly_tagged = 0
total_innohk = 0

for i in range(0, len(pmids), 100):
    batch = pmids[i:i+100]
    try:
        resp = requests.post('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi', data={
            'db': 'pubmed', 'id': ','.join(batch), 'retmode': 'xml', 'rettype': 'abstract'
        }, timeout=90)
        root = ET.fromstring(resp.content)
        for article in root.findall('.//PubmedArticle'):
            pmid = (article.find('.//PMID') or ET.Element('PMID')).text
            if not pmid: continue
            xml_str = ET.tostring(article, encoding='unicode')
            if 'InnoHK' in xml_str or 'innohk' in xml_str.lower():
                for p in papers:
                    if p['pmid'] == pmid:
                        if 'innohk_acknowledgement' not in p.get('source', []):
                            p.setdefault('source', []).append('innohk_acknowledgement')
                            newly_tagged += 1
                        total_innohk += 1
                        break
    except Exception as e:
        print(f"  PubMed batch {i//100+1} error: {e}")
    time.sleep(0.4)

print(f"After PubMed scan: {total_innohk} with InnoHK, {newly_tagged} newly tagged")

# Step 4: scan PMC full text for papers with PMC IDs (THE KEY STEP)
print(f"\nScanning PMC full text for {len(pmc_map)} papers...")
pmc_tagged = 0
pmc_new = 0
pmc_batches = list(pmc_map.items())
pmc_done = 0

for pmid, pmcid in pmc_batches:
    try:
        resp = requests.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi', params={
            'db': 'pmc', 'id': pmcid, 'retmode': 'xml'
        }, timeout=120)
        xml_str = resp.text
        
        if 'InnoHK' in xml_str or 'innohk' in xml_str.lower():
            pmc_tagged += 1
            for p in papers:
                if p['pmid'] == pmid:
                    if 'innohk_acknowledgement' not in p.get('source', []):
                        p.setdefault('source', []).append('innohk_acknowledgement')
                        pmc_new += 1
                        total_innohk += 1
                        
                        # Extract snippet
                        idx = xml_str.lower().find('innohk')
                        if idx >= 0:
                            start = max(0, idx - 60)
                            end = min(len(xml_str), idx + 200)
                            snippet = xml_str[start:end]
                            snippet = re.sub(r'<[^>]+>', ' ', snippet)
                            snippet = re.sub(r'\s+', ' ', snippet).strip()
                            p['innohk_snippet'] = snippet[:300]
                    break
    except Exception as e:
        pass  # skip individual errors
    
    pmc_done += 1
    if pmc_done % 10 == 0:
        sys.stdout.write(f"\r  {pmc_done}/{len(pmc_map)}: {pmc_tagged} with InnoHK, {pmc_new} new")
        sys.stdout.flush()
    time.sleep(0.3)

print(f"\n  Done: {pmc_tagged}/{len(pmc_map)} PMC papers have InnoHK, {pmc_new} newly discovered")

# ── Results ──
print(f"\n{'='*60}")
print(f"FINAL RESULTS")
print(f"{'='*60}")
both = sum(1 for p in papers if 'affiliation' in p.get('source',[]) and 'innohk_acknowledgement' in p.get('source',[]))
innohk_only = sum(1 for p in papers if p.get('source')==['innohk_acknowledgement'])
affil_only = sum(1 for p in papers if p.get('source')==['affiliation'])
print(f"  Total papers: {len(papers)}")
print(f"  Both channels (⭐): {both}")
print(f"  Affiliation only: {affil_only}")
print(f"  InnoHK only (PMC): {innohk_only}")
print(f"  Total InnoHK: {both + innohk_only}")

# Save
with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)
print(f"\nSaved to {PUBMED_FILE}")
