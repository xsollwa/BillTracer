# fetch_bills.py 
import os, re, requests

# > these are editable per bill
CONGRESS = 116
CHAMBER  = "house"
BILL_NUM = 748
VER_A    = "ih"   # Introduced
VER_B    = "enr"  # Enrolled
# 

def pkg_id(congress:int, chamber:str, num:int, ver:str) -> str:
    billtype = "hr" if chamber == "house" else "s"
    return f"BILLS-{congress}{billtype}{num}{ver}"

def fetch_pkg(congress:int, chamber:str, num:int, ver:str) -> str:
    pkg = pkg_id(congress, chamber, num, ver)
    url = f"https://www.govinfo.gov/content/pkg/{pkg}/txt/{pkg}.txt"
    print(f"Fetching {url} …")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    text = r.text.replace("\r\n","\n")
    text = re.sub(r"\u00A0"," ", text)
    if len(text.strip()) < 1000:
        raise RuntimeError(f"Got very short text for {ver} (maybe not available).")
    return text

os.makedirs("data", exist_ok=True)
v1 = fetch_pkg(CONGRESS, CHAMBER, BILL_NUM, VER_A)
v2 = fetch_pkg(CONGRESS, CHAMBER, BILL_NUM, VER_B)

open("data/bill_v1.txt","w",encoding="utf-8").write(v1)
open("data/bill_v2.txt","w",encoding="utf-8").write(v2)
print("Saved data/bill_v1.txt and data/bill_v2.txt")
