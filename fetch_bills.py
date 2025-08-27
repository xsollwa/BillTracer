import os, re, time, requests

# ---- editable per bill ----
CONGRESS = 116
CHAMBER  = "house"   # "house" or "senate"
BILL_NUM = 748
VER_A    = "ih"      # ih, rh, eh, enr, ...
VER_B    = "enr"
# ---------------------------

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

def chamber_path(chamber: str) -> str:
    return "house-bill" if chamber.lower().startswith("h") else "senate-bill"

def billtype(chamber: str) -> str:
    return "hr" if chamber.lower().startswith("h") else "s"

def pkg_id(cong: int, chamber: str, num: int, ver: str) -> str:
    return f"BILLS-{cong}{billtype(chamber)}{num}{ver.lower()}"

def url_candidates(cong: int, chamber: str, num: int, ver: str):
    """Try multiple mirrors. Bulk XML is the most reliable for older bills."""
    bp  = chamber_path(chamber)
    bt  = billtype(chamber)
    pkg = pkg_id(cong, chamber, num, ver)

    # Congress.gov (often 403 on some networks)
    cg_txt  = f"https://www.congress.gov/bill/{cong}th-congress/{bp}/{num}/text/{ver.lower()}?format=txt"
    cg_html = f"https://www.congress.gov/bill/{cong}th-congress/{bp}/{num}/text/{ver.lower()}"

    # GovInfo content (TXT/HTM sometimes short), but XML usually good:
    gi_txt  = f"https://www.govinfo.gov/content/pkg/{pkg}/txt/{pkg}.txt"
    gi_htm  = f"https://www.govinfo.gov/content/pkg/{pkg}/htm/{pkg}.htm"
    gi_xml  = f"https://www.govinfo.gov/content/pkg/{pkg}/xml/{pkg}.xml"  # ✅ add this

    # GPO Bulk Data (corrected path — no bill number folder):
    bulk_xml = f"https://www.govinfo.gov/bulkdata/BILLS/{cong}/{bt}/BILLS-{cong}{bt}{num}{ver.lower()}.xml"
    bulk_htm = f"https://www.govinfo.gov/bulkdata/BILLS/{cong}/{bt}/BILLS-{cong}{bt}{num}{ver.lower()}.htm"

    return [
        ("cg_txt",  cg_txt),
        ("cg_html", cg_html),
        ("gi_txt",  gi_txt),
        ("gi_htm",  gi_htm),
        ("gi_xml",  gi_xml),
        ("bulk_xml", bulk_xml),
        ("bulk_htm", bulk_htm),
    ]

def fetch_raw(url: str) -> str:
    r = S.get(url, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return r.text

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
    # Very simple USLM-ish flattening; enough for diffs
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
    last_err = None
    for kind, url in url_candidates(cong, chamber, num, ver):
        try:
            print(f"Fetching [{kind}] {url} …")
            raw = fetch_raw(url)
            if kind in ("cg_txt", "gi_txt"):
                text = raw.replace("\r\n", "\n")
            elif kind in ("cg_html", "gi_htm", "bulk_htm"):
                text = html_to_text(raw)
            else:  # gi_xml, bulk_xml
                text = xml_to_text(raw)

            if looks_like_error(text):
                raise RuntimeError("Response looks like an error or too short.")
            return text
        except Exception as e:
            last_err = e
            print(f"  -> {kind} failed: {e}")
            time.sleep(0.5)
    raise RuntimeError(f"All sources failed for version {ver} — last error: {last_err}")

def main():
    os.makedirs("data", exist_ok=True)
    v1 = fetch_version(CONGRESS, CHAMBER, BILL_NUM, VER_A)
    v2 = fetch_version(CONGRESS, CHAMBER, BILL_NUM, VER_B)
    if v1 == v2:
        print("WARNING: v1 and v2 identical; try different versions (IH vs EH/ENR).")
    open("data/bill_v1.txt","w",encoding="utf-8").write(v1)
    open("data/bill_v2.txt","w",encoding="utf-8").write(v2)
    print("Saved data/bill_v1.txt and data/bill_v2.txt")

if __name__ == "__main__":
    main()
