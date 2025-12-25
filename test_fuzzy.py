import asyncio
from playwright.async_api import async_playwright

APPLE_PODCASTS_URL = "https://podcasts.apple.com/il/podcast/ai-thinkers/id1848575796"

async def test_fuzzy_match():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(APPLE_PODCASTS_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, 2000)")
        await asyncio.sleep(2)
        
        title = "כשעיצוב פוגש קוד עם חן ןייצמן"
        
        result = await page.evaluate(f"""(targetTitle) => {{
            const normBasic = (s) => {{
                return s.toLowerCase()
                        .replace(/[\\s\\W_]+/g, ' ')
                        .replace(/[׳״'"]/g, '')
                        .trim();
            }};

            const target = normBasic(targetTitle);
            const targetWords = target.split(' ').filter(w => w.length > 1);
            
            const links = Array.from(document.querySelectorAll('a[href*="/podcast/"], a.link-action'));
            
            let results = [];
            
            for (const link of links) {{
                if (!link.href.includes('?i=') || !link.href.includes('apple.com')) continue;
                
                // Try to get just the title, not the full card text
                let rawText = '';
                const h3 = link.querySelector('h3');
                if (h3) {{
                    rawText = h3.innerText;
                }} else {{
                    const span = link.querySelector('span');
                    rawText = span ? span.innerText : (link.innerText || link.getAttribute('aria-label') || "");
                }}
                
                const text = normBasic(rawText);
                if (!text || text.length < 5) continue;
                
                const linkWords = text.split(' ').filter(w => w.length > 1);
                if (linkWords.length === 0) continue;

                let matchCount = 0;
                for (const tw of targetWords) {{
                    for (const lw of linkWords) {{
                        if (tw === lw || tw.includes(lw) || lw.includes(tw)) {{
                            matchCount++;
                            break;
                        }}
                    }}
                }}
                
                // Fallback: Character set overlap (Jaccard-like)
                const targetChars = new Set(target.replace(/ /g, '').split(''));
                const linkChars = new Set(text.replace(/ /g, '').split(''));
                const intersection = [...targetChars].filter(c => linkChars.has(c)).length;
                const union = new Set([...targetChars, ...linkChars]).size;
                const charScore = union > 0 ? intersection / union : 0;
                
                const wordScore = targetWords.length > 0 ? (matchCount / targetWords.length) : 0;
                const score = Math.max(wordScore, charScore * 0.9);
                
                results.push({{ href: link.href, rawText: rawText.substring(0, 60), text: text.substring(0, 60), score, wordScore, charScore }});
            }}
            
            results.sort((a, b) => b.score - a.score);
            return results.slice(0, 8);
        }}""", title)
        
        print("Target title:", title)
        print(f"Target words: {title.lower().split()}")
        print("\nTop matches:")
        for i, r in enumerate(result):
            print(f"{i+1}. Score: {r['score']:.3f} (word: {r['wordScore']:.3f}, char: {r['charScore']:.3f})")
            print(f"   Raw: {r['rawText']}")
            print(f"   Text: {r['text']}")
            print()
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_fuzzy_match())
