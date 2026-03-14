import asyncio
import pandas as pd
from playwright.async_api import async_playwright
import re
from playwright_stealth import stealth_async

async def scrape_99acres(city="delhi", max_pages=1):
    all_properties = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        await stealth_async(page)
        
        for current_page in range(1, max_pages + 1):
            print(f"\n--- Scraping Page {current_page} ---")
            
            page_suffix = f"-page-{current_page}" if current_page > 1 else ""
            url = f"https://www.99acres.com/search/property/buy/{city}{page_suffix}?city=1&preference=S&res_com=R"
            
            try:
                print(f"Navigating to {url}")
                await page.goto(url, timeout=60000)
                
                print("Scrolling to load dynamic content...")
                for _ in range(8):
                    await page.mouse.wheel(0, 1000)
                    await asyncio.sleep(1)
                
                # Use semantic locator: finding all elements containing the currency symbol.
                # In India, real estate prices are almost always denoted with ₹
                price_elements = await page.get_by_text(re.compile(r"₹")).all()
                print(f"Found {len(price_elements)} potential properties based on price tags.")
                
                # To prevent duplicates if the symbol appears multiple times in one card,
                # we will store raw text blocks and parse them.
                extracted_data = set() 
                
                for price_el in price_elements:
                    # We walk up the DOM tree from the price tag to find a wide enough container
                    # We assume a property card is roughly a 'div' or 'section' that contains a lot of text.
                    # This XPath finds an ancestor div that has significant text content (more than just the price)
                    try:
                        # Grab the closest ancestor that looks like a major container (usually has lots of child nodes)
                        # A better semantic approach is to just get the parent that contains a link (usually the title link)
                        container = price_el.locator("xpath=ancestor::div[.//a][1]")
                        
                        if await container.count() > 0:
                            card_text = await container.first.inner_text()
                            
                            # Skip tiny containers that might just be a sub-menu
                            if len(card_text) > 50 and card_text not in extracted_data:
                                extracted_data.add(card_text)
                                
                                property_data = {
                                    "City": city.capitalize(),
                                    "Price": "N/A",
                                    "Location": "N/A",
                                    "Size (sqft)": "N/A",
                                    "Contact Info": "N/A"
                                }
                                
                                lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                                
                                # Process the text block to find our fields
                                for i, line in enumerate(lines):
                                    if '₹' in line or 'Cr' in line or 'Lac' in line:
                                        if property_data["Price"] == "N/A":
                                            property_data["Price"] = line
                                            
                                    elif 'BHK' in line or 'Apartment' in line or 'House' in line or 'Villa' in line:
                                        if property_data["Location"] == "N/A":
                                             property_data["Location"] = line
                                             
                                    elif 'sq.ft' in line.lower() or 'sqft' in line.lower() or 'sq.m' in line.lower() or 'sq.yd' in line.lower():
                                         property_data["Size (sqft)"] = line
                                    elif 'Built-up' in line or 'Carpet Area' in line:
                                        if i + 1 < len(lines):
                                            property_data["Size (sqft)"] = lines[i+1]
                                            
                                    elif 'Dealer' in line or 'Agent' in line or 'Owner' in line or 'Builder' in line:
                                        if property_data["Contact Info"] == "N/A":
                                            property_data["Contact Info"] = line
                                            
                                # Add extracted property
                                if property_data["Price"] != "N/A":
                                    all_properties.append(property_data)
                    except Exception as e:
                        print(f"Failed parsing a card: {e}")
                        pass
                
                print(f"Cleaned and found {len(extracted_data)} unique property blocks.")
                
            except Exception as e:
                print(f"Error on page {current_page}: {e}")
                
        await browser.close()
        
    return all_properties

if __name__ == "__main__":
    print("Starting Semantic 99acres Scraper...")
    scraped_data = asyncio.run(scrape_99acres(city="delhi", max_pages=3))
    print(f"\nFinal Count: Successfully extracted {len(scraped_data)} properties.")
    
    if scraped_data:
        df = pd.DataFrame(scraped_data)
        csv_filename = "99acres_delhi_results_semantic.csv"
        df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
        print(f"Data saved to {csv_filename}!")
        print("\nPreview of extracted data:")
        print(df.head(5).to_string())
    else:
        print("No data extracted. We might need a structural XPath approach.")
