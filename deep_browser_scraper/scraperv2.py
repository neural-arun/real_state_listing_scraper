import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin


RESULTS_URL_TEMPLATES = (
    "https://www.99acres.com/property-in-{city}-ffid{page_suffix}",
    "https://www.99acres.com/property-for-sale-in-{city}-ffid{page_suffix}",
)
JSON_LD_SELECTOR = 'script[type="application/ld+json"]'
FALLBACK_LINK_SELECTOR = "a[href*='-spid-'], a[href*='-npxid-']"
PRICE_LINE_PATTERN = re.compile(r"\u20b9\s*[^\n]+")
SIZE_INLINE_PATTERN = re.compile(
    r"(Plot area|Super Built-up Area|Built-up Area|Carpet Area|Area)\s+([^\n]+)",
    re.IGNORECASE,
)
SIZE_VALUE_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(sq\.?\s*(?:ft|yards?|m)|sqft)", re.IGNORECASE)
ROLE_PATTERN = re.compile(r"Owner|Dealer|Agent|Builder|Promoter", re.IGNORECASE)


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def normalize_city_slug(city: str) -> str:
    slug = re.sub(r"[\s_]+", "-", city.strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        raise ValueError("City cannot be empty.")
    return slug


def format_city_name(city: str) -> str:
    return normalize_city_slug(city).replace("-", " ").title()


def build_search_urls(city_slug: str, page_number: int) -> list[str]:
    page_suffix = f"-page-{page_number}" if page_number > 1 else ""
    return [
        template.format(city=city_slug, page_suffix=page_suffix)
        for template in RESULTS_URL_TEMPLATES
    ]


def build_output_path(city_slug: str, output: str | None) -> Path:
    if output:
        return Path(output)
    return Path(f"99acres_{city_slug}_v2.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape sale listings from 99acres.")
    parser.add_argument(
        "city",
        help="City name or slug, for example: azamgarh, delhi, new-delhi",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of search result pages to scrape.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print verbose progress and parser warnings.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium without opening the browser window. 99acres may block headless mode.",
    )
    parser.add_argument(
        "--output",
        help="Optional output CSV path. Defaults to 99acres_<city>_v2.csv.",
    )
    args = parser.parse_args()

    if args.pages < 1:
        parser.error("--pages must be at least 1.")

    return args


def clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_json_ld_objects(script_texts: list[str]) -> list[dict]:
    objects: list[dict] = []
    for script_text in script_texts:
        try:
            payload = json.loads(script_text)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, list):
            objects.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            objects.append(payload)
    return objects


def flatten_item_list(entries) -> list[dict]:
    flattened: list[dict] = []

    if isinstance(entries, list):
        for entry in entries:
            flattened.extend(flatten_item_list(entry))
        return flattened

    if isinstance(entries, dict) and entries.get("@type") == "ListItem":
        flattened.append(entries)

    return flattened


def dedupe_listings(listings: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    deduped: list[dict] = []

    for listing in listings:
        url = listing.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(listing)

    return deduped


def extract_price(lines: list[str], body: str) -> str:
    for line in lines:
        if "\u20b9" in line:
            return line

    match = PRICE_LINE_PATTERN.search(body)
    if match:
        return match.group(0).strip()

    return "N/A"


def extract_size(lines: list[str], body: str) -> str:
    size_labels = {
        "Plot area",
        "Super Built-up Area",
        "Built-up Area",
        "Carpet Area",
        "Area",
    }
    specific_size_labels = {
        "Plot area",
        "Super Built-up Area",
        "Built-up Area",
        "Carpet Area",
    }

    for index, line in enumerate(lines):
        inline_match = SIZE_INLINE_PATTERN.search(line)
        if inline_match:
            label = inline_match.group(1)
            value = inline_match.group(2).strip()
            if label == "Area" and any(value.startswith(prefix) for prefix in specific_size_labels):
                return value
            return f"{label} {value}"

        if line in size_labels and index + 1 < len(lines):
            next_line = lines[index + 1]
            if line == "Area" and any(next_line.startswith(prefix) for prefix in specific_size_labels):
                return next_line
            return f"{line} {next_line}"

    match = SIZE_VALUE_PATTERN.search(body)
    if match:
        return match.group(0).strip()

    return "N/A"


def extract_contact_info(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line == "Owner Details":
            name = lines[index + 1] if index + 1 < len(lines) else ""
            role = lines[index + 2] if index + 2 < len(lines) else ""
            if name and role and ROLE_PATTERN.fullmatch(role):
                return f"{name} ({role})"
            if name:
                return name

    for index, line in enumerate(lines):
        if ROLE_PATTERN.fullmatch(line):
            previous_line = lines[index - 1] if index > 0 else ""
            if previous_line and previous_line not in {"Owner Details", "Overview", "Articles"}:
                return f"{previous_line} ({line})"
            return line

    return "N/A"


def parse_detail_page(body: str, city_name: str, fallback_location: str, url: str) -> dict[str, str]:
    lines = clean_lines(body)

    return {
        "City": city_name,
        "Price": extract_price(lines, body),
        "Location": fallback_location or "N/A",
        "Size (sqft)": extract_size(lines, body),
        "Contact Info": extract_contact_info(lines),
        "URL": url,
    }


async def load_results_page(page, city_slug: str, page_number: int, headless: bool) -> str:
    last_error: Exception | None = None

    for url in build_search_urls(city_slug, page_number):
        await page.goto(url, timeout=60000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        title = await page.title()
        body = await page.locator("body").inner_text()
        body_lower = body.lower()

        if "access denied" in title.lower() or "access denied" in body_lower:
            if headless:
                raise RuntimeError(
                    "99acres blocked headless mode. Run the scraper without --headless."
                )
            raise RuntimeError(
                "99acres returned Access Denied. Wait a bit and try again in headed mode."
            )

        if "400 error" in title.lower() or "404 not found" in title.lower():
            last_error = RuntimeError(f"99acres rejected URL: {url}")
            continue

        if "this page does not exists" in body_lower:
            last_error = RuntimeError(f"99acres does not have a results page for {url}")
            continue

        return url

    if last_error:
        raise last_error

    raise RuntimeError(f"Unable to load a valid 99acres results page for city: {city_slug}")


async def extract_result_links(page, debug: bool = False) -> list[dict]:
    script_texts = await page.locator(JSON_LD_SELECTOR).all_text_contents()
    json_ld_objects = parse_json_ld_objects(script_texts)

    for obj in json_ld_objects:
        if obj.get("@type") != "ItemList":
            continue

        entries = flatten_item_list(obj.get("itemListElement", []))
        listings = [
            {
                "name": entry.get("name", "").strip(),
                "url": entry.get("url", "").strip(),
            }
            for entry in entries
            if entry.get("url")
        ]
        listings = dedupe_listings(listings)
        if listings:
            return listings

    if debug:
        print("[DEBUG] ItemList JSON-LD missing, falling back to anchor extraction.")

    links = page.locator(FALLBACK_LINK_SELECTOR)
    listings: list[dict] = []
    for index in range(await links.count()):
        link = links.nth(index)
        href = await link.get_attribute("href")
        text = (await link.inner_text()).strip()
        if not href:
            continue
        listings.append(
            {
                "name": text,
                "url": urljoin(page.url, href),
            }
        )

    return dedupe_listings(listings)


async def scrape_listing(context, listing: dict, city_name: str, debug: bool) -> dict[str, str] | None:
    from playwright_stealth import stealth_async

    url = listing["url"]
    location = listing.get("name", "").strip() or "N/A"
    detail_page = await context.new_page()
    await stealth_async(detail_page)

    try:
        await detail_page.goto(url, timeout=60000)
        await detail_page.wait_for_load_state("domcontentloaded")
        await detail_page.wait_for_timeout(1500)

        title = await detail_page.title()
        body = await detail_page.locator("body").inner_text()
        body_lower = body.lower()

        if "access denied" in title.lower() or "access denied" in body_lower:
            raise RuntimeError("99acres blocked the detail page request.")

        if "404 not found" in title.lower() or "this page does not exists" in body_lower:
            raise RuntimeError("99acres returned a missing listing page.")

        return parse_detail_page(body, city_name, location, url)

    except Exception as exc:
        if debug:
            print(f"[WARN] Failed listing: {url}")
            print(f"[WARN] Reason: {exc}")
        return None
    finally:
        await detail_page.close()


async def scrape_99acres(
    city: str,
    max_pages: int = 1,
    debug: bool = False,
    headless: bool = False,
) -> list[dict[str, str]]:
    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async

    city_slug = normalize_city_slug(city)
    city_name = format_city_name(city)
    all_properties: list[dict[str, str]] = []
    seen_listing_urls: set[str] = set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1600, "height": 900},
        )
        results_page = await context.new_page()
        await stealth_async(results_page)

        for current_page in range(1, max_pages + 1):
            print(f"\n{'=' * 40}")
            print(f" Scraping {city_name} - Page {current_page}")
            print(f"{'=' * 40}")

            try:
                current_url = await load_results_page(
                    results_page,
                    city_slug=city_slug,
                    page_number=current_page,
                    headless=headless,
                )
                print(f"URL: {current_url}")

                listings = await extract_result_links(results_page, debug=debug)
                print(f"Found {len(listings)} listing links.")

                for listing in listings:
                    if listing["url"] in seen_listing_urls:
                        continue

                    record = await scrape_listing(context, listing, city_name, debug)
                    seen_listing_urls.add(listing["url"])

                    if record:
                        all_properties.append(record)

                print(f"Extracted {len(all_properties)} properties so far.")

            except Exception as exc:
                print(f"[ERROR] Page {current_page}: {exc}")

        await browser.close()

    return all_properties


def save_results(data: list[dict[str, str]], output_path: Path) -> None:
    import pandas as pd

    df = pd.DataFrame(data)

    for column in ["Price", "Location", "Size (sqft)", "Contact Info"]:
        na_count = (df[column] == "N/A").sum()
        print(f"  {column}: {na_count} N/A out of {len(df)}")

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved to {output_path}")
    print(df.head(5).to_string())


if __name__ == "__main__":
    configure_stdout()
    args = parse_args()
    city_slug = normalize_city_slug(args.city)
    city_name = format_city_name(args.city)
    output_path = build_output_path(city_slug, args.output)

    print(f"Starting 99acres Scraper v2 for {city_name}...")
    scraped_data = asyncio.run(
        scrape_99acres(
            city=args.city,
            max_pages=args.pages,
            debug=args.debug,
            headless=args.headless,
        )
    )

    print(f"\nTotal properties extracted: {len(scraped_data)}")

    if scraped_data:
        save_results(scraped_data, output_path)
    else:
        print("No data extracted. Try again without --headless, or use --debug for more logs.")
