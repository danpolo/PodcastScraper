import asyncio
import feedparser
import re
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from playwright.async_api import async_playwright, Browser, Playwright, Route

import config
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

# --- Entry Helper ---
class EpisodeEntry:
    def __init__(self, id_val: str, title: str, link: str, published: str):
        self.id = id_val
        self.title = title
        self.link = link
        self.published = published

    def get(self, key, default=None):
        return getattr(self, key, default)

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



    async def process_episode(self, entry: EpisodeEntry, browser: Browser):
        async with self.semaphore:
            title = entry.title
            clean_title = self._clean_filename(title)
            file_path = config.OUTPUT_DIR / f"{clean_title}.md"
            
            # Check manifest for status
            entry_id = entry.id
            status = self.manifest["episodes"].get(entry_id, {})
            
            fetch_desc = not status.get("has_description", False)
            fetch_trans = not status.get("has_transcript", False)

            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                if "## Links" not in content or len(content) < 500:
                    fetch_desc = True
            else:
                fetch_desc = True
                fetch_trans = True

            if not fetch_desc and not fetch_trans:
                logger.info(f"Skipping '{title}', already up to date.")
                return

            logger.info(f"Processing '{title}' (Desc: {fetch_desc}, Trans: {fetch_trans})")
            
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

                # 1. Fetch Description from Apple Podcasts
                if fetch_desc:
                    try:
                        logger.info(f"Fetching description from Apple Podcasts for '{title}'")
                        await page.goto(config.APPLE_PODCASTS_URL, wait_until="networkidle")
                        
                        # Find the episode link by title
                        # Apple Pods titles might be slightly different, use a fuzzy match if needed
                        episode_link_selector = f'a:has-text("{title}")'
                        episode_link = page.locator(episode_link_selector).first
                        
                        if await episode_link.is_visible():
                            await episode_link.click()
                            await page.wait_for_load_state("networkidle")
                            
                            # Extract description (notes)
                            # On episode page, description is usually in a specific section
                            desc_container = page.locator('.product-hero-desc__section').first
                            if not await desc_container.is_visible():
                                desc_container = page.locator('.description').first

                            raw_desc = await desc_container.inner_text()
                            description_text = self._clean_description_text(raw_desc)
                            
                            # Extract Links
                            links = desc_container.locator("a")
                            link_count = await links.count()
                            link_list = []
                            for i in range(link_count):
                                l = links.nth(i)
                                href = await l.get_attribute("href")
                                text = await l.inner_text()
                                if href and not href.startswith("mailto:"):
                                    link_list.append(f"- [{text.strip()}]({href})")
                            
                            if link_list:
                                links_text = "\n".join(link_list)
                            
                            logger.info(f"Found description/links on Apple Podcasts for '{title}'")
                        else:
                            logger.warning(f"Episode link not found on Apple Podcasts for '{title}'")
                    except Exception as e:
                        logger.warning(f"Apple Podcasts fetch failed for '{title}': {e}")

                # 2. Fetch Transcript from YouTube
                if fetch_trans:
                    video_id = entry.id # We found it via YouTube discovery
                    logger.info(f"Fetching YouTube transcript for '{title}' (ID: {video_id})")
                    try:
                        transcript_list = YouTubeTranscriptApi().fetch(video_id, languages=['he', 'en', 'iw'])
                        formatter = TextFormatter()
                        transcript_text = formatter.format_transcript(transcript_list)
                        logger.info(f"Successfully fetched YouTube transcript for '{title}'")
                    except Exception as e:
                        logger.warning(f"YouTube transcript failed for '{title}': {e}")

                # 3. Save to Markdown
                if description_text or transcript_text:
                    content = f"# {title}\n\n"
                    content += f"**Published Date:** {entry.published}\n\n"
                    if description_text:
                        content += f"## Description\n{description_text}\n\n"
                    if links_text:
                        content += f"## Links\n{links_text}\n\n"
                    if transcript_text:
                        content += f"## Transcript\n{transcript_text}\n"
                    
                    file_path.write_text(content, encoding="utf-8")
                
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

        async with async_playwright() as p:
            # 0. Discover Episodes via YouTube (Bypass Substack 403)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            entries = []
            try:
                logger.info(f"Discovering episodes via YouTube: {config.YOUTUBE_CHANNEL_VIDEOS_URL}")
                await page.goto(config.YOUTUBE_CHANNEL_VIDEOS_URL, wait_until="networkidle")
                
                # Extract ytInitialData
                video_data = await page.evaluate("""() => {
                    const data = window.ytInitialData;
                    const tabs = data.contents.twoColumnBrowseResultsRenderer.tabs;
                    const videosTab = tabs.find(tab => tab.tabRenderer && tab.tabRenderer.title === 'Videos');
                    if (!videosTab) return [];
                    
                    const contents = videosTab.tabRenderer.content.richGridRenderer.contents;
                    return contents
                        .filter(item => item.richItemRenderer && item.richItemRenderer.content.videoRenderer)
                        .map(item => {
                            const v = item.richItemRenderer.content.videoRenderer;
                            return {
                                id: v.videoId,
                                title: v.title.runs[0].text,
                                published: v.publishedTimeText ? v.publishedTimeText.simpleText : 'Unknown'
                            };
                        });
                }""")
                
                if not video_data:
                    logger.error("No video data found in YouTube's ytInitialData")
                    # Fallback screenshot
                    await page.screenshot(path=str(config.OUTPUT_DIR / "youtube_discovery_failure.png"))
                    return

                entries = [
                    EpisodeEntry(
                        id_val=v['id'],
                        title=v['title'],
                        link=f"https://www.youtube.com/watch?v={v['id']}",
                        published=v['published']
                    )
                    for v in video_data
                ]
                logger.info(f"Found {len(entries)} entries via YouTube discovery.")
                await context.close()

            except Exception as e:
                logger.error(f"Failed to discover episodes via YouTube: {e}")
                return

            # 1. Process Episodes
            tasks = [self.process_episode(entry, browser) for entry in entries]
            await asyncio.gather(*tasks)
            await browser.close()

        logger.info("Scraping finished.")


if __name__ == "__main__":
    async def start():
        scraper = PodcastScraper()
        await scraper.run()
    asyncio.run(start())