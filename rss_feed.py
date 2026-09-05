import asyncio
import feedparser
import re
import logging
import urllib.request
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, Route

import config
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
from youtube_transcript_api.formatters import TextFormatter

# --- Entry Helper ---
class EpisodeEntry:
    def __init__(self, id_val: str, title: str, link: str, published: str, description: str = ""):
        self.id = id_val
        self.title = title
        self.link = link
        self.published = published
        self.description = description

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
                manifest = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
                self._backfill_description_source(manifest)
                return manifest
            except Exception as e:
                logger.error(f"Failed to load manifest: {e}")
        return {"episodes": {}}

    def _backfill_description_source(self, manifest: dict):
        """Tag existing entries that predate description_source tracking.

        Shorts can never have a real Spotify description (they have no Spotify
        episode page). Any short that was previously given a Spotify description
        received it from a misaligned index — reset it so the correct YouTube
        RSS description is fetched on the next run.
        """
        dirty = False
        for ep in manifest["episodes"].values():
            title = ep.get("title", "")
            is_short = "#substack #shorts" in title.lower()

            # Shorts with a stale spotify tag from the old misaligned runs
            if is_short and ep.get("description_source") == "spotify":
                ep["description_source"] = "youtube_rss"
                ep["has_description"] = False
                dirty = True
                continue

            if "description_source" in ep or not ep.get("has_description"):
                continue

            file_path = config.OUTPUT_DIR / f"{self._clean_filename(title)}.md"
            source = "youtube_rss"
            if not is_short and file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if "## Description" in content:
                        desc = content.split("## Description")[1].split("##")[0].strip()
                        if len(desc) >= 400:
                            source = "spotify"
                except Exception:
                    pass
            ep["description_source"] = source
            dirty = True
        if dirty:
            self._save_manifest_raw(manifest)

    def _save_manifest_raw(self, manifest: dict):
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_manifest(self):
        self._save_manifest_raw(self.manifest)

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

    def _entries_from_rss(self, feed) -> list[EpisodeEntry]:
        """Convert YouTube RSS entries into the scraper's stable episode shape."""
        return [
            EpisodeEntry(
                id_val=entry.id.split(":")[-1],
                title=entry.title,
                link=entry.link,
                published=entry.published,
                description=entry.get("summary", ""),
            )
            for entry in feed.entries
        ]

    async def _block_resources(self, route: Route):
        if route.request.resource_type in config.BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()




    async def process_episode(self, entry: EpisodeEntry, browser: Optional[Browser] = None, spotify_url: Optional[str] = None):
        async with self.semaphore:
            title = entry.title
            clean_title = self._clean_filename(title)
            file_path = config.OUTPUT_DIR / f"{clean_title}.md"

            entry_id = entry.id
            status = self.manifest["episodes"].get(entry_id, {})

            # Fetch if no description yet, or if we only have a YouTube RSS fallback
            # but Spotify is now available (upgrade to full show notes).
            has_spotify_desc = status.get("description_source") == "spotify"
            fetch_desc = (
                not status.get("has_description", False)
                or (not has_spotify_desc and spotify_url is not None)
            )
            fetch_trans = not status.get("has_transcript", False)

            if not file_path.exists():
                fetch_desc = True
                fetch_trans = True
            elif "## Description" not in file_path.read_text(encoding="utf-8"):
                fetch_desc = True

            if not fetch_desc and not fetch_trans:
                logger.info(f"Skipping '{title}', already up to date.")
                return

            logger.info(f"Processing '{title}' (Desc: {fetch_desc}, Trans: {fetch_trans})")

            description_text = ""
            links_text = ""
            transcript_text = ""

            # Preserve existing content for sections we are not re-fetching
            if file_path.exists():
                try:
                    existing = file_path.read_text(encoding="utf-8")
                    if not fetch_desc:
                        if "## Description" in existing:
                            description_text = existing.split("## Description")[1].split("##")[0].strip()
                        if "## Links" in existing:
                            links_text = existing.split("## Links")[1].split("##")[0].strip()
                    if not fetch_trans and "## Transcript" in existing:
                        transcript_text = existing.split("## Transcript")[1].strip()
                except Exception as e:
                    logger.warning(f"Failed to read existing file for '{title}': {e}")

            # 1. Description — Spotify primary, YouTube RSS fallback
            if fetch_desc:
                description_fetched = False

                if spotify_url and browser:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = await context.new_page()
                    await page.route("**/*", self._block_resources)
                    try:
                        logger.info(f"Fetching description from Spotify for '{title}'")
                        await page.goto(spotify_url, wait_until="networkidle", timeout=60000)
                        await page.wait_for_timeout(2000)
                        spotify_data = await page.evaluate("""(selector) => {
                            const expandButtons = Array.from(document.querySelectorAll('button, span')).filter(el =>
                                el.innerText && (el.innerText.includes('Show more') || el.innerText.includes('ראה עוד') || el.innerText.includes('See more'))
                            );
                            expandButtons.forEach(btn => btn.click());
                            return new Promise(resolve => {
                                setTimeout(() => {
                                    let container = document.querySelector(selector);
                                    if (!container || container.innerText.length < 50) {
                                        const h2s = Array.from(document.querySelectorAll('h2, span, p')).filter(el =>
                                            el.innerText && (el.innerText.includes('Episode Description') || el.innerText.includes('תיאור הפרק'))
                                        );
                                        if (h2s.length > 0) {
                                            let sibling = h2s[0].nextElementSibling;
                                            while (sibling) {
                                                if (['DIV','P','SPAN'].includes(sibling.tagName) && sibling.innerText.length > 50 && !sibling.innerText.includes('heap.load')) {
                                                    container = sibling; break;
                                                }
                                                sibling = sibling.nextElementSibling;
                                            }
                                        }
                                    }
                                    if (!container) return resolve(null);
                                    const links = Array.from(container.querySelectorAll('a'))
                                        .filter(a => a.href && !a.href.includes('spotify.com') && !a.href.startsWith('mailto:'))
                                        .map(a => `- [${a.innerText.trim()}](${a.href})`);
                                    resolve({ text: container.innerText, links: links.join('\\n') });
                                }, 1500);
                            });
                        }""", config.SPOTIFY_DESC_SELECTOR)

                        if spotify_data and len(spotify_data.get('text', '')) > 50:
                            description_text = self._clean_description_text(spotify_data['text'])
                            links_text = spotify_data['links']
                            if not links_text:
                                urls = re.findall(r'https?://[^\s)\]]+', spotify_data['text'])
                                links_text = "\n".join(f"- {u}" for u in sorted(set(u for u in urls if 'spotify.com' not in u)))
                            logger.info(f"Got description from Spotify for '{title}'")
                            description_fetched = True
                        else:
                            logger.warning(f"Spotify description empty for '{title}', falling back to YouTube RSS")
                    except Exception as e:
                        logger.warning(f"Spotify description failed for '{title}': {e}")
                    finally:
                        await context.close()

                if not description_fetched:
                    raw = entry.description or ""
                    if raw:
                        description_text = self._clean_description_text(raw)
                        urls = re.findall(r'https?://[^\s)\]]+', raw)
                        links_text = "\n".join(
                            f"- {u}" for u in sorted(set(
                                u for u in urls if 'youtube.com' not in u and 'youtu.be' not in u
                            ))
                        )
                        logger.info(f"Got description from YouTube RSS for '{title}'")
                    else:
                        logger.warning(f"No description available for '{title}'")

            # 2. Transcript from YouTube API (direct first, proxy fallback)
            if fetch_trans:
                logger.info(f"Fetching transcript for '{title}' (ID: {entry_id})")
                try:
                    try:
                        transcript_list = YouTubeTranscriptApi().fetch(entry_id, languages=['he', 'en', 'iw'])
                    except Exception:
                        transcript_list = YouTubeTranscriptApi(
                            proxy_config=WebshareProxyConfig(
                                proxy_username=config.PROXY_USERNAME,
                                proxy_password=config.PROXY_PASSWORD,
                            )
                        ).fetch(entry_id, languages=['he', 'en', 'iw'])
                    transcript_text = TextFormatter().format_transcript(transcript_list)
                    logger.info(f"Successfully fetched transcript for '{title}'")
                except Exception as e:
                    logger.warning(f"Transcript unavailable for '{title}': {e}")

            # 3. Save to Markdown
            if description_text or transcript_text:
                md = f"# {title}\n\n**Published Date:** {entry.published}\n\n"
                if description_text:
                    md += f"## Description\n{description_text}\n\n"
                if links_text:
                    md += f"## Links\n{links_text}\n\n"
                if transcript_text:
                    md += f"## Transcript\n{transcript_text}\n"
                file_path.write_text(md, encoding="utf-8")

            # 4. Update manifest
            async with self.manifest_lock:
                self.manifest = self._load_manifest()
                prev = self.manifest["episodes"].get(entry_id, {})
                if fetch_desc and description_text:
                    new_source = "spotify" if description_fetched else "youtube_rss"
                else:
                    new_source = prev.get("description_source")
                self.manifest["episodes"][entry_id] = {
                    "title": title,
                    "has_description": bool(description_text) if fetch_desc else prev.get('has_description', False),
                    "description_source": new_source,
                    "has_transcript": bool(transcript_text) if fetch_trans else prev.get('has_transcript', False),
                    "last_updated": datetime.now().isoformat()
                }
                self._save_manifest()
            logger.info(f"Saved '{title}'")

    async def run(self):
        logger.info("Starting Podcast Scraper...")
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Discover episodes via YouTube RSS (no browser needed)
        entries = []
        try:
            logger.info("Resolving YouTube channel ID from handle @AITHINKER_S...")
            req = urllib.request.Request(
                'https://www.youtube.com/@AITHINKER_S',
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode('utf-8', errors='replace')

            channel_match = re.search(r'"externalId":"(UC[^"]+)"', html)
            if not channel_match:
                logger.error("Could not extract channel ID from YouTube handle page")
                return

            channel_id = channel_match.group(1)
            logger.info(f"Resolved channel ID: {channel_id}")

            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            logger.info(f"Fetching YouTube RSS feed: {rss_url}")
            feed = feedparser.parse(rss_url)

            if not feed.entries:
                logger.error("No entries found in YouTube RSS feed")
                return

            entries = self._entries_from_rss(feed)
            logger.info(f"Found {len(entries)} entries via YouTube RSS feed.")

        except Exception as e:
            logger.error(f"Failed to discover episodes via YouTube RSS: {e}")
            return

        # Try Spotify discovery; fall back gracefully if blocked or unavailable
        spotify_urls = []
        pw = None
        browser = None
        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await ctx.new_page()
            try:
                logger.info(f"Discovering Spotify episodes: {config.SPOTIFY_URL}")
                await page.goto(config.SPOTIFY_URL, wait_until="networkidle", timeout=60000)
                await page.wait_for_selector('a[href*="/episode/"]', timeout=15000)
                await page.wait_for_timeout(2000)
                while True:
                    btn = await page.query_selector('button:has-text("Load more episodes")')
                    if not btn:
                        break
                    await btn.click()
                    await page.wait_for_timeout(2000)
                spotify_urls = await page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/episode/"]'));
                    const seen = new Set();
                    return links
                        .filter(a => { const t = a.innerText || ''; return !['מה יש פה בעצם'].some(s => t.includes(s)); })
                        .map(a => a.href)
                        .filter(href => { if (seen.has(href)) return false; seen.add(href); return true; });
                }""")
                logger.info(f"Found {len(spotify_urls)} Spotify episode URLs")
            except Exception as e:
                logger.warning(f"Spotify unavailable ({type(e).__name__}), using YouTube RSS descriptions")
            await ctx.close()
        except Exception as e:
            logger.warning(f"Browser launch failed ({e}), using YouTube RSS descriptions")

        # Build tasks: shorts skip Spotify; full episodes get indexed Spotify URL if available
        spotify_idx = 0
        tasks = []
        for entry in entries:
            if '#substack #shorts' in entry.title.lower():
                tasks.append(self.process_episode(entry, browser=browser))
            else:
                surl = spotify_urls[spotify_idx] if spotify_idx < len(spotify_urls) else None
                if surl:
                    spotify_idx += 1
                tasks.append(self.process_episode(entry, browser=browser, spotify_url=surl))

        await asyncio.gather(*tasks)

        if browser:
            await browser.close()
        if pw:
            await pw.stop()

        logger.info("Scraping finished.")


if __name__ == "__main__":
    async def start():
        scraper = PodcastScraper()
        await scraper.run()
    asyncio.run(start())
