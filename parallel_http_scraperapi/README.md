# 99acres Scraper v3 — ScraperAPI + Parallel HTTP Scraper

## What This Is
This is the **fastest and most professional** version. It uses **no browser at all** — instead it sends direct HTTP requests and fetches multiple pages simultaneously.

Because 99acres uses Cloudflare to block plain HTTP requests (you'd get a 403 error), this script routes all traffic through **[ScraperAPI](https://scraperapi.com)** — a proxy service that uses real residential IP addresses to bypass Cloudflare automatically.

**How much faster?**
- v1 (browser): ~10 seconds per page loaded one at a time
- v3 (HTTP parallel): ~2 seconds for 5 pages loaded simultaneously

## Setup (One Time)

### Step 1: Get a free ScraperAPI key
1. Go to [scraperapi.com](https://scraperapi.com)
2. Click **Sign Up** (free — no credit card required)
3. Go to your **Dashboard** and copy your **API Key**

Free tier = **1,000 credits/month** (~100 property detail pages)

### Step 2: Set the API key

**Option A — Environment variable (recommended, set it once):**
```powershell
$env:SCRAPERAPI_KEY = "YOUR_API_KEY_HERE"
```

**Option B — Pass it every time:**
```powershell
python scraperv3.py delhi --api-key YOUR_API_KEY_HERE
```

## How to Run

```powershell
# 1. Activate the virtual environment (from the parent folder)
..\venv\Scripts\activate

# 2. Run the scraper
python scraperv3.py delhi
python scraperv3.py delhi --pages 5
python scraperv3.py mumbai --pages 3 --output mumbai.csv
python scraperv3.py pune --debug
```

## All Available Options
| Flag | Description |
|:---|:---|
| `city` | (Required) City name e.g. `delhi`, `mumbai`, `pune` |
| `--pages` | Number of search result pages (default: 1) |
| `--api-key` | ScraperAPI key. Defaults to `SCRAPERAPI_KEY` env variable |
| `--debug` | Print verbose output |
| `--output` | Custom CSV filename |

**Output file:** `99acres_<city>_v3.csv` (unless `--output` is specified)

## What It Extracts
| Column | Description |
|:---|:---|
| City | City name |
| Price | Full price from JSON-LD structured data |
| Location | Full address (structured schema.org format) |
| Size (sqft) | Floor area from structured data |
| Contact Info | Agent/builder name |
| URL | Original property listing link |

## Data Quality Summary
After scraping, the script prints a report like:
```
Data Quality Summary:
   Price:        28/30 filled (93%)
   Location:     30/30 filled (100%)
   Size (sqft):  22/30 filled (73%)
   Contact Info: 15/30 filled (50%)
```

## ScraperAPI Credit Usage
- 1 credit = 1 request
- 1 property = 1 detail page = 1 credit
- 30 properties per search page × 3 pages = ~90 credits total

## Dependencies
See `requirements.txt` in this folder.
