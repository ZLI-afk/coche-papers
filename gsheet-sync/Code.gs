/**
 * COCHE Paper Tracker — one-way sync (GitHub JSON → Google Sheets)
 * =====================================================================
 * Reads the authoritative `coche_pubmed.json` from the GitHub raw URL,
 * matches each paper by a stable key (DOI → PMID → title hash), and writes
 * ONLY the raw-data columns. Annotation columns (anything beyond RAW_COLUMNS)
 * are never touched, so team notes survive every sync.
 *
 * How to install & run — see SETUP.md in this same folder.
 */

// ─────────────────────────────────────────────────────────────────────
// CONFIG — edit these two values only
// ─────────────────────────────────────────────────────────────────────
var GITHUB_RAW_URL =
  'https://raw.githubusercontent.com/ZLI-afk/coche-papers/main/coche_pubmed.json';

// The headers you want in the sheet. First column MUST be the unique key.
// Key priority: DOI (most stable) -> PMID -> title hash fallback.
// Annotation columns are the blank gap at the end ('' placeholder).
var RAW_COLUMNS = [
  'Key',           // unique key — do not change position
  'PMID',
  'Title',
  'DOI',
  'First Published',
  'Journal',
  'All Authors',
  'COCHE Authors',
  'InnoHK Status',
  'ITC Year',
  'Link',
  ''               // <- blank column: left empty as an "Annotation" gap
];

// ─────────────────────────────────────────────────────────────────────
// Sheet name
// ─────────────────────────────────────────────────────────────────────
var SHEET_NAME = 'COCHE Papers';

// ─────────────────────────────────────────────────────────────────────
// INTERNAL — no changes needed below this line
// ─────────────────────────────────────────────────────────────────────

// Stable unique key for a paper. DOI preferred (guaranteed unique, matches
// current Excel/Link behaviour); falls back to PMID when DOI missing; finally
// falls back to a title hash so gs_only papers are never silently dropped.
// NOTE: 134/464 papers currently have empty PMID and 36 have neither DOI nor
// PMID, so keying on PMID alone would silently collide/drop rows.
function paperKey(p) {
  if (p.doi) return 'doi:' + normalizeDoi(p.doi);
  if (p.pmid) return 'pmid:' + p.pmid;
  return 'title:' + hashTitle(p.title || '');
}

// Normalise DOIs so near-duplicates (e.g. trailing period, casing) collapse
// to the same key. Real data has one DOI with a trailing '.' variant.
function normalizeDoi(doi) {
  return String(doi).trim().toLowerCase().replace(/\.$/g, '');
}

// Simple stable hash of the title for the keyless fallback case.
function hashTitle(s) {
  var h = 0;
  for (var i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

// Map a JSON paper object -> array of raw values in RAW_COLUMNS order.
function paperToRow(p) {
  return RAW_COLUMNS.map(function (h) {
    switch (h) {
      case 'Key':
        return paperKey(p);
      case 'PMID':
        return p.pmid;
      case 'Title':
        return p.title || '';
      case 'DOI':
        return p.doi || '';
      case 'First Published':
        return formatDate(p);
      case 'Journal':
        return p.journal || '';
      case 'All Authors':
        return formatAuthors(p);
      case 'COCHE Authors':
        return (p.coche_authors || []).join(', ');
      case 'InnoHK Status':
        return innoHkStatus(p);
      case 'ITC Year':
        return 'ITC ' + itcYear(p);
      case 'Link':
        return paperLink(p);
      case '':
        return ''; // annotation gap — leave blank
      default:
        return '';
    }
  });
}

var MONTH_MAP = {
  'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
  'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'
};

// Mirrors format_date() in generate_outputs.py:
// full date, year+month, or year only (never invent 01-01).
function formatDate(p) {
  var y = p.pub_year || '';
  var m = p.pub_month || '';
  var d = p.pub_day || '';
  if (!y) return 'N/A';
  if (m) {
    var mm = MONTH_MAP[m.slice(0, 3)] || m.slice(0, 3);
    if (d) return y + '-' + mm + '-' + pad2(d);
    return y + '-' + mm;
  }
  return String(y);
}

function pad2(n) { return (String(n).length < 2 ? '0' : '') + n; }

// Full author list, corresponding author marked with '*'.
// Mirrors format_all_authors_with_corresponding() in generate_outputs.py:
//   - uses author_list[].is_corresponding
//   - fallback: if none marked, mark last 1 (<=5 authors) or last 2 (6+ authors)
function formatAuthors(p) {
  var data = p.author_list || [];
  if (data.length === 0) {
    var flat = p.authors || [];
    if (flat.length && typeof flat[0] === 'string') return flat.join(', ');
    if (flat.length && typeof flat[0] === 'object') {
      return flat.map(function (a) { return a.name || ''; }).join(', ');
    }
    return '';
  }

  var hasMarked = data.some(function (a) { return a.is_corresponding; });
  var fallbackCount = data.length <= 5 ? 1 : 2;
  var corrStart = data.length - fallbackCount;

  var parts = [];
  for (var i = 0; i < data.length; i++) {
    var name = (data[i].name || '').trim();
    if (!name) continue;
    var isCorr = !!data[i].is_corresponding;
    if (!hasMarked && i >= corrStart) isCorr = true;
    if (isCorr) name = name + '*';
    parts.push(name);
  }
  return parts.join(', ');
}

function innoHkStatus(p) {
  // Mirrors scripts/generate_outputs.py exactly:
  //   Channel B = 'innohk_acknowledgement' in source
  //   Channel A (COCHE affiliation) = 'affiliation' in source
  var src = p.source || [];
  var isChannelB = src.indexOf('innohk_acknowledgement') !== -1;
  var isAffil = src.indexOf('affiliation') !== -1;

  var label;
  if (isAffil && isChannelB) label = '⭐ InnoHK';
  else if (isChannelB) label = '🏷 InnoHK-only';
  else if (isAffil) label = 'COCHE affiliation';
  else label = 'other';

  // Append the InnoHK acknowledgement snippet (same as Excel: ' | ' + snippet).
  var snip = p.innohk_snippet || '';
  if (snip) {
    if (snip.length > 300) snip = snip.slice(0, 300) + '...';
    label += ' | ' + snip;
  }
  return label;
}

function itcYear(p) {
  // Mirrors get_itc_reporting_year(): Dec belongs to next ITC year.
  var y = parseInt(p.pub_year || '0', 10);
  if (!y) return '?';
  var m = (p.pub_month || '').slice(0, 3);
  if (m === 'Dec') return y + 1;
  return y;
}

function paperLink(p) {
  if (p.doi) return 'https://doi.org/' + p.doi;
  return 'https://pubmed.ncbi.nlm.nih.gov/' + p.pmid;
}

// ─────────────────────────────────────────────────────────────────────
// MAIN — run this (or wire it to a time-driven trigger)
// ─────────────────────────────────────────────────────────────────────
function syncFromGitHub() {
  var json = fetchJson(GITHUB_RAW_URL);
  var papers = Array.isArray(json) ? json : (json.papers || []);

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);

  // 1) Ensure header row exists (create once, never overwrite).
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, RAW_COLUMNS.length).setValues([RAW_COLUMNS]);
    sheet.getRange(1, 1, 1, RAW_COLUMNS.length)
      .setFontWeight('bold').setBackground('#2F5496').setFontColor('#FFFFFF');
    sheet.setFrozenRows(1);
  }

  // 2) Build Key -> row map from existing sheet (skip header).
  var lastRow = Math.max(sheet.getLastRow(), 1);
  var idRange = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
  var existing = {}; // key -> sheet row number
  for (var i = 0; i < idRange.length; i++) {
    var v = idRange[i][0];
    if (v !== '' && v != null) existing[String(v)] = i + 2;
  }

  // 2b) Consolidate papers that share a key (rare source-data duplicates),
  //     e.g. two records with the same DOI but different partial flags.
  //     Merge by union of `source` and `coche_authors`, prefer non-empty
  //     pmid/title, so no flags are lost.
  papers = mergeDuplicates(papers);

  // 3) Upsert: update raw columns for known IDs, append new rows.
  var updates = [];      // {row, values}
  var newRows = [];
  var seen = {};

  papers.forEach(function (p) {
    var k = paperKey(p);
    if (seen[k]) return; // de-dupe
    seen[k] = true;

    var values = paperToRow(p);
    if (existing[k]) {
      updates.push({ row: existing[k], values: values });
    } else {
      newRows.push(values);
    }
  });

  // Apply updates to existing rows WITHOUT touching annotation columns:
  // overwrite only columns 1..RAW_COLUMNS.length.
  var nRaw = RAW_COLUMNS.length;
  updates.forEach(function (u) {
    sheet.getRange(u.row, 1, 1, nRaw).setValues([u.values]);
  });

  // Append brand-new rows at the bottom.
  if (newRows.length) {
    var startRow = sheet.getLastRow() + 1;
    sheet.getRange(startRow, 1, newRows.length, nRaw).setValues(newRows);
  }

  // Lightweight status note (optional) in the annotation gap column header.
  Logger.log('Sync complete: ' + updates.length + ' updated, ' +
             newRows.length + ' new, total ' + papers.length + ' papers.');
  return 'Updated ' + updates.length + ', added ' + newRows.length;
}

// Merge papers that map to the same key (duplicate DOI/PMID records).
function mergeDuplicates(papers) {
  var byKey = {};
  var order = [];
  papers.forEach(function (p) {
    var k = paperKey(p);
    if (!byKey[k]) { byKey[k] = []; order.push(k); }
    byKey[k].push(p);
  });
  var out = [];
  order.forEach(function (k) {
    var ps = byKey[k];
    if (ps.length === 1) { out.push(ps[0]); return; }
    var merged = {};
    ps.forEach(function (p) {
      Object.keys(p).forEach(function (f) { merged[f] = p[f]; }); // last wins
    });
    // Union source flags + author lists so nothing is lost.
    var srcSet = {};
    var srcOrder = [];
    var authors = [];
    var authorSeen = {};
    ps.forEach(function (p) {
      (p.source || []).forEach(function (s) {
        if (!srcSet[s]) { srcSet[s] = true; srcOrder.push(s); }
      });
      (p.coche_authors || []).forEach(function (a) {
        if (!authorSeen[a]) { authorSeen[a] = true; authors.push(a); }
      });
    });
    merged.source = srcOrder;
    merged.coche_authors = authors;
    // Prefer non-empty pmid/title (the record that actually has the PMID).
    ps.forEach(function (p) {
      if (p.pmid) merged.pmid = p.pmid;
      if (p.title) merged.title = p.title;
      if (p.doi) merged.doi = p.doi;
    });
    out.push(merged);
  });
  return out;
}

// Fetch JSON with a cache-buster so we always read the latest committed file.
function fetchJson(url) {
  var sep = url.indexOf('?') === -1 ? '?' : '&';
  var resp = UrlFetchApp.fetch(url + sep + 'nocache=' + Date.now(), {
    muteHttpExceptions: true
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('GitHub fetch failed (' + resp.getResponseCode() + '): ' +
                    resp.getContentText().slice(0, 200));
  }
  return JSON.parse(resp.getContentText());
}

// Add an "Sync" menu + optional time-driven trigger installer.
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('COCHE Sync')
    .addItem('Sync from GitHub now', 'syncFromGitHub')
    .addItem('Install weekly trigger', 'installWeeklyTrigger')
    .addToUi();
}

function installWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncFromGitHub') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('syncFromGitHub')
    .timeBased()
    .everyWeeks(1)
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(10)
    .create();
}
