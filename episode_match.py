"""Conservative Spotify/YouTube episode identity reconciliation.

Spotify's episode index and YouTube's recent-video RSS have unrelated ordering,
different coverage and extra Shorts. Never pair entries by list index.

A match is accepted only if:
 - both platforms provide meaningful titles,
 - their normalized titles agree closely,
 - both sides select each other uniquely,
 - the best candidate has a safe margin over the runner-up.
Ambiguity is reported; the scraper keeps its existing YouTube notes instead of
silently attaching the wrong Spotify description.
"""
from difflib import SequenceMatcher
import re
import unicodedata

TITLE_THRESHOLD = 0.91
AMBIGUITY_MARGIN = 0.07

def normalized_title(title: str) -> str:
    """Keep Hebrew, English and digits; remove accents/punctuation/noise."""
    title = unicodedata.normalize("NFKC", str(title or "")).casefold()
    title = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "", title)
    title = re.sub(r"[^\w]+", " ", title, flags=re.UNICODE)
    return " ".join(title.split())


def similarity(a: str, b: str) -> float:
    a, b = normalized_title(a), normalized_title(b)
    if len(a) < 8 or len(b) < 8:
        return 0.0
    if a == b:
        return 1.0
    # Reject containment shortcuts: different 'part 1/2' suffixes can
    # represent different episodes, as can extended vs teaser versions.
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def match_spotify_entries(youtube_entries, spotify_entries):
    """Return video ID -> Spotify URL matches, plus diagnostics.

    spotify_entries: [{"id": ..., "title": ..., "url": ...}, ...].
    Unknown titles or duplicate URLs are *not* grounds to guess an identity.
    """
    yt = list(youtube_entries)
    sp = list(spotify_entries)
    out = {}
    diagnostics = {
        "youtube_count": len(yt),
        "spotify_count": len(sp),
        "matched": 0,
        "unmatched_youtube": [],
        "unmatched_spotify": [],
        "ambiguous_youtube": [],
        "reason": "conservative_title_mutual_best",
    }
    if not yt or not sp:
        diagnostics["unmatched_youtube"] = [x.id for x in yt]
        diagnostics["unmatched_spotify"] = [x.get("id", x.get("url")) for x in sp]
        return out, diagnostics

    scores = [[similarity(entry.title, item.get("title", ""))
               for item in sp] for entry in yt]
    sorted_y = [sorted(enumerate(row), key=lambda pair: pair[1], reverse=True)
                for row in scores]
    sorted_s = [
        sorted(((yi, scores[yi][sj]) for yi in range(len(yt))),
               key=lambda pair: pair[1], reverse=True)
        for sj in range(len(sp))
    ]
    urls_used = set()
    for yi, entry in enumerate(yt):
        candidates = sorted_y[yi]
        if not candidates:
            diagnostics["unmatched_youtube"].append(entry.id)
            continue
        sj, highest = candidates[0]
        runner = candidates[1][1] if len(candidates) > 1 else 0.0
        other_best, spotify_highest = sorted_s[sj][0]
        other_runner = sorted_s[sj][1][1] if len(sorted_s[sj]) > 1 else 0.0
        url = str(sp[sj].get("url") or "")
        safe_url = url.startswith("https://open.spotify.com/episode/") or \
            url.startswith("https://open.spotify.com/embed/episode/")
        sure = (
            highest >= TITLE_THRESHOLD
            and highest - runner >= AMBIGUITY_MARGIN
            and other_best == yi
            and spotify_highest - other_runner >= AMBIGUITY_MARGIN
            and safe_url and url not in urls_used
        )
        if sure:
            out[entry.id] = url
            urls_used.add(url)
        elif highest >= TITLE_THRESHOLD:
            diagnostics["ambiguous_youtube"].append({
                "id": entry.id, "title": entry.title,
                "spotify_candidate": sp[sj].get("title"),
                "score": round(highest, 3),
                "runner_up_score": round(runner, 3),
            })
        else:
            diagnostics["unmatched_youtube"].append(entry.id)
    matched_urls = set(out.values())
    diagnostics["matched"] = len(out)
    diagnostics["unmatched_spotify"] = [
        x.get("id") or x.get("url")
        for x in sp if x.get("url") not in matched_urls
    ]
    return out, diagnostics
