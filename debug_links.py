import asyncio
from playwright.async_api import async_playwright

APPLE_PODCASTS_URL = "https://podcasts.apple.com/il/podcast/ai-thinkers/id1848575796"

async def debug_links():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(APPLE_PODCASTS_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)
        
        # Scroll to load episodes
        await page.evaluate("window.scrollBy(0, 2000)")
        await asyncio.sleep(2)
        
        # Get all links and their text - look at the inner structure
        links_data = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a'));
            return links
                .filter(a => a.href.includes('?i=') && a.href.includes('apple.com'))
                .map(a => {
                    // Try to get the episode title specifically
                    const h3 = a.querySelector('h3');
                    const titleDiv = a.querySelector('div[role="text"]');
                    const span = a.querySelector('span');
                    
                    return {
                        href: a.href,
                        fullText: (a.innerText || '').trim().substring(0, 200),
                        h3Text: h3 ? h3.innerText.trim() : null,
                        titleDivText: titleDiv ? titleDiv.innerText.trim() : null,
                        spanText: span ? span.innerText.trim() : null,
                    };
                })
                .slice(0, 10);
        }""")
        
        print(f"Found {len(links_data)} episode links:")
        for i, l in enumerate(links_data):
            print(f"\n{i+1}. Full text (first 100): {l['fullText'][:100]}")
            print(f"   H3: {l['h3Text']}")
            print(f"   TitleDiv: {l['titleDivText']}")
            print(f"   Span: {l['spanText']}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_links())
