import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

all_json = []

async def on_response(resp):
    ct = resp.headers.get("content-type", "")
    if "json" in ct:
        try:
            # We must read body HERE inside the callback before it is freed
            text = await resp.text()
            if len(text) > 200:
                all_json.append({
                    "url": resp.url,
                    "length": len(text),
                    "sample": text[:120],
                    "body": text
                })
        except Exception as e:
            pass  # Response body already freed, skip it

async def run():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        )
        page = await context.new_page()
        await stealth_async(page)
        page.on("response", on_response)

        await page.goto("https://www.99acres.com/property-in-delhi-ffid", timeout=60000)
        await page.wait_for_load_state("networkidle", timeout=30000)
        for _ in range(5):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(1.5)

        print(f"\nTotal JSON responses captured: {len(all_json)}")
        for r in all_json[:25]:
            length = r["length"]
            url = r["url"][:90]
            print(f"  [{length:6} bytes]  {url}")

        await browser.close()

asyncio.run(run())
