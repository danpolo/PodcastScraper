"""Read-only coverage audit for AI Thinkers discovery sources.

Never use this report to remove one of RSS, YouTube, or Spotify until the
episode-level union and all useful fields have been verified.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
import urllib.request

import feedparser
from playwright.async_api import async_playwright

import config

RSS_URL = "https://anchor.fm/s/10a582630/podcast/rss"
YOUTUBE_HANDLE_URL = "https://www.youtube.com/@AITHINKER_S"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
LINK_RE = re.compile(r"https?://[^\s<>\"']+")


def normalize_title(title):
    """Conservative cross-platform title matching for Hebrew + English."""
    return " ".join(re.findall(r"[\w\u0590-\u05ff]+", title.casefold()))


def match_sources(items, threshold=0.88, ambiguity_margin=0.08):
    """Suggest only high-confidence, unique matches; do not rewrite source data.

    Reports unmatched/ambiguous episodes instead of guessing from list order.
    One-to-one matches across sources are deliberately conservative.
    """
    indexed = []
    for source in sorted(items):
        for episode in items[source]:
            indexed.append((source, episode))
    groups = []
    ambiguous = []
    for source, episode in indexed:
        title = normalize_title(episode.get("title") or "")
        if not title:
            ambiguous.append({"source": source, "id": episode.get("id"),
                              "reason": "empty title"})
            groups.append({"entries": [{"source": source, **episode}]})
            continue
        options = []
        for index, group in enumerate(groups):
            if any(row["source"] == source for row in group["entries"]):
                continue
            similarities = [
                SequenceMatcher(None, title, normalize_title(row.get("title", ""))).ratio()
                for row in group["entries"] if row.get("title")
            ]
            if similarities:
                options.append((max(similarities), index))
        options.sort(reverse=True)
        best = options[0] if options else (0, -1)
        second = options[1][0] if len(options) > 1 else 0
        if best[0] >= threshold and best[0] - second >= ambiguity_margin:
            groups[best[1]]["entries"].append({"source": source, **episode})
        else:
            if best[0] >= threshold:
                ambiguous.append({"source": source, "id": episode.get("id"),
                                  "reason": "multiple similar titles",
                                  "best_similarity": round(best[0], 3)})
            groups.append({"entries": [{"source": source, **episode}]})
    return groups, ambiguous


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        return response.read()


def _parse_feed(raw, source):
    parsed = feedparser.parse(raw)
    if not parsed.entries:
        raise RuntimeError(f"{source} feed contains no entries "
                           f"(bozo={parsed.get('bozo', False)})")
    episodes = []
    for ep in parsed.entries:
        descriptions = [ep.get("summary", ""), ep.get("description", "")]
        description = max(descriptions, key=len)
        enclosures = ep.get("enclosures") or []
        episodes.append({
            "id": ep.get("id", "") or ep.get("link", ""),
            "title": ep.get("title", ""),
            "published": ep.get("published", ""),
            "description_chars": len(description),
            "links": sorted(set(LINK_RE.findall(description))),
            "url": ep.get("link", ""),
            "audio_url": enclosures[0].get("href", "") if enclosures else "",
        })
    return episodes


def _youtube():
    html = _fetch(YOUTUBE_HANDLE_URL).decode("utf-8", errors="replace")
    match = re.search(r'"externalId":"(UC[^"]+)"', html)
    if not match:
        raise RuntimeError("YouTube channel ID missing from handle page")
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + match.group(1)
    return _parse_feed(_fetch(url), "youtube")


def _rss():
    return _parse_feed(_fetch(RSS_URL), "rss")


async def _spotify():
    """Collect titles/IDs visible on Spotify; no positional matching."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent=UA)
            await page.goto(config.SPOTIFY_URL, wait_until="domcontentloaded",
                            timeout=60000)
            await page.wait_for_selector('a[href*="/episode/"]', timeout=20000)
            for _ in range(80):
                buttons = await page.query_selector_all(
                    'button:has-text("Load more episodes")')
                if not buttons:
                    break
                await buttons[0].click()
                await page.wait_for_timeout(750)
            rows = await page.evaluate("""() => {
                const seen = new Set();
                return [...document.querySelectorAll('a[href*="/episode/"]')]
                  .map(a => {
                    const href = a.href.split('?')[0];
                    const text = (a.innerText || a.getAttribute('aria-label') ||
                      a.getAttribute('title') || '').trim();
                    return {href, text};
                  }).filter(x => {
                    if (seen.has(x.href)) return false;
                    seen.add(x.href);
                    return true;
                  });
            }""")
        finally:
            await browser.close()
    return [{
        "id": row["href"].rstrip("/").split("/")[-1],
        "title": row["text"],
        "published": "",
        "description_chars": None,
        "links": [],
        "url": row["href"],
        "audio_url": "",
    } for row in rows]


async def collect():
    sources, errors = {}, {}
    for name, fn in (("rss", _rss), ("youtube", _youtube)):
        try:
            sources[name] = fn()
        except Exception as exc:
            sources[name] = []
            errors[name] = str(exc)
    try:
        sources["spotify"] = await _spotify()
    except Exception as exc:
        sources["spotify"] = []
        errors["spotify"] = str(exc)
    return sources, errors


def build_report(sources, errors=None):
    errors = errors or {}
    groups, ambiguous = match_sources(sources)
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_counts": {key: len(sources.get(key, []))
                          for key in ("rss", "youtube", "spotify")},
        "source_errors": errors,
        "union_count_conservative": len(groups),
        "linked_groups": sum(len(group["entries"]) > 1 for group in groups),
        "unmatched_by_source": {
            source: [{"id": row["id"], "title": row.get("title", "")}
                     for group in groups if len(group["entries"]) == 1
                     for row in group["entries"] if row["source"] == source]
            for source in ("rss", "youtube", "spotify")
        },
        "ambiguous": ambiguous,
        "groups": groups,
        "warning": (
            "Conservative title matches are suggestions, not verified identity. "
            "YouTube Atom only covers recent videos; local manifest may cover more. "
            "Do not drop any discovery source based solely on this report."
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    sources, errors = asyncio.run(collect())
    report = build_report(sources, errors)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(json.dumps({"counts": report["source_counts"],
                      "union": report["union_count_conservative"],
                      "errors": report["source_errors"]}, ensure_ascii=False))
    if all(not records for records in sources.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
