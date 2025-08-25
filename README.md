# BillTracer

BillTracer is a research tool for analyzing how congressional bills change as they move through the legislative process.  
It fetches two different versions of a bill from **GovInfo** and produces a side-by-side, section-aware comparison in HTML.

The viewer highlights what text was **added**, **removed**, or **modified**, and applies simple heuristics to flag provisions related to **funding**, **authority**, and **reporting**. This makes it easier to trace how appropriations or mandates evolve between drafts.

---

## Why BillTracer?

Legislation often undergoes substantial edits as it moves from introduction to enrollment. These edits may involve inserting new provisions, removing language, or modifying funding authorizations. Manually tracking those changes is tedious.  
BillTracer automates this process and produces a clean, navigable report designed for policy analysis, research, and transparency.

---

## Features

- **Automatic text retrieval**: Downloads bill text directly from [govinfo.gov](https://www.govinfo.gov/).
- **Flexible comparisons**: Works with any two versions of a bill (e.g. *Introduced → Enrolled*).
- **Section recognition**: Splits bills by `SEC.` sections when available, falling back on DIVISION/TITLE/SUBTITLE headers.
- **Redlined output**: Word-level diffs using `<ins>` for insertions and `<del>` for deletions.
- **Interactive viewer**:  
  - Filter by Added, Removed, Modified, Funding, Authority, or Reporting  
  - Search across section IDs and content  
  - Toggle unchanged sections on/off
- **Summary of funding changes**: Highlights sections most likely tied to appropriations.
- **Lightweight**: Written in Python with no dependencies other than `requests`.

---

## Requirements

- Python 3.9 or newer  
- `requests` library

Install with:

```bash
pip install requests
