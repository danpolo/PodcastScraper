"""Strict, offline episode identity tests: fail closed over wrong metadata."""
from types import SimpleNamespace
import unittest

from episode_match import match_spotify_entries, normalized_title, similarity


def yt(ident, title):
    return SimpleNamespace(id=ident, title=title)


def sp(ident, title):
    return {"id": ident, "title": title,
            "url": "https://open.spotify.com/episode/" + ident}


class IdentityMatchingTests(unittest.TestCase):
    def test_shuffled_platform_lists_do_not_change_mapping(self):
        youtube = [
            yt("y1", "איך לתת אמון בסוכן ה AI שלך?"),
            yt("y2", "טייסט: הסקיל שאף אחד לא מלמד מנהלי מוצר"),
            yt("y3", "מדידת AI בפיתוח: למה יותר קוד לא שווה יותר תוצאות"),
        ]
        spotify = [
            sp("sp3", "מדידת AI בפיתוח: למה יותר קוד לא שווה יותר תוצאות"),
            sp("sp1", "איך לתת אמון בסוכן ה AI שלך?"),
            sp("sp2", "טייסט: הסקיל שאף אחד לא מלמד מנהלי מוצר"),
        ]
        got, diag = match_spotify_entries(youtube, spotify)
        self.assertEqual(got, {
            "y1": "https://open.spotify.com/episode/sp1",
            "y2": "https://open.spotify.com/episode/sp2",
            "y3": "https://open.spotify.com/episode/sp3",
        })
        self.assertEqual(diag["matched"], 3)
        again, _ = match_spotify_entries(list(reversed(youtube)), list(reversed(spotify)))
        self.assertEqual(got, again)

    def test_mismatched_coverage_fails_closed_and_does_not_shift(self):
        youtube = [
            yt("short", "Stop Chasing Every AI Hype #shorts"),
            yt("episode", "האמנות למחוק: על טעם, אג'נטים ושיטות עבודה עם AI"),
        ]
        spotify = [sp("sp1", "האמנות למחוק: על טעם, אג'נטים ושיטות עבודה עם AI")]
        got, diag = match_spotify_entries(youtube, spotify)
        self.assertEqual(got, {"episode": "https://open.spotify.com/episode/sp1"})
        self.assertIn("short", diag["unmatched_youtube"])

    def test_duplicate_titles_are_ambiguous_not_auto_merged(self):
        youtube = [yt("video", "איך בונים סוכן AI")]
        spotify = [sp("sp1", "איך בונים סוכן AI"),
                   sp("sp2", "איך בונים סוכן AI")]
        matches, diag = match_spotify_entries(youtube, spotify)
        self.assertEqual(matches, {})
        self.assertEqual(len(diag["ambiguous_youtube"]), 1)

    def test_duplicate_youtube_titles_are_ambiguous(self):
        youtube = [yt("one", "אבטחת סוכני AI"),
                   yt("two", "אבטחת סוכני AI")]
        spotify = [sp("sp1", "אבטחת סוכני AI")]
        matches, diag = match_spotify_entries(youtube, spotify)
        self.assertEqual(matches, {})
        self.assertEqual(len(diag["ambiguous_youtube"]), 2)

    def test_no_title_never_uses_positional_guessing(self):
        matches, diag = match_spotify_entries(
            [yt("youtube-a", "Managing secrets in AI agents")],
            [sp("sp-a", "")],
        )
        self.assertEqual(matches, {})
        self.assertEqual(diag["matched"], 0)

    def test_substantial_title_change_requires_manual_review(self):
        matches, diag = match_spotify_entries(
            [yt("youtube", "איך בונים סוכן AI שמנהל עסק")],
            [sp("sp", "שלושה כללים לאבטחת ארגונים בעולם AI")],
        )
        self.assertEqual(matches, {})
        self.assertEqual(diag["unmatched_youtube"], ["youtube"])

    def test_unsafe_url_and_short_uninformative_titles_are_rejected(self):
        matches, _ = match_spotify_entries(
            [yt("v1", "One")],
            [{"id": "sp1", "title": "One", "url": "https://invalid.example/episode/sp1"}],
        )
        self.assertEqual(matches, {})
        matches, _ = match_spotify_entries(
            [yt("v2", "Managing agent credentials")],
            [{"id": "sp2", "title": "Managing agent credentials",
              "url": "https://example.com/episode/sp2"}],
        )
        self.assertEqual(matches, {})

    def test_normalization_keeps_hebrew_and_english_not_remove_content(self):
        self.assertEqual(normalized_title('  "קוד-review: AI?" '), "קוד review ai")
        self.assertEqual(similarity("קוד review: AI", "קוד review AI"), 1.0)
        self.assertLess(similarity("Episode part 1 extended", "Episode part 2"), 0.91)


if __name__ == "__main__":
    unittest.main()
