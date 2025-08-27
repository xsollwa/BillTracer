# BillTracer

BillTracer is a tool I built for the **Congressional Hackathon** to make it easier to analyze how congressional bills change as they move through the legislative process.  

It fetches two different versions of a bill from **GovInfo** and produces a side-by-side, section-aware comparison in HTML. The viewer highlights what text was **added**, **removed** or **modified** and applies simple heuristics to flag provisions related to **funding**.

Youtube Prototype Demo: https://youtu.be/PBa_G2kVW18?si=rLCRcPSMGERZGYrd

-

## Why I Made BillTracer

Legislation often undergoes major edits as it moves from introduction to enrollment. Tracking those changes by hand is tedious and confusing, especially for congressional staff, students, advocates or anyone who isn’t a legal expert.  

I made BillTracer because I wanted a **clearer way to see how bills evolve**. My goal was to build something that encourages civic engagement, makes government processes less intimidating, and supports transparency.

## How I Made It

1. **APIs and data** - I used GovInfo’s API to pull down different versions of a bill.  
2. **Parsing** - I wrote a Python parser to split bills into sections (`SEC.`, DIVISION, TITLE, SUBTITLE, etc.).  
3. **Diffing engine** - I built logic to compare the two versions at the word level, marking insertions and deletions.  
4. **Heuristics** - I added keyword checks to flag funding, authority, and reporting language.  
5. **HTML viewer** - Finally, I created a HTML that makes the changes searchable, filterable and easier to read.

## What I Struggled With

- Congressional bills are not standardized. Some had clean section headers, others didn’t, which made parsing hard.  
- Highlighting every change at once looked really challenging, so I worked on sectioning and filters to make the output readable.  

## What I Learned

- **Government data is messy**: APIs and documents don’t always follow a neat structure, but careful parsing can still make them usable.  
- Tech + civics go hand in hand because even small projects can make the legislative process more transparent and accessible for everyone.  

-

## Features

- **Text retrieval** from [govinfo.gov](https://www.govinfo.gov/)  
- **Comparisons** between any two versions of a bill (e.g., Introduced -> Enrolled)  
- **Section recognition** with fallbacks for headers  
- **Interactive report** with filters, search, and toggle for unchanged sections  
- **Funding summary** that highlights appropriation-related changes  
- **Lightweight**: only requires Python and `requests`

-
## To View to Bill of Your Choice 

- Edit the bill information on the fetch script and add your bill information.
  
CONGRESS = 116

CHAMBER  = "house"   # "house" or "senate"

BILL_NUM = 748

VER_A    = "ih"      # ih, rh, eh, enr.

VER_B    = "enr"
 

## Requirements

- Python 3.9 or newer  
- `requests` library  

Install with:

```bash
pip install requests

