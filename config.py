from pathlib import Path

# --- General Settings ---
ARCHIVE_API_URL = 'https://aithinkers.substack.com/api/v1/archive?sort=new&search=&offset=0&limit=12'
PODCAST_PAGE_URL = 'https://aithinkers.substack.com/podcast'
STORAGE_STATE_PATH = "auth.json"
OUTPUT_DIR = Path("AI Thinkers podcast data")
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
CONCURRENCY_LIMIT = 3

# --- Playwright Settings ---
# Resources to block to speed up loading
BLOCKED_RESOURCE_TYPES = ["image", "font"]

# --- Selectors ---
SUBSTACK_DESC_SELECTOR = ".available-content"
SUBSTACK_TRANSCRIPT_BTN_TEXT = "Transcript"
SUBSTACK_TRANSCRIPT_SELECTOR = ".transcription-full-body-container-LXFSNv"
SPOTIFY_TRANSCRIPT_BTN = '[data-testid="transcript-tab"]'
CLICK_TIMEOUT = 30000

# --- Markers & Filtering ---
TRANSCRIPT_START_MARKER = "This transcript was generated automatically. Its accuracy may vary."
TRANSCRIPT_END_MARKER = "More episodes like this"
AVOID_PHRASES = ["דובר או דוברת מס"]
