# PodcastScraper

Scrapes episodes of the Hebrew-language **AI Thinkers** podcast ([@AITHINKER_S](https://www.youtube.com/@AITHINKER_S)) and stores each one as a Markdown file with its description, links, and full transcript. A weekly GitHub Action keeps the data current.

## How it works

`rss_feed.py` is the whole pipeline:

1. **Discovery** — resolves the YouTube channel ID from the `@AITHINKER_S` handle page, then parses the channel RSS feed (`feeds/videos.xml`). This is the source of truth for the episode list; no browser needed.
2. **Spotify episode index** — launches headless Chromium (Playwright), opens the [Spotify show page](https://open.spotify.com/show/5qXP9dnucaWoHe6VMB56wc), clicks through *Load more episodes*, and collects episode URLs. If Spotify is blocked or the browser fails to launch, the run continues without it.
3. **Descriptions** — Spotify is preferred (full show notes, with outbound links extracted). YouTube RSS `summary` is the fallback. Shorts (titles containing `#substack #shorts`) skip Spotify entirely, since they have no Spotify episode page.
4. **Transcripts** — `youtube-transcript-api`, tried direct first and then through a Webshare proxy if the direct call is blocked. Languages: `he`, `en`, `iw`.
5. **Output** — one `<clean title>.md` per episode plus a `manifest.json` tracking what has already been fetched.

Episodes are processed concurrently with a semaphore (`CONCURRENCY_LIMIT = 2`). Images and fonts are blocked at the network layer to speed up page loads.

### Incremental behaviour

`manifest.json` records `has_description`, `has_transcript`, `description_source`, and `last_updated` per YouTube video ID. On each run an episode is re-fetched only if:

- it has no description or no transcript yet, **or**
- its description came from the YouTube RSS fallback and a Spotify URL is now available (upgrade to full show notes), **or**
- its Markdown file is missing or has no `## Description` section.

Sections that are *not* being re-fetched are read back out of the existing file and preserved, so a partial run never loses data.

### Output format

```markdown
# <episode title>

**Published Date:** 2026-01-31T18:09:29+00:00

## Description
...

## Links
- https://example.com

## Transcript
...
```

## Setup

```bash
pip install -r requirements.txt
playwright install chromium --with-deps
```

Requires Python 3.11+.

## Configuration

Settings live in `config.py`. Two things come from the environment:

| Variable | Purpose |
| --- | --- |
| `PROXY_USERNAME` / `PROXY_PASSWORD` | Webshare proxy credentials, used only as a fallback when YouTube blocks direct transcript fetches. |
| `PODCASTSCRAPER_DATA_DIR` | Where episode Markdown and `manifest.json` are written. Default: `~/.local/share/PodcastScraper`. Output lands in a `AI Thinkers podcast data/` subdirectory. |
| `PODCASTSCRAPER_ENV_FILE` | Path to the `.env` file to load. Default: `~/.config/PodcastScraper/.env`, falling back to a `.env` in the working directory. |

Example `~/.config/PodcastScraper/.env`:

```
PROXY_USERNAME=...
PROXY_PASSWORD=...
```

The scraper runs fine without proxy credentials — it just loses the fallback path when a direct transcript fetch fails.

## Running

```bash
python rss_feed.py
```

Progress goes to stdout and to `scraper.log` (gitignored).

## Automation

`.github/workflows/weekly_scrape.yml` runs the scraper every Monday at 07:00 UTC (and on manual `workflow_dispatch`), then commits any changes under `AI Thinkers podcast data/`. `PROXY_USERNAME` and `PROXY_PASSWORD` come from repository secrets. On failure it uploads `scraper.log` and any debug screenshots/HTML as artifacts.

The workflow sets `PODCASTSCRAPER_DATA_DIR: ${{ github.workspace }}` so the scraper writes into the checkout rather than the runner's home directory — without it the commit step would find nothing to stage.

## Maintenance script

`cleanup_data.py` is a one-off repair tool, not part of the normal run. It:

- merges manifest entries whose titles overlap by more than 50% of their words (deduplicating episodes that were recorded under both a YouTube ID and a `substack:` ID), preferring the YouTube ID and the longest non-emoji title;
- deletes `.md` files in the data directory that no longer correspond to a manifest entry (the `מה יש פה בעצם` trailer is exempt).

It deletes files, so review the manifest before running it:

```bash
python cleanup_data.py
```

## Layout

```
config.py                     settings, selectors, env loading
rss_feed.py                   the scraper (PodcastScraper class + entrypoint)
cleanup_data.py               manifest dedupe / orphan-file cleanup
requirements.txt
.github/workflows/            weekly_scrape.yml
AI Thinkers podcast data/     committed episode Markdown + manifest.json
```
