"""LangTalks audio-RSS client.

Unlike AI Thinkers, LangTalks has no usable caption track — the only YouTube
track is Hebrew ASR, which transliterates the English technical terms into
Hebrew script. So the audio itself is the source of record and the RSS feed is
what points at it.

Two host quirks matter and are handled here:

1. The enclosure host returns 403 to requests without a browser User-Agent.
2. Older enclosure URLs are doubly percent-encoded (``%2520``). The URL must be
   passed through byte-for-byte as it appears in the feed — decoding it yields
   a 404.
"""

import hashlib
import logging
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import feedparser

logger = logging.getLogger(__name__)

FEED_URL = "https://feeds.async.com/47/928fdaee-6711-4272-9695-e721488d8c33.rss"

# The enclosure host 403s anything that does not look like a browser.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_EPISODE_NUMBER_RE = re.compile(r"^\s*(\d+)\s*-")


def _parse_duration(raw: str) -> int:
    """iTunes duration ("HH:MM:SS" or "MM:SS") to seconds."""
    if not raw:
        return 0
    parts = [int(p) for p in raw.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


@dataclass
class Episode:
    guid: str
    title: str
    published: str
    audio_url: str
    duration_seconds: int
    description: str = ""
    links: list = field(default_factory=list)

    @property
    def number(self) -> Optional[int]:
        """Leading episode number from the title, when the title carries one."""
        match = _EPISODE_NUMBER_RE.match(self.title)
        return int(match.group(1)) if match else None

    @property
    def slug(self) -> str:
        clean = re.sub(r'[\\/*?:"<>|]', "", self.title)
        return " ".join(clean.split()).strip()


def fetch_episodes(feed_url: str = FEED_URL) -> list:
    """All episodes in the feed, newest first."""
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        raise RuntimeError(f"No entries in LangTalks feed: {feed_url}")

    episodes = []
    for entry in feed.entries:
        enclosures = entry.get("enclosures") or []
        if not enclosures:
            logger.warning("Skipping '%s': no enclosure", entry.get("title"))
            continue
        description = entry.get("summary", "") or ""
        episodes.append(
            Episode(
                guid=entry.get("id", ""),
                title=entry.get("title", ""),
                published=entry.get("published", ""),
                audio_url=enclosures[0]["href"],
                duration_seconds=_parse_duration(entry.get("itunes_duration", "")),
                description=description,
                links=sorted(set(re.findall(r"https?://[^\s)\]<]+", description))),
            )
        )

    # The feed is published oldest-first; callers care about recent episodes.
    episodes.reverse()
    return episodes


def download_audio(episode: Episode, dest_dir: Path) -> Path:
    """Download an episode's audio, skipping the fetch if it is already local.

    Returns the local path. The URL is used exactly as it appeared in the feed;
    re-encoding it breaks the doubly-encoded older entries.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{episode.guid}.mp3"
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Audio already present for '%s'", episode.title)
        return dest

    logger.info("Downloading audio for '%s'", episode.title)
    request = urllib.request.Request(episode.audio_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()

    # Write via a temp name so an interrupted download never looks complete.
    partial = dest.with_suffix(".mp3.part")
    partial.write_bytes(payload)
    partial.rename(dest)
    logger.info("Saved %.1f MB to %s", len(payload) / 1e6, dest)
    return dest


def audio_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
