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

        asr_context = {
            "schema_version": "1.0", "turns": [{
                "id": "turn-0001", "start_s": 480, "end_s": 510,
                "speaker_id": None, "text": "בפרק הזה אנחנו משתמשים ב-NanoClaw",
            }],
        }
        page.locator("#asrTranscriptFile").set_input_files({
            "name": "transcript.json", "mimeType": "application/json",
            "buffer": json.dumps(asr_context, ensure_ascii=False).encode(),
        })
        assert "NanoClaw" in page.locator("#nearbyTranscript").inner_text()
        page.locator("#editSurface").fill("Nano-Claw")
        page.locator("#editTerm").fill("NanoClaw")
        page.locator("#conceptKind").select_option("product")
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
        assert out["concept_mentions"][0]["surface"] == "Nano-Claw"
        assert out["concept_mentions"][0]["canonical"] == "NanoClaw"
        assert out["concept_mentions"][0]["kind"] == "product"

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
        # Split and merge remain manual and do not silently approve a phrase.
        page.reload()
        compound = {
            "episode_guid": "compound-test", "window": {"start": 480, "end": 780},
            "suggested_terms": [
                {"term": "code", "occurrences": [{"start": 489.4, "end": 489.58,
                    "text": "code", "sources": ["model-a"]}]},
                {"term": "review", "occurrences": [{"start": 489.58, "end": 489.86,
                    "text": "review", "sources": ["model-b"]}]},
            ],
        }
        page.locator("#proposal").set_input_files({
            "name": "compound.json", "mimeType": "application/json",
            "buffer": json.dumps(compound).encode(),
        })
        page.locator("#terms input[type=checkbox]").nth(0).check()
        page.locator("#terms input[type=checkbox]").nth(1).check()
        page.locator("#mergeSelected").click()
        assert page.locator("#editSurface").input_value() == "code review"
        assert page.locator("#counts").inner_text() == "0 / 1 reviewed"
        page.locator("#splitTerm").click()
        assert page.locator("#terms .term-item").count() == 2
        assert page.locator("#counts").inner_text() == "0 / 2 reviewed"
        browser.close()
    print("UI_SMOKE_TEST: PASSED (terms, timestamps, approval, export, save)")


if __name__ == "__main__":
    run()
