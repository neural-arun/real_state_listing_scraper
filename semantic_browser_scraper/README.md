# 99acres Scraper v1 — Semantic Browser Scraper

## What This Is
This scraper uses a real **Chromium browser** (powered by Playwright) to open 99acres, scroll the page like a human, and extract property listings using **semantic text detection**.

Instead of looking for specific HTML class names (which 99acres randomizes daily to block scrapers), this script searches the **visible text on screen** for the `₹` symbol and "BHK" keywords and extracts the surrounding text block for each card.

## How to Run

```powershell
# 1. Activate the virtual environment (from the parent folder)
..\venv\Scripts\activate

# 2. Run the scraper
python scraper.py
```

**Output file:** `99acres_delhi_results_semantic.csv`

To change the city or number of pages, open `scraper.py` and edit the last few lines:
```python
scraped_data = asyncio.run(scrape_99acres(city="mumbai", max_pages=5))
```

## What It Extracts
| Column | Description |
|:---|:---|
| City | City name (e.g., Delhi) |
| Price | Listing price (e.g., ₹2.5 Cr) |
| Location | Property title / area name |
| Size (sqft) | Area if listed on the card |
| Contact Info | Agent/builder name if visible |

## Limitations
- Some fields show `N/A` because 99acres hides them behind a "View Contact" click
- Requires a visible browser window (can be seen on screen while running)
- Can be slowed down by CAPTCHA challenges on heavy usage

## Dependencies
See `requirements.txt` in this folder.
