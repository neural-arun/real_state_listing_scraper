# 99acres Scraper v2 — Deep Browser Scraper

## What This Is
This is the **"Deep Scraper"** version. Instead of reading only the search result page (which gives partial data), this scraper:

1. Visits the search results page and collects the URL of every property listing
2. Opens each property's **individual detail page** in a new browser tab
3. Reads the complete property data including area, price, and contact info
4. Exports everything to a clean CSV

Because it visits the full detail page (not just the preview card), this version gets significantly better data with far fewer `N/A` fields.

## How to Run

```powershell
# 1. Activate the virtual environment (from the parent folder)
..\venv\Scripts\activate

# 2. Run the scraper (you MUST pass a city name)
python scraperv2.py delhi
python scraperv2.py delhi --pages 3
python scraperv2.py mumbai --pages 2 --output mumbai_properties.csv
python scraperv2.py pune --debug    # shows extra detail in terminal
python scraperv2.py delhi --headless  # browser runs hidden (more likely to be blocked)
```

## All Available Options
| Flag | Description |
|:---|:---|
| `city` | (Required) City name e.g. `delhi`, `mumbai`, `new-delhi` |
| `--pages` | Number of search result pages to scrape (default: 1) |
| `--debug` | Print detailed progress to terminal |
| `--headless` | Hide the browser window (WARNING: 99acres often blocks headless mode) |
| `--output` | Custom CSV output filename |

**Output file:** `99acres_<city>_v2.csv` (unless `--output` is specified)

## What It Extracts
| Column | Description |
|:---|:---|
| City | City name |
| Price | Full price from the detail page |
| Location | Full address (street + locality) |
| Size (sqft) | Built-up area / carpet area |
| Contact Info | Agent or builder name |
| URL | Link to the original property listing |

## Trade-Off
This scraper is the most accurate but the **slowest** — it loads one full webpage per property. A search page with 30 listings means ~31 total page loads.

## Dependencies
See `requirements.txt` in this folder.
