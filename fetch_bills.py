# Fetch two versions of a bill (Congress.gov + GovInfo), write data/bill_v1.txt, data/bill_v2.txt, data/meta.json
import os, re, time, json, argparse, requests

PRESETS = {
    "hr748-116":  dict(congress=116, chamber="house", number=748,  v1="ih", v2="enr",
                       label="H.R. 748 (116th) — CARES Act vehicle"),
    "hr3684-117": dict(congress=117, chamber="house", number=3684, v1="ih", v2="enr",
                       label="H.R. 3684 (117th) — Infrastructure Investment & Jobs Act"),
    "hr133-116":  dict(congress=116, chamber="house", number=133,  v1="ih", v2="enr",
                       label="H.R. 133 (116th) — Consolidated Appropriations Act, 2021"),
}

CONGRESS = 116
CHAMBER  = "house"
BILL_NUM = 748
VER_A    = "ih"
VER_B    = "enr"

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
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
    return [("cg_txt",cg_txt),("cg_html",cg_html),("gi_txt",gi_txt),("gi_htm",gi_htm),("gi_xml",gi_xml),("bulk_xml",bulk_xml),("bulk_htm",bulk_htm)]

def fetch_raw(url: str) -> str:
    r = S.get(url, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return r.text

def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", s)
    s = re.sub(r"(?is)<br\\s*/?>", "\\n", s)
    s = re.sub(r"(?is)</p>", "\\n\\n", s)
    s = re.sub(r"(?is)</(h\\d|div|section|li|tr|td|thead|tbody)>", "\\n", s)
    s = re.sub(r"(?is)<li[^>]*>", " • ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = s.replace("\\u00A0", " ")
    s = re.sub(r"[ \\t]+", " ", s)
    s = re.sub(r"\\n\\s*\\n\\s*\\n+", "\\n\\n", s)
    return s.strip()

def xml_to_text(s: str) -> str:
    block_tags = r"(officialTitle|shortTitle|longTitle|title|section|subsection|paragraph|subparagraph|text|quotedBlock)"
    s = re.sub(fr"(?is)<{block_tags}[^>]*>", "\\n", s)
    s = re.sub(fr"(?is)</{block_tags}>", "\\n", s)
    s = re.sub(r"(?is)<note[^>]*>", " (Note: ", s)
    s = re.sub(r"(?is)</note>", ") ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = s.replace("\\u00A0", " ")
    s = re.sub(r"[ \\t]+", " ", s)
    s = re.sub(r"\\n\\s*\\n\\s*\\n+", "\\n\\n", s)
    return s.strip()

def looks_like_error(text: str) -> bool:
    if len(text.strip()) < 800: return True
    if re.search(r"(Page Not Found|Error occurred|cannot be found|Access Denied|Forbidden|Drupal|govinfo error)", text, re.I): return True
    return False

def fetch_version(cong: int, chamber: str, num: int, ver: str) -> str:
    last_err = None
    for kind, url in url_candidates(cong, chamber, num, ver):
        try:
            print(f"Fetching [{kind}] {url} …")
            raw = fetch_raw(url)
            if kind in ("cg_txt","gi_txt"):
                text = raw.replace("\r\n","\n")
            elif kind in ("cg_html","gi_htm","bulk_htm"):
                text = html_to_text(raw)
            else:
                text = xml_to_text(raw)
            if looks_like_error(text):
                raise RuntimeError("Response looks like an error or too short.")
            return text
        except Exception as e:
            last_err = e
            print(f"  -> {kind} failed: {e}")
            time.sleep(0.5)
    raise RuntimeError(f"All sources failed for version {ver} — last error: {last_err}")

def write_meta(label, v1, v2, preset_key):
    os.makedirs("data", exist_ok=True)
    stage_map = {"ih":"Introduced (IH)", "rh":"Reported (RH)", "eh":"Engrossed (EH)", "enr":"Enrolled (ENR)"}
    meta = {"bill_id": label, "stage_a": stage_map.get(v1.lower(), v1.upper()), "stage_b": stage_map.get(v2.lower(), v2.upper()), "preset": preset_key or "manual"}
    open("data/meta.json","w",encoding="utf-8").write(json.dumps(meta, ensure_ascii=False, indent=2))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preset", choices=list(PRESETS.keys()))
    p.add_argument("--congress", type=int)
    p.add_argument("--chamber", choices=["house","senate"])
    p.add_argument("--number", type=int)
    p.add_argument("--v1"); p.add_argument("--v2")
    args = p.parse_args()

    if args.preset:
        cfg = PRESETS[args.preset].copy()
        preset_key = args.preset
    else:
        cfg = dict(congress=args.congress or CONGRESS, chamber=args.chamber or CHAMBER, number=args.number or BILL_NUM,
                   v1=args.v1 or VER_A, v2=args.v2 or VER_B,
                   label=f"{'H.R.' if (args.chamber or CHAMBER)=='house' else 'S.'} {args.number or BILL_NUM} ({args.congress or CONGRESS}th)")
        preset_key = None

    os.makedirs("data", exist_ok=True)
    v1 = fetch_version(cfg["congress"], cfg["chamber"], cfg["number"], cfg["v1"])
    v2 = fetch_version(cfg["congress"], cfg["chamber"], cfg["number"], cfg["v2"])
    open("data/bill_v1.txt","w",encoding="utf-8").write(v1)
    open("data/bill_v2.txt","w",encoding="utf-8").write(v2)
    write_meta(cfg["label"], cfg["v1"], cfg["v2"], preset_key)
    print("Saved data/bill_v1.txt, data/bill_v2.txt, data/meta.json")

if __name__ == "__main__":
    main()
