from pathlib import Path

# --- General Settings ---
YOUTUBE_CHANNEL_VIDEOS_URL = 'https://www.youtube.com/@AITHINKER_S/videos'
APPLE_PODCASTS_URL = 'https://podcasts.apple.com/il/podcast/ai-thinkers/id1848575796'
SPOTIFY_URL = 'https://open.spotify.com/show/5qXP9dnucaWoHe6VMB56wc'
STORAGE_STATE_PATH = "auth.json"
OUTPUT_DIR = Path("AI Thinkers podcast data")
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
CONCURRENCY_LIMIT = 2

# --- Playwright Settings ---
# Resources to block to speed up loading
BLOCKED_RESOURCE_TYPES = ["image", "font"]

# --- Selectors ---
SUBSTACK_DESC_SELECTOR = ".available-content"
SUBSTACK_TRANSCRIPT_BTN_TEXT = "Transcript"
SUBSTACK_TRANSCRIPT_SELECTOR = ".transcription-full-body-container-LXFSNv"
SPOTIFY_TRANSCRIPT_BTN = '[data-testid="transcript-tab"]'
SPOTIFY_DESC_SELECTOR = '[data-testid="episode-description"], [class*="Description"], .episode-description'
CLICK_TIMEOUT = 30000

# --- Markers & Filtering ---
TRANSCRIPT_START_MARKER = "This transcript was generated automatically. Its accuracy may vary."
TRANSCRIPT_END_MARKER = "More episodes like this"
AVOID_PHRASES = ["דובר או דוברת מס"]
