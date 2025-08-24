#!/usr/bin/env python3
# BillTracer — Bill Evolution (Appropriations-focused)
# Compares two bill versions and generates a static HTML redline at output/index.html

import re, html, difflib, datetime
from pathlib import Path
from typing import List, Dict, Tuple

# > Labels for your specific bill
BILL_ID  = "BillTracer — H.R. 748 (CARES Act vehicle)" 
STAGE_A  = "Introduced (IH)"                            
STAGE_B  = "Enrolled (ENR)"                              
# 

DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")
V1_PATH    = DATA_DIR / "bill_v1.txt"
V2_PATH    = DATA_DIR / "bill_v2.txt"

# A) Classic section headers, e.g. SEC. 101. or Section 204:
SECTION_PATTERN = re.compile(
    r'^(?:SEC\.|Sec\.|SECTION|Section)\s+(\d+[A-Za-z\-]*)[.: ]',
    re.MULTILINE
)

# B) Appropriations often hinge on DIVISIONS/TITLES
TITLE_DIV_PATTERN = re.compile(
    r'^(?:DIVISION [A-Z][\u2014—\-].*|TITLE [IVXLC]+[\u2014—\-].*)$',
    re.MULTILINE
)

# C) SUBTITLES show up a lot in omnibus vehicles
SUBTITLE_PATTERN = re.compile(
    r'^(?:SUBTITLE [A-Z][\u2014—\-].*)$',
    re.MULTILINE
)

# Heuristics to flag likely funding/appropriations language
APPROPRIATIONS_HINTS = re.compile(
    r'(\$\s?\d|\bappropriat|\bauthorized to be appropriated\b|to remain available|transfer|obligation|resciss|offset|grant|fund(s|ing)?|line item)',
    re.IGNORECASE
)

def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\u00A0", " ", text)  # non-breaking 
    return text

def split_by_matches(raw: str, matches: List[re.Match], id_prefix: str, keep_header_line: bool = True) -> List[Dict]:
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end   = matches[i+1].start() if i+1 < len(matches) else len(raw)
        chunk = raw[start:end].strip()
        header = m.group(0).strip()
        sec_id = f"{id_prefix}{i+1:03d}"
        title  = header
        body   = chunk if keep_header_line else "\n".join(chunk.splitlines()[1:]).strip()
        blocks.append({"sec_id": sec_id, "title": title, "body": body})
    return blocks

def split_sections(raw: str) -> List[Dict]:
    """
    Try four levels:
      1) "SEC. 101." style sections
      2) DIVISION/TITLE blocks
      3) SUBTITLE blocks
      4) Fallback = whole doc
    Returns list of dicts: {"sec_id","title","body"}
    """
    # 1) Formal "SEC." / "Section"
    sec_matches = list(SECTION_PATTERN.finditer(raw))
    if sec_matches:
        sections = []
        for i, m in enumerate(sec_matches):
            sec_id = m.group(1)
            start  = m.start()
            end    = sec_matches[i+1].start() if i+1 < len(sec_matches) else len(raw)
            chunk  = raw[start:end].strip()
            lines  = chunk.splitlines()
            title_line = lines[0].strip() if lines else f"Section {sec_id}"
            body       = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
            m2 = re.search(r'^(?:SEC\.|Sec\.|SECTION|Section)\s+\d+[A-Za-z\-]*[.: ]\s*(.*)$', title_line)
            short_title = (m2.group(1).strip() if m2 else title_line) or title_line
            sections.append({"sec_id": sec_id, "title": short_title, "body": body})
        return sections

    # 2) DIVISION/TITLE blocks
    div_matches = list(TITLE_DIV_PATTERN.finditer(raw))
    if div_matches:
        return split_by_matches(raw, div_matches, id_prefix="DIV", keep_header_line=True)

    # 3) SUBTITLE blocks
    sub_matches = list(SUBTITLE_PATTERN.finditer(raw))
    if sub_matches:
        return split_by_matches(raw, sub_matches, id_prefix="SUB", keep_header_line=True)

    # 4) Fallback — whole doc
    return [{"sec_id": "ALL", "title": "FULL TEXT", "body": raw.strip()}]

def index_by_id(sections: List[Dict]) -> Dict[str, Dict]:
    return {s["sec_id"]: s for s in sections}

def word_diff_html(a: str, b: str) -> str:
    """Word-level redline with <ins>/<del> using difflib."""
    def esc(s): return html.escape(s, quote=False)
    a_w, b_w = a.split(), b.split()
    sm = difflib.SequenceMatcher(None, a_w, b_w)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.append(" ".join(esc(w) for w in a_w[i1:i2]))
        elif tag == "delete":
            out.append("<del>" + " ".join(esc(w) for w in a_w[i1:i2]) + "</del>")
        elif tag == "insert":
            out.append("<ins>" + " ".join(esc(w) for w in b_w[j1:j2]) + "</ins>")
        elif tag == "replace":
            out.append("<del>" + " ".join(esc(w) for w in a_w[i1:i2]) + "</del>")
            out.append("<ins>" + " ".join(esc(w) for w in b_w[j1:j2]) + "</ins>")
    return " ".join(out)

def categorize_change(before: str, after: str) -> List[str]:
    """Tiny rule-based tags for quick scanning."""
    tags = set()
    text = (before + " " + after).lower()
    if re.search(r'(\$[\s]?\d|\bappropriat|\bauthorized to be appropriated|\bgrant\b|\bfund(s|ing)?)', text):
        tags.add("Funding")
    if re.search(r'\bshall\b|\bmay not\b|\bpenalt', text):
        tags.add("Authority")
    if re.search(r'not later than|\breport to congress|\bgao\b|\breporting requirement', text):
        tags.add("Reporting")
    return sorted(tags)

def summarize_changes(old_by_id: Dict[str, Dict], new_by_id: Dict[str, Dict]) -> Tuple[List[Dict], Dict[str,int]]:
    """Compare section dictionaries; return change list + stats."""
    change_log: List[Dict] = []
    stats = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}

    all_ids = sorted(set(old_by_id) | set(new_by_id), key=lambda x: (len(x), x))
    for sid in all_ids:
        old = old_by_id.get(sid)
        new = new_by_id.get(sid)

        if old and not new:
            stats["removed"] += 1
            change_log.append({
                "sec_id": sid, "title": old["title"], "status": "Removed",
                "tags": [], "is_approp": bool(APPROPRIATIONS_HINTS.search(old["body"])),
                "redline": "<del>Section removed in newer version.</del>"
            })
            continue

        if new and not old:
            stats["added"] += 1
            tags = categorize_change("", new["body"])
            change_log.append({
                "sec_id": sid, "title": new["title"], "status": "Added",
                "tags": tags, "is_approp": bool(APPROPRIATIONS_HINTS.search(new["body"])),
                "redline": "<ins>" + html.escape(new["body"]) + "</ins>"
            })
            continue

        # Present in both > compare bodies
        if old["body"].strip() == new["body"].strip():
            stats["unchanged"] += 1
            continue

        stats["modified"] += 1
        tags = categorize_change(old["body"], new["body"])
        redline = word_diff_html(old["body"], new["body"])
        change_log.append({
            "sec_id": sid,
            "title": new["title"] or old["title"],
            "status": "Modified",
            "tags": tags,
            "is_approp": bool(APPROPRIATIONS_HINTS.search(old["body"] + " " + new["body"])),
            "redline": redline
        })

    # Show likely funding/appropriations changes first, then by ID
    change_log.sort(key=lambda x: (not x["is_approp"], x["sec_id"]))
    return change_log, stats

def build_html(change_log: List[Dict], stats: Dict[str,int]) -> str:
    css = """
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin:0; }
    header { padding:14px 20px; border-bottom:1px solid #eee; position:sticky; top:0; background:#fff; z-index:1;}
    .wrap { display:flex; min-height:100vh; }
    nav { width:320px; border-right:1px solid #eee; padding:16px; position:sticky; top:58px; height:calc(100vh - 58px); overflow:auto;}
    main { flex:1; padding:16px 24px; }
    h1 { margin:0 0 6px 0; font-size:20px; }
    small.muted { color:#666; }
    .chip { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; margin-right:6px; background:#f2f2f2; }
    .chip.status.Modified { background:#fff3cd; }
    .chip.status.Added { background:#e2f7e2; }
    .chip.status.Removed { background:#fde2e2; }
    .chip.tag { background:#e9eefc; }
    .chip.approp { background:#ffe7bf; }
    section.block { border-bottom:1px solid #eee; padding:18px 0; }
    section.block h3 { margin:0 0 6px 0; }
    section.block pre { white-space:pre-wrap; word-wrap:break-word; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:#fafafa; padding:12px; border-radius:6px; border:1px solid #eee; }
    ins { background:#dbffdb; text-decoration:none; }
    del { background:#ffd9d9; text-decoration:line-through; }
    a { color:#2a5bd7; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .sec-link { display:block; margin-bottom:8px; }
    .counts span { margin-right:12px; }
    .top5 { background:#f7faff; border:1px solid #e5ecff; padding:10px; border-radius:6px; margin-top:10px; }
    """

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Left nav
    nav_items = []
    for ch in change_log:
        app = "<span class='chip approp'>Appropriations</span>" if ch["is_approp"] else ""
        nav_items.append(
            f"<a class='sec-link' href='#{html.escape(ch['sec_id'])}'>"
            f"<span class='chip status {ch['status']}'>{ch['status']}</span> "
            f"<strong>{html.escape(ch['sec_id'])}</strong> — {html.escape(ch['title'][:70])} {app}</a>"
        )

    # Top 5 likely funding changes
    top5 = [c for c in change_log if c["is_approp"]][:5]
    top5_html = "".join(
        f"<li><a href='#{html.escape(c['sec_id'])}'>{html.escape(c['sec_id'])}</a> — "
        f"{html.escape(c['title'][:100])} <span class='chip status {c['status']}'>{c['status']}</span></li>"
        for c in top5
    ) or "<li>No likely funding changes found.</li>"

    # Content blocks
    blocks = []
    for ch in change_log:
        tags = " ".join(f"<span class='chip tag'>{t}</span>" for t in ch["tags"])
        app = "<span class='chip approp'>Appropriations</span>" if ch["is_approp"] else ""
        blocks.append(f"""
        <section class='block' id='{html.escape(ch["sec_id"])}'>
          <h3>{html.escape(ch["title"])}</h3>
          <div>{app} <span class='chip status {ch['status']}'>{ch['status']}</span> {tags}</div>
          <pre>{ch["redline"]}</pre>
        </section>
        """)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BillTracer — Bill Evolution (Appropriations)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>BillTracer — Bill Evolution (Appropriations)</h1>
    <small class="muted">{html.escape(BILL_ID)} — Comparing <strong>{html.escape(STAGE_A)}</strong> → <strong>{html.escape(STAGE_B)}</strong> • Generated {now}</small>
    <div class="counts">
      <span>Modified: <strong>{stats['modified']}</strong></span>
      <span>Added: <strong>{stats['added']}</strong></span>
      <span>Removed: <strong>{stats['removed']}</strong></span>
    </div>
    <div class="top5">
      <strong>Top likely funding changes</strong>
      <ul>{top5_html}</ul>
    </div>
  </header>
  <div class="wrap">
    <nav>
      {"".join(nav_items) if nav_items else "<em>No changes detected or structure headers not found — showing any full-text differences below.</em>"}
    </nav>
    <main>
      {"".join(blocks) if blocks else "<p>No changed sections to display. If this persists, verify the two files are different and not short 404 pages.</p>"}
    </main>
  </div>
</body>
</html>
"""
    return html_doc

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not V1_PATH.exists() or not V2_PATH.exists():
        raise SystemExit("Place bill_v1.txt and bill_v2.txt in the data/ folder (run your fetch script).")

    v1 = load_text(V1_PATH)
    v2 = load_text(V2_PATH)

    s1 = split_sections(v1)
    s2 = split_sections(v2)

    d1 = index_by_id(s1)
    d2 = index_by_id(s2)

    changes, stats = summarize_changes(d1, d2)
    out_html = build_html(changes, stats)

    out_path = OUTPUT_DIR / "index.html"
    out_path.write_text(out_html, encoding="utf-8")
    print(f"Done. Open {out_path}.")

if __name__ == "__main__":
    main()
