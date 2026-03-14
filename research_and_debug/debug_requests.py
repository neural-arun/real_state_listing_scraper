import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

requests_log = []

def on_request(req):
    if req.resource_type in ("xhr", "fetch"):
        requests_log.append({
            "url": req.url,
            "type": req.resource_type,
            "method": req.method,
        })

async def run():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()
        await stealth_async(page)
        page.on("request", on_request)

        await page.goto("https://www.99acres.com/property-in-delhi-ffid", timeout=60000)
        await page.wait_for_load_state("networkidle", timeout=25000)
        for _ in range(5):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(1.5)

        print(f"\nTotal XHR/Fetch requests: {len(requests_log)}")
        for r in requests_log[:30]:
            method = r["method"]
            url = r["url"][:100]
            print(f"  [{method}] {url}")

        await browser.close()

asyncio.run(run())
