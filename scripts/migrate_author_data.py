#!/usr/bin/env python3
"""
Migration: Convert existing coche_pubmed.json authors from flat strings to structured author_list.
Also re-fetches author data from PubMed for papers missing author_list.
"""
import json
import requests
import time
import xml.etree.ElementTree as ET

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
PUBMED_FILE = f'{WORKSPACE}/coche_pubmed.json'

with open(PUBMED_FILE) as f:
    papers = json.load(f)

print(f"Loaded {len(papers)} papers")

needs_update = []
for p in papers:
    if 'author_list' not in p or not p.get('author_list'):
        needs_update.append(p['pmid'])
    # Also check for existing flat authors
    authors = p.get('authors', [])
    if authors and isinstance(authors[0], str):
        # Convert flat strings to author_list fallback
        p['author_list'] = [{'name': a, 'affiliations': [], 'is_corresponding': False, 'is_coche': a in p.get('coche_authors', [])} for a in authors if a.strip()]

print(f"Papers needing re-fetch from PubMed: {len(needs_update)}")

if needs_update:
    print(f"Fetching author details for {len(needs_update)} papers...")
    updated = 0
    for i in range(0, len(needs_update), 50):
        batch = needs_update[i:i+50]
        resp = requests.post('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi', data={
            'db': 'pubmed', 'id': ','.join(batch),
            'retmode': 'xml', 'rettype': 'xml'
        }, timeout=60)
        
        root = ET.fromstring(resp.content)
        for article in root.findall('.//PubmedArticle'):
            pmid = article.find('.//PMID').text
            
            author_list = []
            coche_authors = []
            for author in article.findall('.//Author'):
                last = author.find('./LastName')
                fore = author.find('./ForeName')
                name = f'{fore.text} {last.text}' if fore is not None and last is not None else ''
                
                in_coche = False
                aff_list = []
                is_corr = False
                for aff in author.findall('.//AffiliationInfo/Affiliation'):
                    aff_text = aff.text or ''
                    aff_list.append(aff_text)
                    # Check COCHE
                    aff_lower = aff_text.lower()
                    if any(t in aff_lower for t in ['cerebro-cardiovascular health engineering', 'cerebra-cardiovascular', 'cerebrocardiovascular']):
                        if any(t in aff_lower for t in ['hong kong', 'hongkong', 'shatin', 'kowloon', 'cityu', 'city university']):
                            in_coche = True
                    # Check corresponding author
                    if any(t in aff_lower for t in ['correspond', 'email:', '✉', '📧', 'electronic address']):
                        is_corr = True
                
                if in_coche and name:
                    coche_authors.append(name.strip())
                
                author_list.append({
                    'name': name.strip() if name else '',
                    'affiliations': aff_list,
                    'is_corresponding': is_corr,
                    'is_coche': in_coche
                })
            
            # Update paper
            for p in papers:
                if p['pmid'] == pmid:
                    p['author_list'] = author_list
                    if coche_authors and not p.get('coche_authors'):
                        p['coche_authors'] = coche_authors
                    if 'source' not in p:
                        p['source'] = ['affiliation'] if coche_authors else []
                    elif coche_authors and 'affiliation' not in p['source']:
                        p['source'].append('affiliation')
                    updated += 1
                    break
        
        time.sleep(0.5)
        if (i // 50) % 5 == 0:
            print(f"  Fetched {min(i+50, len(needs_update))}/{len(needs_update)}")
    
    print(f"Updated {updated} papers with structured author data")

# Save
with open(PUBMED_FILE, 'w') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

print(f"Saved {len(papers)} papers to {PUBMED_FILE}")
print("Migration complete!")
