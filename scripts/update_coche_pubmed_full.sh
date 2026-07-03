#!/bin/bash
# COCHE PubMed Full Fetch - 补全所有变体拼写，尽量不遗漏
set -e

WORKSPACE_DIR="/home/ubuntu/.openclaw/workspace"
PUBMED_OUT="$WORKSPACE_DIR/coche_pubmed.json"
PREVIOUS_OUT="$WORKSPACE_DIR/coche_pubmed_previous.json"
LOG_FILE="$WORKSPACE_DIR/coche_pubmed_fetch_log.txt"

echo "[$(date)] Starting COCHE PubMed full fetch..." | tee "$LOG_FILE"

python3 << 'PYEOF'
import requests, json, time, xml.etree.ElementTree as ET, os, sys

# ============================================================
# === Helper function first! ===
# ============================================================
def is_coche_affiliation(aff_text):
    """Check if an affiliation string belongs to COCHE (Hong Kong)."""
    if not aff_text:
        return False
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
    hk_terms = [
        'hong kong', 'hongkong', 'shatin', 'kowloon',
        'cityu', 'city university', 'hk science', 'hksar',
        'hkstp', 'new territories', 'pak shek kok',
    ]
    has_coche = any(t in aff for t in coche_terms)
    has_hk = any(t in aff for t in hk_terms)
    venezuela = any(t in aff for t in ['venezuela', 'caracas', 'periferico', 'periférico'])
    return has_coche and has_hk and not venezuela

# ============================================================
# Step 0: Define all queries
# ============================================================
AFFILIATION_QUERIES = [
    '"Hong Kong Centre for Cerebro-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebra-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebro-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebra-cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebrocardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebrocardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Centre for Cerebra Cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebro Cardiovascular Health Engineering"[Affiliation]',
    '"Hong Kong Center for Cerebra Cardiovascular Health Engineering"[Affiliation]',
    '"COCHE"[Affiliation]',
]

TEXT_QUERIES = [
    '("Cerebro-cardiovascular Health Engineering"[All Fields] OR "Cerebra-cardiovascular Health Engineering"[All Fields] OR "Cerebrocardiovascular Health Engineering"[All Fields]) AND ("Hong Kong"[All Fields] OR "Hong Kong"[Affiliation] OR "Hong Kong Science Park"[All Fields])',
    'COCHE[Affiliation] AND (Hong Kong[Affiliation] OR cerebro-cardiovascular[All Fields])',
]

seen_pmids = set()

def fetch_pmids_for_query(query):
    all_ids = []
    retstart = 0
    while True:
        resp = requests.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi', params={
            'db': 'pubmed', 'term': query, 'retstart': retstart,
            'retmax': 500, 'retmode': 'json', 'sort': 'date'
        }, timeout=30)
        data = resp.json()
        ids = data.get('esearchresult', {}).get('idlist', [])
        total = int(data.get('esearchresult', {}).get('count', '0'))
        for pid in ids:
            if pid not in seen_pmids:
                all_ids.append(pid)
                seen_pmids.add(pid)
        if len(ids) == 0 or retstart + 500 >= total:
            break
        retstart += 500
        time.sleep(0.4)
    return all_ids

# ============================================================
# Step 1: Fetch all PMIDs from all affiliation queries
# ============================================================
print("=== Fetching PMIDs from all affiliation queries ===")
all_ids = []
for q in AFFILIATION_QUERIES:
    ids = fetch_pmids_for_query(q)
    print(f"  Query: {q[:80]}... -> {len(ids)} new, total unique: {len(seen_pmids)}")
    all_ids.extend(ids)
    time.sleep(0.3)

print(f"\nTotal unique PMIDs from affiliation search: {len(seen_pmids)}")

# ============================================================
# Step 2: Broader text search
# ============================================================
print("\n=== Broader text search ===")
for q in TEXT_QUERIES:
    ids = fetch_pmids_for_query(q)
    print(f"  Query: {q[:80]}... -> {len(ids)} new, total unique: {len(seen_pmids)}")
    all_ids.extend(ids)
    time.sleep(0.3)

print(f"\nTotal unique PMIDs after text search: {len(seen_pmids)}")

# ============================================================
# Step 3: Fetch full details
# ============================================================
print(f"\n=== Fetching details for {len(all_ids)} papers ===")
papers = []

for i in range(0, len(all_ids), 100):
    batch = all_ids[i:i+100]
    resp = requests.post('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi', data={
        'db': 'pubmed', 'id': ','.join(batch),
        'retmode': 'xml', 'rettype': 'abstract'
    }, timeout=60)
    
    root = ET.fromstring(resp.content)
    for article in root.findall('.//PubmedArticle'):
        try:
            pmid = article.find('.//PMID').text
            title_elem = article.find('.//ArticleTitle')
            title = title_elem.text if title_elem is not None else ''
            if title is None:
                title = ''
            
            authors = []
            author_list = []
            coche_authors = []
            all_affiliations = []
            
            for author in article.findall('.//Author'):
                last = author.find('./LastName')
                fore = author.find('./ForeName')
                name = f'{fore.text} {last.text}' if fore is not None and last is not None else ''
                
                affs = []
                in_coche = False
                is_corr = False
                for aff in author.findall('.//AffiliationInfo/Affiliation'):
                    aff_text = aff.text or ''
                    affs.append(aff_text)
                    all_affiliations.append(aff_text)
                    if is_coche_affiliation(aff_text):
                        in_coche = True
                    if re.search(r'(?:correspond|\*|✉|📧)', aff_text, re.IGNORECASE):
                        is_corr = True
                authors.append({'name': name.strip() if name else '', 'affiliations': affs})
                author_list.append({
                    'name': name.strip() if name else '',
                    'affiliations': affs,
                    'is_corresponding': is_corr,
                    'is_coche': in_coche
                })
                if in_coche and name:
                    coche_authors.append(name.strip())
            
            # Check GrantList for COCHE mentions
            grant_list = article.find('.//GrantList')
            grants_mention_coche = False
            if grant_list is not None:
                for grant in grant_list.findall('.//Grant'):
                    agency = grant.find('./Agency')
                    if agency is not None and agency.text:
                        if is_coche_affiliation(agency.text):
                            grants_mention_coche = True
                            break
            
            journal = article.find('.//Journal/Title')
            journal_name = journal.text if journal is not None else ''
            
            # Get DOI
            doi = ''
            for eid in article.findall('.//ELocationID'):
                if eid.get('EIdType') == 'doi':
                    doi = eid.text or ''
                    break
            if not doi:
                for aid in article.findall('.//ArticleId'):
                    if aid.get('IdType') == 'doi':
                        doi = aid.text or ''
                        break
            
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
                'authors': authors, 'author_list': author_list, 'coche_authors': coche_authors,
                'coche_in_grants': grants_mention_coche,
                'all_affiliations': all_affiliations[:50]
            })
        except Exception as e:
            print(f"  Warning: parse error for PMID in batch {i//100+1}: {e}")
            continue
    time.sleep(0.5)
    if (i // 100) % 5 == 0:
        print(f"  Fetched {min(i+100, len(all_ids))}/{len(all_ids)}")

# ============================================================
# Step 4: Filter and validate
# ============================================================
valid_pmids = set()
for p in papers:
    for a in p.get('authors', []):
        for aff in a.get('affiliations', []):
            if is_coche_affiliation(aff):
                valid_pmids.add(p['pmid'])
                break
    if p.get('coche_in_grants'):
        valid_pmids.add(p['pmid'])

cleaned = [p for p in papers if p['pmid'] in valid_pmids]
removed = len(papers) - len(cleaned)

print(f"\n=== Results ===")
print(f"Total fetched: {len(papers)}")
print(f"Has COCHE affiliation: {len(cleaned)}")
print(f"Removed (non-COCHE): {removed}")

# Sort by year desc
cleaned.sort(key=lambda x: (x.get('pub_year', '0'), x.get('pub_month', '0'), x.get('pub_day', '0')), reverse=True)

# Save
output_path = '/home/ubuntu/.openclaw/workspace/coche_pubmed.json'
with open(output_path, 'w') as f:
    json.dump(cleaned, f, indent=2, ensure_ascii=False)

print(f"Saved to {output_path}")

# Check specific known paper
target = 'Ultrathin, soft, radiative cooling'
found = any(target.lower() in p.get('title', '').lower() for p in cleaned)
print(f"\n'{target}' in results: {'YES ✅' if found else 'NO ❌'}")
if found:
    for p in cleaned:
        if target.lower() in p.get('title', '').lower():
            print(f"  PMID: {p['pmid']}, COCHE authors: {p.get('coche_authors', [])}")

# Stats
years = {}
for p in cleaned:
    y = p.get('pub_year', '?')
    years[y] = years.get(y, 0) + 1
print(f"\nPapers per year: {dict(sorted(years.items()))}")
PYEOF

# Save previous for comparison
cp "$PUBMED_OUT" "$PREVIOUS_OUT"

echo "" | tee -a "$LOG_FILE"
echo "[$(date)] Done. Output: $PUBMED_OUT" | tee -a "$LOG_FILE"
