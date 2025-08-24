# BillTracer

BillTracer is a lightweight tool for exploring how U.S. congressional bills evolve between different versions. It fetches two versions of a bill from **GovInfo** and produces a section-aware comparison in HTML with highlighted changes.

The output highlights **added**, **removed**, and **modified** text. It also tags likely **appropriations/funding**, **authority**, and **reporting** provisions so you can quickly see how funding and mandates change between drafts.

---

## Features

- Fetches bill text directly from [govinfo.gov](https://www.govinfo.gov/)
- Compares any two versions (e.g., *Introduced → Enrolled*)
- Section-aware diffing (`SEC.` sections, DIVISION/TITLE/SUBTITLE fallbacks)
- Word-level redline with `<ins>` (inserted) and `<del>` (deleted) markup
- Filters and search in the HTML viewer:
  - Filter by Added, Removed, Modified, Funding, Authority, Reporting
  - Toggle to show unchanged sections
  - Search by section ID or text content
- Top “likely funding changes” summary
- Pure Python, no external dependencies beyond `requests`

---

## Requirements

- Python 3.9 or later  
- The `requests` library  

Install dependencies:
```bash
pip install requests
