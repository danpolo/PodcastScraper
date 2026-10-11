"""LangTalks ingestion and ASR benchmarking.

LangTalks is a Hebrew podcast about AI agents whose value is concentrated in
the English technical terms embedded in Hebrew speech. That makes it a
different problem from AI Thinkers, where YouTube captions were good enough:
there is no usable caption track here, and Hebrew ASR transliterates exactly
the words worth keeping.

This package therefore starts with a benchmark rather than a pipeline — pick
the transcription backend on measured technical-term recall, then build.
"""
