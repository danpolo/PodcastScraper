"""Per-episode keyterm glossary.

Every ASR provider in this benchmark accepts a list of expected terms, and that
list is the main lever on the thing we actually care about: whether English
technical terms survive as English. The glossary biases recognition — it is
never used to rewrite output after the fact.
"""

import re

# Vocabulary that recurs across LangTalks regardless of the episode. Keep this
# list short and high-precision; providers cap the number of keyterms, and a
# term that is not really in the audio can pull recognition toward it.
BASE_VOCABULARY = [
    "LLM", "RAG", "MCP", "Model Context Protocol", "agent", "agentic",
    "LangChain", "LangGraph", "LangSmith", "Claude", "Claude Code", "ChatGPT",
    "GPT", "Gemini", "OpenAI", "Anthropic", "embedding", "vector database",
    "fine-tuning", "prompt", "prompt engineering", "context window",
    "context compaction", "token", "inference", "hallucination", "guardrails",
    "evaluation", "eval", "benchmark", "chunking", "retrieval", "reranking",
    "tool calling", "function calling", "subagent", "orchestration",
    "workflow", "pipeline", "latency", "throughput", "observability",
    "LLMOps", "production", "deployment", "API", "SDK", "endpoint",
    "repository", "pull request", "code review", "CI", "CD", "Git", "GitHub",
    "Docker", "Kubernetes", "serverless", "webhook", "OAuth", "Cursor",
]

# Show-note prose contributes ordinary English words that look like terms to a
# tokenizer. Passing "into" or "deep" as a keyterm is not merely useless — it
# biases recognition toward a word the speaker probably did not say. Technical
# nouns are deliberately absent from this list even when common ("model",
# "agent", "token"), because in this podcast they are load-bearing.
_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am",
    "an", "and", "any", "are", "as", "at", "back", "be", "because", "been",
    "before", "behind", "being", "below", "best", "better", "between", "big",
    "both", "build", "but", "by", "can", "come", "could", "day", "deep",
    "did", "differently", "dive", "do", "does", "doing", "done", "down",
    "during", "each", "even", "every", "few", "first", "for", "from",
    "further", "get", "give", "go", "good", "great", "had", "has", "have",
    "having", "he", "her", "here", "hers", "him", "his", "how", "however",
    "i", "if", "in", "inside", "into", "is", "it", "its", "just", "know",
    "last", "learn", "less", "let", "like", "long", "look", "made", "make",
    "many", "may", "me", "might", "more", "most", "much", "must", "my",
    "need", "never", "new", "next", "no", "not", "now", "of", "off", "on",
    "once", "one", "only", "or", "other", "our", "ours", "out", "over",
    "own", "part", "really", "right", "said", "same", "say", "see", "she",
    "should", "so", "some", "still", "such", "take", "talk", "than", "that",
    "the", "their", "theirs", "them", "then", "there", "these", "they",
    "thing", "things", "think", "this", "those", "through", "time", "to",
    "today", "too", "two", "under", "until", "up", "us", "use", "used",
    "using", "very", "want", "was", "way", "we", "well", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "will", "with",
    "without", "work", "would", "year", "you", "your", "yours",
    # Boilerplate that shows up in feed metadata rather than in speech.
    "com", "episode", "html", "http", "https", "join", "listen", "net",
    "org", "podcast", "subscribe", "www",
}

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._+-]{1,}")


def extract_latin_terms(text: str) -> list:
    """Latin-script tokens from mixed Hebrew/English text, deduped in order."""
    seen = {}
    for token in _LATIN_TOKEN_RE.findall(text or ""):
        stripped = token.strip("._-+")
        if len(stripped) < 2 or stripped.lower() in _STOPWORDS:
            continue
        # Preserve the first-seen casing; "MCP" should not become "mcp".
        seen.setdefault(stripped.lower(), stripped)
    return list(seen.values())


def build(episode, extra_terms=None, limit: int = 400) -> list:
    """Glossary for one episode: title and show-note terms first, then base.

    Episode-specific terms come first because they are the ones a generic model
    is least likely to get right — guest names, company names and whatever tool
    the episode is actually about.
    """
    terms = []
    seen = set()

    def add(term):
        key = term.lower()
        if key not in seen and term:
            seen.add(key)
            terms.append(term)

    for term in extract_latin_terms(episode.title):
        add(term)
    for term in extract_latin_terms(episode.description):
        add(term)
    for term in extra_terms or []:
        add(term)
    for term in BASE_VOCABULARY:
        add(term)

    return terms[:limit]


def context_prompt(episode, terms) -> str:
    """Free-text prompt for providers that take prose rather than a term list."""
    return (
        "This is LangTalks, a Hebrew-language technical podcast about LLMs, AI "
        "agents and applied AI engineering. The speakers are Israeli engineers "
        "who speak Hebrew but keep technical terms, product names, model names, "
        "API names and acronyms in English. Transcribe Hebrew speech in Hebrew "
        "script and keep every English term in Latin script — never transliterate "
        "an English technical term into Hebrew letters.\n\n"
        f"Episode: {episode.title}\n\n"
        f"Expected terms: {', '.join(terms[:120])}"
    )
