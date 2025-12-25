import asyncio
import feedparser
import re
import logging
import json
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Browser, Playwright, Route

import config
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PodcastScraper:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(config.CONCURRENCY_LIMIT)
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        if config.MANIFEST_PATH.exists():
            try:
                return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Failed to load manifest: {e}")
        return {"episodes": {}}

    def _save_manifest(self):
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        config.MANIFEST_PATH.write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    def _clean_filename(self, title: str) -> str:
        return re.sub(r'[\\/*?:\"<>|]', "", title)

    def _clean_transcript(self, raw_text: str) -> str:
        pattern = rf"{re.escape(config.TRANSCRIPT_START_MARKER)}(.*?){re.escape(config.TRANSCRIPT_END_MARKER)}"
        match = re.search(pattern, raw_text, re.DOTALL)
        if not match:
            return ""

        content = match.group(1).strip()
        lines = [
            line.strip()
            for line in content.split('\n')
            if line.strip() and not any(avoid in line for avoid in config.AVOID_PHRASES)
        ]
        return "\n".join(lines)

    async def _block_resources(self, route: Route):
        if route.request.resource_type in config.BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()



    async def process_episode(self, entry: dict, browser: Browser):
        async with self.semaphore:
            title = entry.title
            clean_title = self._clean_filename(title)
            file_path = config.OUTPUT_DIR / f"{clean_title}.md"
            
            # Check manifest for status
            entry_id = entry.get('id', title)
            status = self.manifest["episodes"].get(entry_id, {})
            
            fetch_desc = not status.get("has_description", False)
            fetch_trans = not status.get("has_transcript", False)

            # Re-check if manual file exists and check if Links: are missing
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                if "## Links" not in content:
                    fetch_desc = True
            else:
                fetch_desc = True
                fetch_trans = True

            if not fetch_desc and not fetch_trans:
                logger.info(f"Skipping '{title}', already up to date.")
                return

            logger.info(f"Processing '{title}' (Desc: {fetch_desc}, Trans: {fetch_trans})")
            
            # Use a realistic User Agent and Viewport to avoid bot detection and ensure correct rendering
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            await page.route("**/*", self._block_resources)

            try:
                description_text = ""
                links_text = ""
                transcript_text = ""
                spotify_link = None

                # 1. Fetch from Substack
                await page.goto(entry.link, wait_until="domcontentloaded")
                
                # Human-like scrolling to trigger lazy loading
                for _ in range(5):
                    await page.mouse.wheel(0, 500)
                    await page.wait_for_timeout(500)
                
                # Final scroll to bottom just in case
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000) # Wait for content to settle
                
                await page.wait_for_selector(config.SUBSTACK_DESC_SELECTOR)
                desc_element = page.locator(config.SUBSTACK_DESC_SELECTOR).first
                
                # Extract Links with Context
                links = desc_element.locator("a")
                link_count = await links.count()
                for i in range(link_count):
                    link = links.nth(i)
                    l_href = await link.get_attribute('href')
                    
                    if l_href:
                        # Try to get the full line context (parent paragraph or list item)
                        l_text = await link.evaluate("el => el.parentElement.innerText")
                        # Clean up newlines and extra spaces
                        l_text = " ".join(l_text.split())
                        
                        if not l_text: # Fallback if parent is empty
                            l_text = await link.inner_text()

                        links_text += f"- [{l_text}]({l_href})\n"
                        
                        if l_href.startswith("https://open.spotify.com/episode/"):
                            spotify_link = l_href

                if fetch_desc:
                    description_text = await desc_element.inner_text()

                # 2. Fetch Transcript
                # Priority A: Try Substack (Current Page)
                if fetch_trans:
                    try:
                        # Look for the Transcript button on Substack
                        transcript_btn = page.get_by_role("button", name=config.SUBSTACK_TRANSCRIPT_BTN_TEXT)
                        if await transcript_btn.is_visible():
                            logger.info(f"Attempting Substack transcript for '{title}'")
                            await transcript_btn.click()
                            
                            # Wait for content to load
                            await page.wait_for_selector(config.SUBSTACK_TRANSCRIPT_SELECTOR, timeout=5000)
                            trans_element = page.locator(config.SUBSTACK_TRANSCRIPT_SELECTOR).first
                            
                            raw_substack_text = await trans_element.inner_text()
                            if raw_substack_text and len(raw_substack_text) > 100:
                                transcript_text = raw_substack_text.strip()
                                logger.info(f"Found transcript on Substack for '{title}' (Length: {len(transcript_text)})")
                            else:
                                logger.warning(f"Substack transcript found but empty or too short for '{title}'")

                    except Exception as e:
                        logger.debug(f"Substack transcript fetch failed for '{title}': {e}")

                # Priority B: Fallback to YouTube
                if fetch_trans and not transcript_text:
                    youtube_url = None
                    video_id = None
                    try:
                        # Strategy 1: Substack Custom Component (Data Attrs)
                        # Check for div with data-component-name="Youtube2ToDOM" and extract videoId from data-attrs
                        yt_component = page.locator('div[data-component-name="Youtube2ToDOM"]').first
                        if await yt_component.count() > 0:
                             data_attrs = await yt_component.get_attribute("data-attrs")
                             if data_attrs:
                                 try:
                                     attrs = json.loads(data_attrs)
                                     video_id = attrs.get("videoId")
                                     if video_id:
                                         logger.info(f"Found YouTube ID {video_id} in Substack component")
                                 except Exception as json_err:
                                     logger.warning(f"Failed to parse Youtube2ToDOM attrs: {json_err}")

                        # Strategy 2: Iframe (Classic & Nocookie)
                        if not video_id:
                            iframe = page.locator('iframe[src*="youtube"]').first
                            if await iframe.count() > 0:
                                src = await iframe.get_attribute("src")
                                youtube_url = src
                            
                        # Strategy 3: Direct Links
                        if not video_id and not youtube_url:
                            yt_link = page.locator('a[href*="youtube.com/watch"], a[href*="youtu.be"]').first
                            if await yt_link.count() > 0:
                                youtube_url = await yt_link.get_attribute("href")

                        # Extract ID from URL if we found a URL but no ID yet
                        if not video_id and youtube_url:
                            if "embed/" in youtube_url:
                                video_id = youtube_url.split("embed/")[-1].split("?")[0]
                            elif "v=" in youtube_url:
                                video_id = youtube_url.split("v=")[-1].split("&")[0]
                            elif "youtu.be/" in youtube_url:
                                video_id = youtube_url.split("youtu.be/")[-1].split("?")[0]

                        # Strategy 4: window._preloads JSON (Robust Fallback)
                        if not video_id:
                            try:
                                preloads = await page.evaluate("() => window._preloads")
                                if preloads:
                                    post = preloads.get('post', {})
                                    # Check cover_image for YouTube ID
                                    cover_image = post.get('cover_image', '') or ''
                                    if 'youtube' in cover_image:
                                         # URL typically like: .../youtube/w_728,c_limit/VIDEO_ID
                                         parts = cover_image.split('/')
                                         if parts:
                                             candidate = parts[-1]
                                             if len(candidate) == 11:
                                                 video_id = candidate
                                                 logger.info(f"Found YouTube ID {video_id} in _preloads cover_image")
                                    
                                    # Check body_html for iframes
                                    if not video_id:
                                        body_html = post.get('body_html', '')
                                        if body_html:
                                            match = re.search(r'embed/([a-zA-Z0-9_-]{11})', body_html)
                                            if match:
                                                video_id = match.group(1)
                                                logger.info(f"Found YouTube ID {video_id} in _preloads body_html")

                            except Exception as e:
                                logger.debug(f"JSON extraction failed: {e}")

                        # Fetch Transcript if we have an ID
                        if video_id:
                            logger.info(f"Fetching YouTube transcript for video {video_id} ('{title}')")
                            try:
                                # Fix: Instantiate API and use fetch() for this specific version/env
                                api = YouTubeTranscriptApi()
                                transcript_list = api.fetch(video_id, languages=['he', 'en', 'iw'])
                                formatter = TextFormatter()
                                transcript_text = formatter.format_transcript(transcript_list)
                                logger.info(f"Successfully fetched YouTube transcript for '{title}'")
                            except Exception as yt_err:
                                logger.warning(f"YouTube transcript fetch failed for {video_id}: {yt_err}")
                        else:
                            logger.info(f"No YouTube link/ID found for '{title}'")
                            # DEBUG: Save HTML to inspect why we missed it
                            try:
                                debug_html = await page.content()
                                debug_path = config.OUTPUT_DIR / f"debug_{entry_id[:10]}.html"
                                debug_path.write_text(debug_html, encoding="utf-8")
                                logger.info(f"Saved debug HTML to {debug_path}")
                            except Exception as e:
                                logger.warning(f"Failed to save debug HTML: {e}")

                    except Exception as e:
                        logger.warning(f"Error during YouTube fallback for '{title}': {e}")

                # 3. Assemble Markdown
                md_content = f"# {title}\n\n"
                
                if file_path.exists():
                    existing_content = file_path.read_text(encoding="utf-8")
                    if not fetch_desc:
                        match = re.search(r"## Description\n(.*?)\n##", existing_content, re.DOTALL)
                        description_text = match.group(1).strip() if match else "Description missing."
                    if not fetch_trans:
                         match = re.search(r"## Transcript\n(.*)", existing_content, re.DOTALL)
                         transcript_text = match.group(1).strip() if match else ""

                md_content += f"## Description\n{description_text}\n\n"
                if links_text:
                    md_content += f"## Links\n{links_text}\n"
                if transcript_text:
                    md_content += f"## Transcript\n{transcript_text}\n"

                file_path.write_text(md_content, encoding="utf-8")
                
                # Update Manifest
                self.manifest["episodes"][entry_id] = {
                    "title": title,
                    "clean_title": clean_title,
                    "has_description": bool(description_text),
                    "has_transcript": bool(transcript_text),
                    "last_updated": datetime.now().isoformat()
                }
                self._save_manifest()
                logger.info(f"Successfully saved '{title}'")

            except Exception as e:
                logger.error(f"Error processing '{title}': {e}")
            finally:
                await context.close()

    async def run(self):
        logger.info("Starting Podcast Scraper...")
        config.OUTPUT_DIR.mkdir(exist_ok=True)



        feed = feedparser.parse(config.RSS_URL)
        if feed.status != 200:
            logger.error(f"RSS Feed failed (Status {feed.status})")
            return

        logger.info(f"Found {len(feed.entries)} entries.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            tasks = [self.process_episode(entry, browser) for entry in feed.entries]
            await asyncio.gather(*tasks)
            await browser.close()

        logger.info("Scraping finished.")


if __name__ == "__main__":
    async def start():
        scraper = PodcastScraper()
        await scraper.run()
    asyncio.run(start())