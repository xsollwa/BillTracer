#!/usr/bin/env python3


import re, html, difflib, datetime, time
from typing import List, Dict, Tuple
from flask import Flask, request, abort
import requests

app = Flask(__name__)

# visible build banner 
APP_VERSION = "BillTracer v3 — strict-diff + fixed filters (77.7%)"
print(">>> Starting", APP_VERSION)

@app.get("/version")
def version():
    return APP_VERSION

# good demo bills 
PRESETS = {
    "hr3684-117": dict(congress=117, chamber="house", number=3684, v1="ih",  v2="enr",
                       label="H.R. 3684 (117th) — Infrastructure Investment & Jobs Act"),
    "hr748-116":  dict(congress=116, chamber="house", number=748,  v1="ih",  v2="enr",
                       label="H.R. 748 (116th) — CARES Act vehicle"),
    "hr133-116":  dict(congress=116, chamber="house", number=133,  v1="ih",  v2="enr",
                       label="H.R. 133 (116th) — Consolidated Appropriations Act, 2021"),
}

# HTTP session
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

# tiny cache (html per preset)
CACHE: Dict[str, Tuple[float, str]] = {}
CACHE_TTL = 6 * 60 * 60

# quick flush route (handy while iterating)
@app.get("/flush")
def flush_cache():
    CACHE.clear()
    return "CACHE cleared"

# fetching

def chamber_path(chamber: str) -> str:
    return "house-bill" if chamber.lower().startswith("h") else "senate-bill"

def billtype(chamber: str) -> str:
    return "hr" if chamber.lower().startswith("h") else "s"

def pkg_id(cong: int, chamber: str, num: int, ver: str) -> str:
    return f"BILLS-{cong}{billtype(chamber)}{num}{ver.lower()}"

def url_candidates(cong: int, chamber: str, num: int, ver: str):
    bp  = chamber_path(chamber)
    bt  = billtype(chamber)
    pkg = pkg_id(cong, chamber, num, ver)

    cg_txt  = f"https://www.congress.gov/bill/{cong}th-congress/{bp}/{num}/text/{ver.lower()}?format=txt"
    cg_html = f"https://www.congress.gov/bill/{cong}th-congress/{bp}/{num}/text/{ver.lower()}"

    gi_txt  = f"https://www.govinfo.gov/content/pkg/{pkg}/txt/{pkg}.txt"
    gi_htm  = f"https://www.govinfo.gov/content/pkg/{pkg}/htm/{pkg}.htm"
    gi_xml  = f"https://www.govinfo.gov/content/pkg/{pkg}/xml/{pkg}.xml"

    bulk_xml = f"https://www.govinfo.gov/bulkdata/BILLS/{cong}/{bt}/BILLS-{cong}{bt}{num}{ver.lower()}.xml"
    bulk_htm = f"https://www.govinfo.gov/bulkdata/BILLS/{cong}/{bt}/BILLS-{cong}{bt}{num}{ver.lower()}.htm"

    return [
        ("gi_txt",  gi_txt),
        ("gi_xml",  gi_xml),
        ("gi_htm",  gi_htm),
        ("bulk_xml", bulk_xml),
        ("bulk_htm", bulk_htm),
        ("cg_txt",  cg_txt),
        ("cg_html", cg_html),
    ]

def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p>", "\n\n", s)
    s = re.sub(r"(?is)</(h\d|div|section|li|tr|td|thead|tbody)>", "\n", s)
    s = re.sub(r"(?is)<li[^>]*>", " • ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()

def xml_to_text(s: str) -> str:
    block_tags = r"(officialTitle|shortTitle|longTitle|title|section|subsection|paragraph|subparagraph|text|quotedBlock)"
    s = re.sub(fr"(?is)<{block_tags}[^>]*>", "\n", s)
    s = re.sub(fr"(?is)</{block_tags}>", "\n", s)
    s = re.sub(r"(?is)<note[^>]*>", " (Note: ", s)
    s = re.sub(r"(?is)</note>", ") ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()

def looks_like_error(text: str) -> bool:
    if len(text.strip()) < 800:
        return True
    if re.search(r"(Page Not Found|Error occurred|cannot be found|Access Denied|Forbidden|Drupal|govinfo error)", text, re.I):
        return True
    return False

def fetch_version(cong: int, chamber: str, num: int, ver: str) -> str:
    last = None
    for kind, url in url_candidates(cong, chamber, num, ver):
        try:
            r = S.get(url, timeout=60, allow_redirects=True)
            r.raise_for_status()
            raw = r.text
            if kind.endswith("txt"):
                t = raw.replace("\r\n", "\n")
            elif kind.endswith("xml"):
                t = xml_to_text(raw)
            else:
                t = html_to_text(raw)
            if looks_like_error(t):
                raise RuntimeError("short/error")
            return t
        except Exception as e:
            last = e
            time.sleep(0.2)
            continue
    raise RuntimeError(f"failed to fetch {ver}: {last}")

# diff & structure
def sanitize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" \s*([,.;:])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s); s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\[\s+", "[", s); s = re.sub(r"\s+\]", "]", s)
    out, buf = [], []
    for ln in s.split("\n"):
        t = ln.strip()
        if not t:
            if buf: out.append(" ".join(buf)); buf = []
            out.append("")
            continue
        buf.append(t)
        if re.search(r"[.;:)]\s*$", t):
            out.append(" ".join(buf)); buf = []
    if buf: out.append(" ".join(buf))
    s = "\n".join(out)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s

# STRICT header: only "SEC./Sec." at line-start (avoids references like “section 12 U.S.C.”)
SEC_RE = re.compile(r'^(?:SEC\.|Sec\.)\s+(\d+[A-Za-z\-]*)[.: ]', re.MULTILINE)

# broader fallbacks if no SEC headings are found
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
    # if we found sane number of real sections, use them
    if sec and len(sec) <= 800:
        out = []
        for i, m in enumerate(sec):
            sid   = m.group(1)
            start = m.start()
            end   = sec[i+1].start() if i+1 < len(sec) else len(raw)
            block = raw[start:end].strip()
            head  = block.split("\n", 1)[0]
            m2 = re.search(r'^(?:SEC\.|Sec\.)\s+\d+[A-Za-z\-]*[.: ]\s*(.*)$', head)
            title = (m2.group(1).strip() if m2 else head) or f"Section {sid}"
            body  = block[len(head):].strip()
            out.append({"sec_id": sid, "title": title, "body": body})
        return out
    # fallbacks
    for rx, pref in [(DIVISION_RE, "DIV"), (TITLE_RE, "TITLE"), (SUBTITLE_RE, "SUB")]:
        m = list(rx.finditer(raw))
        if m:
            return _split_by_matches(raw, m, pref)
    # last resort
    return [{"sec_id":"ALL", "title":"FULL TEXT", "body":raw.strip()}]

def index_by_id(sections: List[Dict]) -> Dict[str, Dict]:
    return {s["sec_id"]: s for s in sections}

TOKEN_RE = re.compile(r"\S+|\s+")
def esc(s: str) -> str: return html.escape(s, quote=False)

def diff_words_preserve_ws(a: str, b: str) -> str:
    a_tok = TOKEN_RE.findall(a)
    b_tok = TOKEN_RE.findall(b)
    sm = difflib.SequenceMatcher(a=a_tok, b=b_tok)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        A = "".join(a_tok[i1:i2]); B = "".join(b_tok[j1:j2])
        if tag == "equal":
            out.append(esc(A))
        elif tag == "delete":
            out.append(f"<del>{esc(A)}</del>")
        elif tag == "insert":
            out.append(f"<ins>{esc(B)}</ins>")
        else:
            out.append(f"<del>{esc(A)}</del><ins>{esc(B)}</ins>")
    return "".join(out)

MIN_DIFF_TOKENS = 80          # ignore micro-changes smaller than 6 tokens total
MIN_EQUAL_RATIO = 0.777         # 77.7% similarity or higher => treat as unchanged

def _tokenize_for_ratio(s: str) -> list:
    # coalesce whitespace to single spaces to reduce formatting noise
    s = re.sub(r"\s+", " ", s.strip())
    return s.split(" ") if s else []

def diff_magnitude(a: str, b: str) -> Tuple[int, float]:
    """Return (changed_token_count, equal_ratio) using a token diff that
    down-weights whitespace-only edits."""
    a_t = _tokenize_for_ratio(a)
    b_t = _tokenize_for_ratio(b)
    sm = difflib.SequenceMatcher(a=a_t, b=b_t, autojunk=False)
    equal = 0
    total = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            equal += (i2 - i1)
        total += max(i2 - i1, j2 - j1)
    equal_ratio = (equal / total) if total else 1.0

    # approximate "changed tokens" as the non-equal portion
    changed = total - equal
    return changed, equal_ratio

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

def summarize_changes(old_by_id: Dict[str, Dict], new_by_id: Dict[str, Dict]) -> Tuple[List[Dict], Dict[str,int], List[Dict]]:
    changes: List[Dict] = []
    unchanged: List[Dict] = []
    stats = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}

    def _sort_key(x: str):
        # numeric-ish ids first (SEC. numbers), then strings
        return (len(x), x)

    all_ids = sorted(set(old_by_id) | set(new_by_id), key=_sort_key)

    for sid in all_ids:
        old = old_by_id.get(sid)
        new = new_by_id.get(sid)

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
                "redline": f"<ins>{esc(new['body'])}</ins>"
            })
            continue

        if old and new:
            A = (old["body"] or "").strip()
            B = (new["body"] or "").strip()

            # identical after cleanup
            if A == B:
                stats["unchanged"] += 1
                unchanged.append({"sec_id": sid, "title": new["title"] or old["title"], "body": A})
                continue

            # magnitude guard: ignore micro/formatting changes
            changed_tokens, ratio = diff_magnitude(A, B)
            if changed_tokens < MIN_DIFF_TOKENS or ratio >= MIN_EQUAL_RATIO:
                stats["unchanged"] += 1
                unchanged.append({"sec_id": sid, "title": new["title"] or old["title"], "body": B})
                continue

            stats["modified"] += 1
            changes.append({
                "sec_id": sid,
                "title": new["title"] or old["title"],
                "status": "Modified",
                "tags": categorize_change(A, B),
                "is_approp": bool(APPROPS_HINTS.search(A + " " + B)),
                "redline": diff_words_preserve_ws(A, B)
            })

    # Prioritize likely appropriations changes to the top
    changes.sort(key=lambda x: (not x["is_approp"], x["sec_id"]))
    return changes, stats, unchanged

# UI (viewer)
CSS = """
:root { --stick: 98px; }
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;margin:0;color:#111827;background:#fff}
header{padding:14px 20px;border-bottom:1px solid #eef2f7;position:sticky;top:0;background:#fff;z-index:8}
.toolbar{display:flex;gap:8px;align-items:center;margin:8px 0}
select,button{padding:8px 10px;font-size:15px}
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
.empty{color:#6b7280}
"""

JS = """
(() => {
  const q  = (s, el=document) => el.querySelector(s);
  const qa = (s, el=document) => Array.from(el.querySelectorAll(s));

  // filters
  function wireFilters(){
    const search = q('#search');
    const btns = qa('.btn[data-filter]');
    const toggleUnchanged = q('#toggle-unchanged');
    const cards = qa('section.block');

    function apply() {
      const text = (search?.value || '').toLowerCase();
      const want = new Set(qa('.btn.active').map(b => b.dataset.filter));
      const showUnchanged = !!(toggleUnchanged && toggleUnchanged.checked);

      cards.forEach(card => {
        const tags = (card.dataset.tags || '').split(',').filter(Boolean);
        const status = card.dataset.status || '';
        const title = (card.dataset.title || '').toLowerCase();
        const id = (card.id || '').toLowerCase();

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

    btns.forEach(b => b.addEventListener('click', () => { b.classList.toggle('active'); apply(); }));
    if (search) search.addEventListener('input', apply);
    if (toggleUnchanged) toggleUnchanged.addEventListener('input', apply);
    apply();
  }

  // bill switcher (keeps dropdown on viewer)
  function wireSwitcher(){
    const sel = q('#bill-switch');
    const btn = q('#go-switch');
    if (!sel || !btn) return;
    btn.addEventListener('click', () => {
      window.location = '/view?preset=' + encodeURIComponent(sel.value) + '&nocache=1';
    });
  }

  wireFilters();
  wireSwitcher();
})();
"""

def build_html(label: str, stage_a: str, stage_b: str, changes, stats, unchanged, preset_key: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    def first_anchor(sec_id: str, redline_html: str):
        anchor_id = f"{sec_id}-chg"
        m = re.search(r"<(ins|del)\\b", redline_html)
        if not m: return sec_id, redline_html
        return anchor_id, re.sub(r"<(ins|del)\\b", f'<a id="{anchor_id}"></a><\\1', redline_html, count=1)

    nav_items, blocks = [], []
    for ch in changes:
        anchor_id, body_html = first_anchor(ch["sec_id"], ch["redline"])
        tags = " ".join(f"<span class='chip tag'>{t}</span>" for t in ch["tags"])
        app  = "<span class='chip approp'>Appropriations</span>" if ch["is_approp"] else ""
        nav_items.append(
            f"<a class='toc-link' href='#{esc(anchor_id)}'>"
            f"<span class='chip status {ch['status']}'>{ch['status']}</span> "
            f"<strong>{esc(ch['sec_id'])}</strong>"
            f"<span class='sub'>{esc(ch['title'][:100])}</span></a>"
        )
        blocks.append(
            f"<section class='block' id='{esc(ch['sec_id'])}' "
            f"data-status='{ch['status']}' data-tags='{','.join(ch['tags'])}' data-title='{esc(ch['title'])}'>"
            f"<h3>{esc(ch['title'])}</h3>"
            f"<div>{app} <span class='chip status {ch['status']}'>{ch['status']}</span> {tags}</div>"
            f"<pre>{body_html}</pre>"
            f"</section>"
        )

    for u in unchanged:
        blocks.append(
            f"<section class='block' id='{esc(u['sec_id'])}' "
            f"data-status='Unchanged' data-tags='' data-title='{esc(u['title'])}' style='display:none;'>"
            f"<h3>{esc(u['title'])}</h3>"
            f"<div><span class='chip'>Unchanged</span></div>"
            f"<pre>{esc(u['body'])}</pre>"
            f"</section>"
        )

    top5 = [c for c in changes if c['is_approp']][:5]
    top5_html = "".join(
        f"<li><a href='#{esc(c['sec_id'] + '-chg')}'>{esc(c['sec_id'])}</a> — "
        f"{esc(c['title'][:140])} <span class='chip status {c['status']}'>{c['status']}</span></li>"
        for c in top5
    ) or "<li>No likely funding changes found.</li>"

    options = "".join(
        f"<option value='{esc(k)}' {'selected' if k==preset_key else ''}>{esc(v['label'])}</option>"
        for k, v in PRESETS.items()
    )

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
          <input id="toggle-unchanged" type="checkbox" /> Show unchanged
        </label>
      </div>
    """

    small_line = (f"{esc(label)} — Comparing <strong>{esc(stage_a)}</strong> → "
                  f"<strong>{esc(stage_b)}</strong> • {APP_VERSION} • Generated {now}")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>BillTracer — Bill Evolution</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>{CSS}</style>
</head>
<body>
<header>
  <div class="toolbar">
    <select id="bill-switch">{options}</select>
    <button id="go-switch">View comparison</button>
  </div>
  <h1>BillTracer — Bill Evolution (Appropriations)</h1>
  <small class="muted">{small_line}</small>
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
    {"".join(blocks) if blocks else "<p class='empty'>No changed sections to display.</p>"}
  </main>
</div>
<script>{JS}</script>
</body>
</html>"""

# routes
@app.get("/")
def index():
    # immediate redirect to viewer with the first preset selected
    first = next(iter(PRESETS.keys()))
    return ("<script>location='/view?preset="+first+"'</script>")

@app.get("/view")
def view():
    preset_key = request.args.get("preset")
    nocache = request.args.get("nocache") == "1" 

    if preset_key not in PRESETS:
        abort(400, "bad preset")

    if (not nocache) and preset_key in CACHE:
        ts, html_doc = CACHE[preset_key]
        if (time.time() - ts) < CACHE_TTL:
            return html_doc

    cfg = PRESETS[preset_key]
    stage_map = {
        "ih":"Introduced (IH)", "rh":"Reported (RH)",
        "eh":"Engrossed (EH)",  "enr":"Enrolled (ENR)"
    }
    label   = cfg["label"]
    stage_a = stage_map.get(cfg["v1"].lower(), cfg["v1"].upper())
    stage_b = stage_map.get(cfg["v2"].lower(), cfg["v2"].upper())

    v1 = fetch_version(cfg["congress"], cfg["chamber"], cfg["number"], cfg["v1"])
    v2 = fetch_version(cfg["congress"], cfg["chamber"], cfg["number"], cfg["v2"])

    v1c, v2c = sanitize_text(v1), sanitize_text(v2)
    s1 = split_sections(v1c)
    s2 = split_sections(v2c)
    d1, d2 = index_by_id(s1), index_by_id(s2)
    changes, stats, unchanged = summarize_changes(d1, d2)

    html_doc = build_html(label, stage_a, stage_b, changes, stats, unchanged, preset_key)
    CACHE[preset_key] = (time.time(), html_doc)
    return html_doc


if __name__ == "__main__":
    # run dev server
    app.run(host="127.0.0.1", port=5000, debug=True)
