"""Real Chromium smoke test for tools/reference-review.html (offline).

Runs in a separate UI workflow because unit-test CI does not install Chromium.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PAGE = (ROOT / "tools/reference-review.html").as_uri()


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        page.goto(PAGE)
        proposal = {
            "episode_guid": "test-episode",
            "episode_title": "Hebrew / English example",
            "window": {"start": 480, "end": 780},
            "suggested_terms": [
                {
                    "term": "Nano-Claw",
                    "seen_in": ["local_whisper", "local_ivrit"],
                    "occurrences": [
                        {"start": 494.1, "end": 495.4,
                         "sources": ["local_whisper", "local_ivrit"],
                         "text": "Nano-Claw"},
                    ],
                },
            ],
        }
        page.locator("#proposal").set_input_files({
            "name": "proposal.json",
            "mimeType": "application/json",
            "buffer": json.dumps(proposal).encode(),
        })
        assert "Hebrew / English" in page.locator("#episodeTitle").inner_text()
        assert page.locator(".occ").count() == 1
        assert "8:14" in page.locator(".seek").first.inner_text()

        page.locator("#editTerm").fill("NanoClaw")
        page.locator("#applyTerm").click()
        assert page.locator("#terms").get_by_text("NanoClaw").count() > 0
        page.locator(".occ input[type=checkbox]").check()

        page.locator("#newTerm").fill("LangGraph")
        page.locator("#newTime").fill("09:01")
        page.locator("#addTerm").click()
        assert page.locator("#terms").get_by_text("LangGraph").count() > 0
        assert "2 / 2 reviewed" in page.locator("#counts").inner_text()

        page.locator("#listened").check()
        with page.expect_download() as download_info:
            page.locator("#exportRef").click()
        download = download_info.value
        path = download.path()
        out = json.loads(Path(path).read_text())
        assert out["review_status"] == "approved", out
        assert out["terms_exhaustive"] is True
        assert set(out["technical_terms"]) == {"NanoClaw", "LangGraph"}
        assert len(out["verified_occurrences"]) == 2

        page.locator("#listened").uncheck()
        with page.expect_download() as download_info:
            page.locator("#exportRef").click()
        out = json.loads(Path(download_info.value.path()).read_text())
        assert out["review_status"] == "pending"

        with page.expect_download() as download_info:
            page.locator("#exportSession").click()
        session = json.loads(Path(download_info.value.path()).read_text())
        assert session["review_session"]
        assert session["term_groups"][0]["occurrences"][0]["state"] == "confirmed"
        browser.close()
    print("UI_SMOKE_TEST: PASSED (terms, timestamps, approval, export, save)")


if __name__ == "__main__":
    run()
