"""Unit tests for automated, fair glossary generation.

Enforces:
1. Production reproducibility purely from Episode metadata (title, description, links)
   and standard domain vocabulary.
2. Zero leakage or dependency on human-reviewed reference files.
3. Proper adaptation to provider-specific constraints (Soniox, Groq, ivrit.ai).
"""
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from langtalks import glossary


@dataclass
class DummyEpisode:
    title: str
    description: str
    guid: str = "dummy-guid-1234"
    published: str = "2026-01-01"
    audio_url: str = "https://example.com/audio.mp3"
    duration_seconds: int = 1800
    links: List[str] = field(default_factory=list)


class FairGlossaryTests(unittest.TestCase):
    def setUp(self):
        self.ep71 = DummyEpisode(
            title="71 - Claw Architectures | Gavriel Cohen (NanoClaw)",
            description=(
                "A deep dive into the architecture and security model behind "
                "autonomous agent harnesses - isolation, credential gateways, "
                "and skill-based extensibility."
            ),
            links=[],
        )
        self.ep52 = DummyEpisode(
            title="52 - Agents at scale | Adam Cohen Hillel",
            description="Discussing Suna, an open source agent framework.",
            links=["https://github.com/kortix-ai/suna", "https://suna.so/docs"],
        )

    def test_never_imports_or_reads_reference_files(self):
        """Glossary generator must never import or read from reference files."""
        import inspect
        source = inspect.getsource(glossary)
        # Check imports and file access
        self.assertNotIn("import reference", source.lower())
        self.assertNotIn("from .reference", source.lower())
        self.assertNotIn("from . import reference", source.lower())
        self.assertNotIn("REFERENCE_DIR", source)
        self.assertNotIn("verified_occurrences", source)

    def test_title_and_description_terms_extracted_with_casing(self):
        terms = glossary.build(self.ep71)
        # Episode-specific terms must be at the very front
        self.assertIn("NanoClaw", terms[:10])
        self.assertIn("Claw", terms[:10])
        # Multi-word phrase or compound terms from description
        self.assertTrue(
            any("credential gateway" in t.lower() or "gateways" in t.lower() for t in terms)
        )
        self.assertTrue(
            any("agent harness" in t.lower() or "harnesses" in t.lower() for t in terms)
        )
        self.assertTrue(
            any("extensibility" in t.lower() for t in terms)
        )

    def test_link_terms_extracted(self):
        link_terms = glossary.extract_link_terms(self.ep52.links)
        # Suna and kortix-ai from GitHub URL
        self.assertTrue(any("suna" in t.lower() for t in link_terms))
        self.assertTrue(any("kortix-ai" in t.lower() or "kortix" in t.lower() for t in link_terms))
        # Web boilerplate must be excluded
        for stop in ["https", "github", "com", "docs", "http"]:
            self.assertNotIn(stop, [t.lower() for t in link_terms])

    def test_stopwords_and_generic_prose_filtered(self):
        terms = glossary.build(self.ep71)
        for stop in ["into", "deep", "behind", "and", "the", "a"]:
            self.assertNotIn(stop, [t.lower() for t in terms])

    def test_soniox_structured_context(self):
        ctx = glossary.for_soniox(self.ep71)
        self.assertIn("general", ctx)
        self.assertIn("text", ctx)
        self.assertIn("terms", ctx)
        self.assertIsInstance(ctx["general"], list)
        self.assertTrue(any(g.get("key") == "domain" for g in ctx["general"]))
        self.assertIn("NanoClaw", ctx["terms"][:10])
        self.assertIn("autonomous agent", ctx["text"].lower())

    def test_groq_prompt_adaptation_bounds_and_avoids_repetition(self):
        prompt = glossary.prompt_for_groq(self.ep71, max_chars=300)
        self.assertLessEqual(len(prompt), 300)
        self.assertIn("NanoClaw", prompt)
        # Must not contain repeating instructions that cause Whisper hallucination loops
        self.assertNotIn("פודקאסט בעברית על AI ותוכנה. מונחים באנגלית:", prompt)

    def test_ivrit_initial_prompt_prioritizes_episode_terms(self):
        prompt = glossary.initial_prompt_for_ivrit(self.ep71, max_chars=400)
        self.assertLessEqual(len(prompt), 400)
        # Episode-specific terms must appear before generic vocabulary
        idx_nanoclaw = prompt.find("NanoClaw")
        idx_llm = prompt.find("LLM")
        self.assertNotEqual(idx_nanoclaw, -1)
        if idx_llm != -1:
            self.assertLess(idx_nanoclaw, idx_llm)


if __name__ == "__main__":
    unittest.main()
