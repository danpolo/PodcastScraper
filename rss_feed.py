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
from youtube_transcript_api.proxies import WebshareProxyConfig
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
        self.manifest_lock = asyncio.Lock()
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
        # Normalize whitespace and remove problematic chars
        clean = re.sub(r'[\\/*?:\"<>|]', "", title)
        # Ensure single spaces throughout and strip
        return " ".join(clean.split()).strip()

    def _clean_description_text(self, raw_text: str) -> str:
        if not raw_text:
            return ""
        # Remove Spotify expansion markers
        text = re.sub(r'Show less|ראה פחות', '', raw_text, flags=re.IGNORECASE)
        # Preserve basic structure but clean up excessive empty lines
        lines = [line.strip() for line in text.split('\n')]
        # Filter out empty lines while keeping a single blank line between content
        cleaned_lines = []
        last_empty = False
        for line in lines:
            if line:
                cleaned_lines.append(line)
                last_empty = False
            elif not last_empty:
                cleaned_lines.append("")
                last_empty = True
        return "\n".join(cleaned_lines).strip()

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



    async def process_episode(self, entry: EpisodeEntry, browser: Browser, spotify_url: str = None):
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
                
                # Load existing content if file exists to preserve data not being fetched
                if file_path.exists():
                    try:
                        existing_content = file_path.read_text(encoding="utf-8")
                        if "## Description" in existing_content:
                            desc_part = existing_content.split("## Description")[1].split("##")[0].strip()
                            description_text = desc_part
                        if "## Links" in existing_content:
                            links_part = existing_content.split("## Links")[1].split("##")[0].strip()
                            links_text = links_part
                        if "## Transcript" in existing_content:
                            trans_part = existing_content.split("## Transcript")[1].strip()
                            transcript_text = trans_part
                    except Exception as e:
                        logger.warning(f"Failed to read existing file for '{title}': {e}")

                # 1. Fetch Description from Spotify
                if fetch_desc:
                    try:
                        if not spotify_url:
                            logger.warning(f"No Spotify URL provided for '{title}', skipping description fetch")
                        else:
                            logger.info(f"Fetching description from Spotify for '{title}'")
                            await page.goto(spotify_url, wait_until="networkidle", timeout=60000)
                            await page.wait_for_timeout(2000)
                            
                            # Extract description via JS
                            js_script = """(selector) => {
                                // 1. Try to find and click "Show more"
                                const expandButtons = Array.from(document.querySelectorAll('button, span')).filter(el => 
                                    el.innerText && (el.innerText.includes('Show more') || el.innerText.includes('ראה עוד') || el.innerText.includes('See more'))
                                );
                                expandButtons.forEach(btn => btn.click());
                                
                                return new Promise(resolve => {
                                    setTimeout(() => {
                                        // 2. Try to find host container by selector
                                        let container = document.querySelector(selector);
                                        
                                        // 3. Fallback: Find by header and semantic location
                                        if (!container || container.innerText.length < 50) {
                                            const h2s = Array.from(document.querySelectorAll('h2, span, p')).filter(el => 
                                                el.innerText && (el.innerText.includes('Episode Description') || el.innerText.includes('תיאור הפרק'))
                                            );
                                            if (h2s.length > 0) {
                                                let h = h2s[0];
                                                let sibling = h.nextElementSibling;
                                                while (sibling) {
                                                    if (['DIV', 'P', 'SPAN'].includes(sibling.tagName) && 
                                                        sibling.innerText.length > 50 && 
                                                        !sibling.innerText.includes('heap.load')) {
                                                        container = sibling;
                                                        break;
                                                    }
                                                    sibling = sibling.nextElementSibling;
                                                }
                                            }
                                        }
                                        
                                        if (!container) return resolve(null);
                                        
                                        const text = container.innerText;
                                        const links = Array.from(container.querySelectorAll('a'))
                                            .filter(a => a.href && !a.href.includes('spotify.com') && !a.href.startsWith('mailto:'))
                                            .map(a => `- [${a.innerText.trim() || a.innerText}](${a.href})`);
                                            
                                        resolve({ text, links: links.join('\\n') });
                                    }, 1500);
                                });
                            }"""
                            spotify_data = await page.evaluate(js_script, config.SPOTIFY_DESC_SELECTOR)

                            if spotify_data:
                                description_text = self._clean_description_text(spotify_data['text'])
                                links_text = spotify_data['links']
                                
                                if not links_text:
                                    # Fallback: regex for plain text URLs
                                    urls = re.findall(r'https?://[^\s)\]]+', spotify_data['text'])
                                    final_urls = sorted(list(set(u for u in urls if "spotify.com" not in u)))
                                    links_text = "\n".join([f"- {u}" for u in final_urls])
                                
                                logger.info(f"Successfully extracted description and links from Spotify for '{title}'")
                            else:
                                logger.warning(f"Failed to extract Spotify data for '{title}'")
                    except Exception as e:
                        logger.error(f"Error fetching description from Spotify for '{title}': {e}")

                # 2. Fetch Transcript from YouTube
                if fetch_trans:
                    video_id = entry.id # We found it via YouTube discovery
                    logger.info(f"Fetching YouTube transcript for '{title}' (ID: {video_id})")
                    try:
                        transcript_list = YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(proxy_username=config.PROXY_USERNAME, proxy_password=config.PROXY_PASSWORD)).fetch(video_id, languages=['he', 'en', 'iw'])
                        formatter = TextFormatter()
                        transcript_text = formatter.format_transcript(transcript_list)
                        logger.info(f"Successfully fetched YouTube transcript for '{title}'")
                    except Exception as e:
                        logger.warning(f"YouTube transcript failed for '{title}': {e}")

                # 3. Save to Markdown
                if description_text or transcript_text:
                    # If we didn't fetch description but it was already in manifest, we should keep it?
                    # No, process_episode is called with fetch_desc/fetch_trans flags.
                    # If fetch_desc is False, description_text is "". We should NOT overwrite a good file with missing desc.
                    
                    # Better: If we have existing content, read it? No, manifest is source of truth.
                    
                    content = f"# {title}\n\n"
                    content += f"**Published Date:** {entry.published}\n\n"
                    if description_text:
                        content += f"## Description\n{description_text}\n\n"
                    if links_text:
                        content += f"## Links\n{links_text}\n\n"
                    if transcript_text:
                        content += f"## Transcript\n{transcript_text}\n"
                    
                    file_path.write_text(content, encoding="utf-8")
                
                # Update Manifest only if we actually did something or want to preserve
                async with self.manifest_lock:
                    self.manifest = self._load_manifest()
                    self.manifest["episodes"][entry_id] = {
                        "title": title,
                        "has_description": bool(description_text) if fetch_desc else entry.get('has_description', False),
                        "has_transcript": bool(transcript_text) if fetch_trans else entry.get('has_transcript', False),
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

            except Exception as e:
                logger.error(f"Failed to discover episodes via YouTube: {e}")
                await context.close()
                return

            # 1. Discover Spotify episodes (in order, newest first)
            spotify_urls = []
            try:
                logger.info(f"Discovering Spotify episodes: {config.SPOTIFY_URL}")
                await page.goto(config.SPOTIFY_URL, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(3000)
                
                # Scroll to load more episodes
                for _ in range(3):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1000)
                
                # Extract all episode URLs in DOM order (newest first on Spotify)
                spotify_urls = await page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/episode/"]'));
                    const seen = new Set();
                    return links
                        .map(a => a.href)
                        .filter(href => {
                            if (seen.has(href)) return false;
                            seen.add(href);
                            return true;
                        });
                }""")
                logger.info(f"Found {len(spotify_urls)} Spotify episode URLs")
                
            except Exception as e:
                logger.error(f"Failed to discover Spotify episodes: {e}")
            
            await context.close()

            # 2. Process Episodes with index-based matching
            tasks = []
            for i, entry in enumerate(entries):
                spotify_url = spotify_urls[i] if i < len(spotify_urls) else None
                tasks.append(self.process_episode(entry, browser, spotify_url))
            await asyncio.gather(*tasks)
            await browser.close()

        logger.info("Scraping finished.")


if __name__ == "__main__":
    async def start():
        scraper = PodcastScraper()
        await scraper.run()
    asyncio.run(start())