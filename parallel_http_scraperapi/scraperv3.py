"""
scraperv3.py — 99acres Parallel HTTP Scraper with ScraperAPI Support
=====================================================================
STRATEGY:
  Uses direct async HTTP requests (no browser!) for maximum speed.
  Routes all traffic through ScraperAPI's residential proxies to bypass
  Cloudflare's bot detection that blocks direct requests.

HOW SCRAPERAPI WORKS:
  Instead of sending requests directly to 99acres (which gets a 403),
  we send our request to ScraperAPI's endpoint like this:
    https://api.scraperapi.com/?api_key=YOUR_KEY&url=https://www.99acres.com/...
  ScraperAPI handles the IP rotation, CAPTCHA solving, and Cloudflare bypass
  on their end, and returns the clean HTML to us.

WHY THIS IS FASTER THAN scraper.py:
  - No browser launch (saves 5-10 seconds per run)
  - No scrolling or waiting for JavaScript
  - 5 pages fetched simultaneously through parallel async calls
  - Still extracts clean JSON-LD structured data, no messy HTML class parsing

USAGE:
  # Set your API key first (one-time setup):
  python scraperv3.py delhi --pages 3 --api-key YOUR_SCRAPERAPI_KEY

  # Or set the environment variable so you don't type it every time:
  $env:SCRAPERAPI_KEY = "YOUR_KEY"
  python scraperv3.py delhi --pages 3

  # Get a free API key (1000 free credits/month) at:
  # https://scraperapi.com → Sign Up → Dashboard → API Key

PRICING GUIDE (as of 2024):
  Free tier:  1,000 requests/month  → ~100 properties (good for testing)
  Hobby:      $49/month → 250,000 requests
  Startup:    $149/month → 1,000,000 requests
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pandas as pd
from bs4 import BeautifulSoup


# ──────────────────────────────────────────────────────────────────────────────
# ScraperAPI Configuration
# ──────────────────────────────────────────────────────────────────────────────
SCRAPERAPI_BASE = "https://api.scraperapi.com/"

def build_scraperapi_url(target_url: str, api_key: str, render_js: bool = False) -> str:
    """
    Wraps any URL through ScraperAPI's proxy endpoint.
    
    render_js=False: Faster — just returns the raw HTML (enough for JSON-LD extraction)
    render_js=True:  Slower — renders JavaScript too (use only if JSON-LD is missing)
    """
    params = {
        "api_key": api_key,
        "url": target_url,
        "country_code": "in",  # Use Indian IPs to avoid geo-blocking
    }
    if render_js:
        params["render"] = "true"
    return SCRAPERAPI_BASE + "?" + urlencode(params)


# ──────────────────────────────────────────────────────────────────────────────
# Standard (non-ScraperAPI) headers — used only if no API key is provided
# ──────────────────────────────────────────────────────────────────────────────
DIRECT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

CONCURRENCY = 5   # Max simultaneous property page requests


# ──────────────────────────────────────────────────────────────────────────────
# URL & Name helpers
# ──────────────────────────────────────────────────────────────────────────────
def normalize_city(city: str) -> str:
    slug = re.sub(r"[\s_]+", "-", city.strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return re.sub(r"-{2,}", "-", slug).strip("-")


def build_search_url(city_slug: str, page_number: int) -> str:
    suffix = f"-page-{page_number}" if page_number > 1 else ""
    return f"https://www.99acres.com/property-in-{city_slug}-ffid{suffix}"


def city_display_name(city_slug: str) -> str:
    return city_slug.replace("-", " ").title()


# ──────────────────────────────────────────────────────────────────────────────
# JSON-LD Parsing — extracts structured data from SEO script tags
# ──────────────────────────────────────────────────────────────────────────────
def extract_json_ld_blocks(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, dict):
                blocks.append(data)
            elif isinstance(data, list):
                blocks.extend(b for b in data if isinstance(b, dict))
        except (json.JSONDecodeError, TypeError):
            pass
    return blocks


def extract_listing_urls(blocks: list[dict]) -> list[tuple[str, str]]:
    """Extract (name, url) pairs from the ItemList JSON-LD block."""
    results = []
    for block in blocks:
        if block.get("@type") != "ItemList":
            continue
        for item in block.get("itemListElement", []):
            url = item.get("url", "").strip()
            name = item.get("name", "").strip()
            if url:
                results.append((name, url))
    return results


def parse_property_detail(html: str, city_name: str, fallback_name: str, url: str) -> dict | None:
    """
    Parse a property's individual detail page to extract all data fields.
    Uses JSON-LD first (fast + clean), then falls back to text scanning.
    """
    blocks = extract_json_ld_blocks(html)

    price = "N/A"
    location = fallback_name or "N/A"
    size = "N/A"
    contact = "N/A"

    # ── Priority 1: Clean JSON-LD data ──
    for block in blocks:
        btype = block.get("@type", "")
        if btype in ("Apartment", "House", "SingleFamilyResidence", "LandParcel", "Accommodation"):

            # Price — comes in as 'offers' object
            offers = block.get("offers") or {}
            if isinstance(offers, dict):
                price_val = offers.get("price") or offers.get("priceSpecification")
                if price_val and str(price_val).strip() not in ("0", "", "None"):
                    price = f"₹{price_val}" if "₹" not in str(price_val) else str(price_val)

            # Location — from address block
            addr = block.get("address") or {}
            if isinstance(addr, dict):
                parts = [addr.get("streetAddress", ""), addr.get("addressLocality", "")]
                joined = ", ".join(p for p in parts if p)
                if joined:
                    location = joined

            # Size — from floorSize or description
            floor_sz = block.get("floorSize") or {}
            if isinstance(floor_sz, dict) and floor_sz.get("value"):
                size = f"{floor_sz['value']} {floor_sz.get('unitCode', 'sqft')}"

            desc = block.get("description", "")
            if size == "N/A" and desc:
                m = re.search(r"(\d[\d,]*)\s*(sq\.?\s*ft|sqft|sq\s*yards?)", desc, re.IGNORECASE)
                if m:
                    size = f"{m.group(1)} {m.group(2)}"

    # ── Priority 2: Text scan for any remaining N/A fields ──
    if price == "N/A" or contact == "N/A" or size == "N/A":
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        for i, line in enumerate(lines):
            if price == "N/A" and "₹" in line:
                price = line
            if size == "N/A" and re.search(r"sq\.?\s*ft|sqft|sq\s*yards?", line, re.IGNORECASE):
                size = line
            if contact == "N/A":
                role_words = ("Owner", "Dealer", "Agent", "Builder", "Promoter")
                if any(w.lower() in line.lower() for w in role_words):
                    prev = lines[i - 1] if i > 0 else ""
                    if prev and len(prev) > 2 and prev not in ("Overview", "Details", "Articles"):
                        contact = f"{prev} ({line})"
                    else:
                        contact = line

    return {
        "City": city_name,
        "Price": price,
        "Location": location,
        "Size (sqft)": size,
        "Contact Info": contact,
        "URL": url,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Async HTTP Fetching
# ──────────────────────────────────────────────────────────────────────────────
async def fetch_html(
    client: httpx.AsyncClient,
    target_url: str,
    api_key: str | None,
    debug: bool,
) -> str | None:
    """
    Fetch HTML from a URL.
    
    - If api_key is provided: Route through ScraperAPI (bypasses Cloudflare)
    - If no api_key: Send direct request (will get 403 from 99acres)
    """
    if api_key:
        request_url = build_scraperapi_url(target_url, api_key)
    else:
        request_url = target_url

    try:
        resp = await client.get(request_url, timeout=30, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        if debug:
            print(f"  [WARN] HTTP {resp.status_code} for {target_url[:70]}")
        return None
    except Exception as e:
        if debug:
            print(f"  [WARN] Request failed: {target_url[:70]} — {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Main Scraper
# ──────────────────────────────────────────────────────────────────────────────
async def scrape_99acres(
    city: str,
    max_pages: int = 1,
    api_key: str | None = None,
    debug: bool = False,
) -> list[dict]:
    city_slug = normalize_city(city)
    city_name = city_display_name(city_slug)
    all_records: list[dict] = []
    seen_urls: set[str] = set()

    # Warn the user if no API key — the direct requests will be 403'd
    if not api_key:
        print("\n  ⚠️  WARNING: No ScraperAPI key provided.")
        print("  99acres will return 403 Forbidden for direct HTTP requests.")
        print("  Get a free key at: https://scraperapi.com  (1000 free credits/month)")
        print("  Then run: python scraperv3.py delhi --api-key YOUR_KEY\n")

    async with httpx.AsyncClient(headers=DIRECT_HEADERS, http2=True) as client:

        # ── Step 1: Fetch all search result pages in PARALLEL ──
        search_urls = [build_search_url(city_slug, n) for n in range(1, max_pages + 1)]
        print(f"Step 1: Fetching {len(search_urls)} search page(s) simultaneously...")
        
        search_htmls = await asyncio.gather(
            *[fetch_html(client, u, api_key, debug) for u in search_urls]
        )

        all_listing_tuples: list[tuple[str, str]] = []
        for html in search_htmls:
            if html:
                blocks = extract_json_ld_blocks(html)
                tuples = extract_listing_urls(blocks)
                all_listing_tuples.extend(tuples)

        # Deduplicate by URL
        unique_listings = []
        for name, url in all_listing_tuples:
            if url not in seen_urls:
                seen_urls.add(url)
                unique_listings.append((name, url))

        print(f"  Found {len(unique_listings)} unique property URLs.\n")

        if not unique_listings:
            return []

        # ── Step 2: Fetch each property detail page in concurrent batches ──
        print(f"Step 2: Fetching {len(unique_listings)} property detail pages (max {CONCURRENCY} at once)...")
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def fetch_and_parse(name: str, url: str) -> dict | None:
            async with semaphore:
                html = await fetch_html(client, url, api_key, debug)
                if html:
                    return parse_property_detail(html, city_name, name, url)
                return None

        tasks = [fetch_and_parse(name, url) for name, url in unique_listings]
        results = await asyncio.gather(*tasks)

        for record in results:
            if record:
                all_records.append(record)

        print(f"  Parsed {len(all_records)} properties successfully.")

    return all_records


# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────
def save_to_csv(data: list[dict], path: Path) -> None:
    df = pd.DataFrame(data)
    print("\nData Quality Summary:")
    for col in ["Price", "Location", "Size (sqft)", "Contact Info"]:
        if col in df.columns:
            na_count = (df[col] == "N/A").sum()
            pct = (1 - na_count / len(df)) * 100
            print(f"   {col}: {len(df) - na_count}/{len(df)} filled ({pct:.0f}%)")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\nSaved → {path}")
    print("\nPreview:")
    print(df.head(5).to_string())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="99acres Parallel HTTP Scraper v3 (ScraperAPI powered)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scraperv3.py delhi --pages 3 --api-key YOUR_KEY\n"
            "  python scraperv3.py mumbai --pages 5 --output mumbai.csv\n\n"
            "  Get a free ScraperAPI key (1000 credits/month):\n"
            "  https://scraperapi.com\n"
        ),
    )
    parser.add_argument("city", help="City name or slug, e.g. delhi, mumbai, new-delhi")
    parser.add_argument("--pages", type=int, default=1, help="Number of search pages to scrape")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("SCRAPERAPI_KEY"),
        help="ScraperAPI key. Defaults to SCRAPERAPI_KEY environment variable.",
    )
    parser.add_argument("--debug", action="store_true", help="Print verbose debug output")
    parser.add_argument("--output", help="Output CSV filename")
    args = parser.parse_args()
    if args.pages < 1:
        parser.error("--pages must be >= 1")
    return args


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    city_slug = normalize_city(args.city)
    output = Path(args.output) if args.output else Path(f"99acres_{city_slug}_v3.csv")

    print("=" * 60)
    print("  99acres Scraper v3  —  ScraperAPI + Parallel HTTP")
    print("=" * 60)
    print(f"  City    : {args.city}")
    print(f"  Pages   : {args.pages}")
    print(f"  API Key : {'✅ Provided' if args.api_key else '❌ Missing — requests will be blocked'}")
    print(f"  Output  : {output}")

    data = asyncio.run(scrape_99acres(
        city=args.city,
        max_pages=args.pages,
        api_key=args.api_key,
        debug=args.debug,
    ))

    print(f"\nTotal properties scraped: {len(data)}")
    if data:
        save_to_csv(data, output)
    else:
        print("\nNo data extracted.")
        if not args.api_key:
            print("→ Add --api-key YOUR_SCRAPERAPI_KEY to bypass Cloudflare.")
            print("→ Free key at: https://scraperapi.com")
