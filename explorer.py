#!/usr/bin/env python3
# BillTracer — Bill Evolution Viewer (no external deps)
# Reads data/bill_v1.txt and data/bill_v2.txt, writes output/index.html

import re, html, difflib, datetime, json
from pathlib import Path
from typing import List, Dict, Tuple

# ---------- Branding ----------
BILL_ID  = "BillTracer — H.R. 748 (CARES Act vehicle)"
STAGE_A  = "Introduced (IH)"
STAGE_B  = "Enrolled (ENR)"
FORCE_FULLTEXT = False     # set True to ignore sectioning and redline the whole doc
SHOW_UNCHANGED = False     # default toggle when the page opens
# -----------------------------

DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")
V1_PATH    = DATA_DIR / "bill_v1.txt"
V2_PATH    = DATA_DIR / "bill_v2.txt"

# ---------- Text cleanup ----------
def sanitize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" \s*([,.;:])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s); s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\[\s+", "[", s); s = re.sub(r"\s+\]", "]", s)
    # unwrap within paragraphs (keep blank lines as paragraph breaks)
    out, buf = [], []
    for ln in s.split("\n"):
        t = ln.strip()
        if not t:
            if buf: out.append(" ".join(buf)); buf = []
            out.append("")
            continue
        buf.append(t)
        if re.search(r"[.;:)]\s*$", t):  # end of sentence-ish
            out.append(" ".join(buf)); buf = []
    if buf: out.append(" ".join(buf))
    s = "\n".join(out)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s

def load_text(path: Path) -> str:
    return sanitize_text(path.read_text(encoding="utf-8", errors="ignore"))

# ---------- Structure detection ----------
SEC_RE       = re.compile(r'^(?:SEC\.|Sec\.|SECTION|Section)\s+(\d+[A-Za-z\-]*)[.: ]', re.MULTILINE)
TITLE_RE     = re.compile(r'^(?:TITLE\s+[IVXLC]+(?:\s*[\u2014—-].*)?)$', re.MULTILINE)
DIVISION_RE  = re.compile(r'^(?:DIVISION\s+[A-Z](?:\s*[\u2014—-].*)?)$', re.MULTILINE)
SUBTITLE_RE  = re.compile(r'^(?:SUBTITLE\s+[A-Z](?:\s*[\u2014—-].*)?)$', re.MULTILINE)

def _split_by_matches(raw: str, matches: List[re.Match], id_prefix: str) -> List[Dict]:
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end   = matches[i+1].start() if i+1 < len(matches) else len(raw)
        header = m.group(0).strip()
        chunk  = raw[start:end].strip()
        sec_id = f"{id_prefix}{i+1:03d}"
        title  = header
        body   = chunk[len(header):].strip()
        blocks.append({"sec_id": sec_id, "title": title, "body": body})
    return blocks

def split_sections(raw: str) -> List[Dict]:
    sec = list(SEC_RE.finditer(raw))
    if sec:
        out = []
        for i, m in enumerate(sec):
            sid   = m.group(1)
            start = m.start()
            end   = sec[i+1].start() if i+1 < len(sec) else len(raw)
            block = raw[start:end].strip()
            head  = block.split("\n", 1)[0]
            m2 = re.search(r'^(?:SEC\.|Sec\.|SECTION|Section)\s+\d+[A-Za-z\-]*[.: ]\s*(.*)$', head)
            title = (m2.group(1).strip() if m2 else head) or f"Section {sid}"
            body  = block[len(head):].strip()
            out.append({"sec_id": sid, "title": title, "body": body})
        return out
    for rx, pref in [(DIVISION_RE, "DIV"), (TITLE_RE, "TITLE"), (SUBTITLE_RE, "SUB")]:
        m = list(rx.finditer(raw))
        if m: return _split_by_matches(raw, m, pref)
    return [{"sec_id":"ALL", "title":"FULL TEXT", "body":raw.strip()}]

def index_by_id(sections: List[Dict]) -> Dict[str, Dict]:
    return {s["sec_id"]: s for s in sections}

# ---------- Diffing ----------
TOKEN_RE = re.compile(r"\S+|\s+")
def escape(s: str) -> str: return html.escape(s, quote=False)

def diff_words_preserve_ws(a: str, b: str) -> str:
    a_tok = TOKEN_RE.findall(a)
    b_tok = TOKEN_RE.findall(b)
    sm = difflib.SequenceMatcher(a=a_tok, b=b_tok)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        A = "".join(a_tok[i1:i2]); B = "".join(b_tok[j1:j2])
        if tag == "equal":
            out.append(escape(A))
        elif tag == "delete":
            out.append(f"<del>{escape(A)}</del>")
        elif tag == "insert":
            out.append(f"<ins>{escape(B)}</ins>")
        else:
            out.append(f"<del>{escape(A)}</del><ins>{escape(B)}</ins>")
    return "".join(out)

# ---------- Heuristics & tags ----------
APPROPS_HINTS = re.compile(
    r'(\$\s?\d|\bappropriat(?:e|ion|ed|ions)\b|\bauthorized to be appropriated\b|'
    r'\btransfer\b|\bobligation\b|\bresciss|\boffset\b|\bgrant\b|\bfund(?:s|ing)?\b|'
    r'\bremain available\b)',
    re.IGNORECASE
)
def categorize_change(before: str, after: str) -> List[str]:
    tags = set()
    t = (before + " " + after).lower()
    if re.search(r'(\$[\s]?\d|\bappropriat|\bauthorized to be appropriated|\bgrant\b|\bfund(?:s|ing)?)', t):
        tags.add("Funding")
    if re.search(r'\bshall\b|\bmay not\b|\bpenalt', t):
        tags.add("Authority")
    if re.search(r'not later than|\breport to congress|\bgao\b|\breporting requirement', t):
        tags.add("Reporting")
    return sorted(tags)

# ---------- Summarize ----------
def summarize_changes(old_by_id: Dict[str, Dict], new_by_id: Dict[str, Dict]) -> Tuple[List[Dict], Dict[str,int], List[Dict]]:
    changes: List[Dict] = []
    unchanged: List[Dict] = []
    stats = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}
    all_ids = sorted(set(old_by_id) | set(new_by_id), key=lambda x: (x=="ALL", len(x), x))
    for sid in all_ids:
        old = old_by_id.get(sid); new = new_by_id.get(sid)
        if old and not new:
            stats["removed"] += 1
            changes.append({
                "sec_id": sid, "title": old["title"], "status": "Removed",
                "tags": [], "is_approp": bool(APPROPS_HINTS.search(old["body"])),
                "redline": "<del>Section removed in newer version.</del>"
            })
            continue
        if new and not old:
            stats["added"] += 1
            changes.append({
                "sec_id": sid, "title": new["title"], "status": "Added",
                "tags": categorize_change("", new["body"]),
                "is_approp": bool(APPROPS_HINTS.search(new["body"])),
                "redline": f"<ins>{escape(new['body'])}</ins>"
            })
            continue
        if old and new:
            A = old["body"].strip(); B = new["body"].strip()
            if A == B:
                stats["unchanged"] += 1
                unchanged.append({"sec_id": sid, "title": new["title"] or old["title"], "body": A})
                continue
            stats["modified"] += 1
            changes.append({
                "sec_id": sid, "title": (new["title"] or old["title"]),
                "status": "Modified",
                "tags": categorize_change(A, B),
                "is_approp": bool(APPROPS_HINTS.search(A + " " + B)),
                "redline": diff_words_preserve_ws(A, B)
            })
    changes.sort(key=lambda x: (not x["is_approp"], x["sec_id"]))
    return changes, stats, unchanged

# ---------- HTML ----------
CSS = """
:root { --stick: 98px; }
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;margin:0;color:#111827;background:#fff}
header{padding:14px 20px;border-bottom:1px solid #eef2f7;position:sticky;top:0;background:#fff;z-index:5}
.wrap{display:flex;min-height:100vh}
nav{width:340px;border-right:1px solid #eef2f7;padding:12px;position:sticky;top:var(--stick);height:calc(100vh - var(--stick));overflow:auto;background:#fafbff}
main{flex:1;padding:16px 24px}
h1{margin:0 0 6px 0;font-size:20px}
small.muted{color:#6b7280}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.controls input[type="text"]{flex:1;min-width:200px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px}
.btn{padding:6px 10px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;cursor:pointer;font-size:13px}
.btn.active{background:#eef2ff;border-color:#c7d2fe}
.chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;margin-right:6px;background:#f3f4f6;border:1px solid #e5e7eb}
.chip.status.Modified{background:#fff7d6;border-color:#f6e39c}
.chip.status.Added{background:#e8fae8;border-color:#bfecc3}
.chip.status.Removed{background:#ffe7e6;border-color:#f5b5b2}
.chip.tag{background:#e9eefc;border-color:#c9d6ff}
.chip.approp{background:#ffe9c2;border-color:#ffd392}
.counts span{margin-right:12px}
.top5{background:#f7faff;border:1px solid #e5ecff;padding:10px;border-radius:8px;margin-top:10px}
.toc-link{display:block;padding:8px;border-left:3px solid transparent;border-radius:6px;margin-bottom:6px;text-decoration:none;color:#1f2937}
.toc-link:hover{background:#eef2ff}
.toc-link .sub{display:block;color:#6b7280;font-size:12px}
section.block{border-bottom:1px solid #eef2f7;padding:18px 0}
section.block h3{margin:0 0 6px 0;font-size:16px}
section.block pre{white-space:pre-wrap;word-wrap:break-word;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#fafafa;padding:12px;border-radius:8px;border:1px solid #eee}
ins{background:#dbffdb;text-decoration:none}
del{background:#ffd9d9;text-decoration:line-through}
:target{scroll-margin-top:calc(var(--stick)+8px)}
hr.sep{border:none;border-top:1px dashed #e5e7eb;margin:18px 0}
.empty{color:#6b7280}
"""

JS = """
(() => {
  const q = (s, el=document) => el.querySelector(s);
  const qa = (s, el=document) => [...el.querySelectorAll(s)];
  const search = q('#search');
  const btns = qa('.btn[data-filter]');
  const toggleUnchanged = q('#toggle-unchanged');
  const cards = qa('section.block');

  function apply() {
    const text = (search.value || '').toLowerCase();
    const want = new Set(qa('.btn.active').map(b => b.dataset.filter));
    const showUnchanged = toggleUnchanged.checked;

    cards.forEach(card => {
      const tags = card.dataset.tags.split(',');
      const status = card.dataset.status;
      const title = card.dataset.title.toLowerCase();
      const id = card.id.toLowerCase();

      let ok = true;

      if (want.size) {
        ok = tags.some(t => want.has(t)) || want.has(status);
      }
      if (ok && text) {
        ok = title.includes(text) || id.includes(text) || card.textContent.toLowerCase().includes(text);
      }
      if (ok && !showUnchanged && status === 'Unchanged') {
        ok = false;
      }
      card.style.display = ok ? '' : 'none';
    });
  }

  btns.forEach(b => b.addEventListener('click', () => {
    b.classList.toggle('active');
    apply();
  }));
  [search, toggleUnchanged].forEach(el => el.addEventListener('input', apply));

  // Initial
  apply();
})();
"""

def build_html(change_log: List[Dict], stats: Dict[str,int], unchanged: List[Dict]) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    def first_change_anchor(sec_id: str, redline_html: str):
        anchor_id = f"{sec_id}-chg"
        m = re.search(r"<(ins|del)\\b", redline_html)
        if not m:
            return sec_id, redline_html
        new_html = re.sub(r"<(ins|del)\\b", f'<a id="{anchor_id}"></a><\\1', redline_html, count=1)
        return anchor_id, new_html

    # left nav
    nav_items = []
    # right side blocks
    blocks = []

    for ch in change_log:
        anchor_id, body_html = first_change_anchor(ch["sec_id"], ch["redline"])
        tags = " ".join(f"<span class='chip tag'>{t}</span>" for t in ch["tags"])
        app  = "<span class='chip approp'>Appropriations</span>" if ch["is_approp"] else ""
        nav_items.append(
            f"<a class='toc-link' href='#{html.escape(anchor_id)}'>"
            f"<span class='chip status {ch['status']}'>{ch['status']}</span> "
            f"<strong>{html.escape(ch['sec_id'])}</strong>"
            f"<span class='sub'>{html.escape(ch['title'][:100])}</span></a>"
        )
        blocks.append(
            f"<section class='block' id='{html.escape(ch['sec_id'])}' "
            f"data-status='{ch['status']}' data-tags='{','.join(ch['tags'])}' data-title='{html.escape(ch['title'])}'>"
            f"<h3>{html.escape(ch['title'])}</h3>"
            f"<div>{app} <span class='chip status {ch['status']}'>{ch['status']}</span> {tags}</div>"
            f"<pre>{body_html}</pre>"
            f"</section>"
        )

    # unchanged (hidden by default unless toggled)
    for u in unchanged:
        blocks.append(
            f"<section class='block' id='{html.escape(u['sec_id'])}' "
            f"data-status='Unchanged' data-tags='' data-title='{html.escape(u['title'])}' style='display:none;'>"
            f"<h3>{html.escape(u['title'])}</h3>"
            f"<div><span class='chip'>Unchanged</span></div>"
            f"<pre>{escape(u['body'])}</pre>"
            f"</section>"
        )

    # top likely funding changes
    top5 = [c for c in change_log if c['is_approp']][:5]
    top5_html = "".join(
        f"<li><a href='#{html.escape(c['sec_id'] + '-chg')}'>{html.escape(c['sec_id'])}</a> — "
        f"{html.escape(c['title'][:140])} <span class='chip status {c['status']}'>{c['status']}</span></li>"
        for c in top5
    ) or "<li>No likely funding changes found.</li>"

    # filters
    controls = """
      <div class="controls">
        <input id="search" type="text" placeholder="Filter by text, section id, or content…" />
        <button class="btn" data-filter="Modified">Modified</button>
        <button class="btn" data-filter="Added">Added</button>
        <button class="btn" data-filter="Removed">Removed</button>
        <button class="btn" data-filter="Funding">Funding</button>
        <button class="btn" data-filter="Authority">Authority</button>
        <button class="btn" data-filter="Reporting">Reporting</button>
        <label style="display:flex;align-items:center;gap:6px;margin-left:auto;">
          <input id="toggle-unchanged" type="checkbox" %s /> Show unchanged
        </label>
      </div>
    """ % ("checked" if SHOW_UNCHANGED else "")

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>BillTracer — Bill Evolution</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>BillTracer — Bill Evolution (Appropriations)</h1>
  <small class="muted">{escape(BILL_ID)} — Comparing <strong>{escape(STAGE_A)}</strong> → <strong>{escape(STAGE_B)}</strong> • Generated {now}</small>
  <div class="counts">
    <span>Modified: <strong>{stats['modified']}</strong></span>
    <span>Added: <strong>{stats['added']}</strong></span>
    <span>Removed: <strong>{stats['removed']}</strong></span>
    <span>Unchanged: <strong>{stats['unchanged']}</strong></span>
  </div>
  <div class="top5">
    <strong>Top likely funding changes</strong>
    <ul>{top5_html}</ul>
  </div>
</header>

<div class="wrap">
  <nav>
    {controls}
    {"".join(nav_items) if nav_items else "<em class='empty'>No changed sections detected.</em>"}
  </nav>
  <main>
    {"".join(blocks) if blocks else "<p class='empty'>No changed sections to display. Check that your two files differ and aren’t error pages.</p>"}
  </main>
</div>

<script>{JS}</script>
</body>
</html>
"""
    return html_doc

# ---------- Main ----------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not V1_PATH.exists() or not V2_PATH.exists():
        raise SystemExit("Place bill_v1.txt and bill_v2.txt in data/")
    v1 = load_text(V1_PATH)
    v2 = load_text(V2_PATH)

    if FORCE_FULLTEXT:
        s1 = [{"sec_id":"ALL","title":"FULL TEXT (v1)","body":v1}]
        s2 = [{"sec_id":"ALL","title":"FULL TEXT (v2)","body":v2}]
    else:
        s1 = split_sections(v1)
        s2 = split_sections(v2)

    d1 = index_by_id(s1); d2 = index_by_id(s2)
    changes, stats, unchanged = summarize_changes(d1, d2)
    out_html = build_html(changes, stats, unchanged)
    (OUTPUT_DIR / "index.html").write_text(out_html, encoding="utf-8")
    print("✅ Done. Open output/index.html in your browser.")

if __name__ == "__main__":
    main()
