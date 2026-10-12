"""Per-episode automated keyterm glossary.

Every ASR provider in this benchmark accepts a list or prompt of expected terms.
This module builds an automated, production-reproducible glossary using:
1. Episode title (terms, names, and compound phrases)
2. Episode description (technical nouns, acronyms, and multi-word phrases)
3. Outbound links / show-note URLs (repository names, tool slugs, domain identifiers)
4. Domain technical vocabulary (recurring AI engineering, systems, and security concepts)

FAIRNESS RULE:
Never use human-reviewed reference files or listening annotations to build
the model input. The glossary biases recognition at inference time; it is
never used to rewrite output after the fact.
"""

import re
import urllib.parse
from typing import List

# Industry-standard domain vocabulary recurring across AI engineering and software
# podcasts. These terms are established prior knowledge, NOT episode-specific leaks.
BASE_VOCABULARY = [
    # AI models, labs & protocols
    "LLM", "RAG", "MCP", "Model Context Protocol", "agent", "agentic",
    "subagent", "multi-agent", "LangChain", "LangGraph", "LangSmith",
    "LlamaIndex", "Claude", "Claude Code", "ChatGPT", "GPT", "Gemini",
    "OpenAI", "Anthropic", "DeepSeek", "Mistral", "Llama", "vLLM", "Ollama",
    "Hugging Face", "Transformer", "fine-tuning", "embedding", "vector database",
    "prompt", "prompt engineering", "context window", "context compaction",
    "token", "inference", "hallucination", "guardrails", "eval", "evaluation",
    "benchmark", "chunking", "retrieval", "reranking", "tool calling",
    "function calling",

    # Architecture, orchestration & execution
    "orchestration", "workflow", "pipeline", "latency", "throughput",
    "observability", "LLMOps", "production", "deployment", "harness",
    "agent harness", "autonomous agent", "runtime", "daemon", "process",
    "microservices", "gateway", "reverse proxy", "sandbox",

    # Security, identity & cloud infrastructure
    "OAuth", "SSO", "IAM", "credentials", "vault", "credential vault",
    "credential gateway", "supply chain security", "security best practices",
    "access token", "refresh token", "bearer token", "authorization",
    "authentication", "RBAC", "blast radius", "Docker", "Kubernetes",
    "container", "multi-tenant", "single-tenant", "file system",
    "mounted directory", "serverless", "webhook", "API", "SDK", "endpoint",
    "REST API", "GraphQL", "gRPC", "HTTP", "HTTPS", "header", "dependency",
    "open source", "managed service", "hosted version",

    # Developer tools & platforms
    "Git", "GitHub", "code review", "CI", "CD", "CI/CD", "pull request",
    "repository", "Cursor", "Codex", "Copilot", "Google Workspace",
    "Gmail", "Google Calendar", "Google Drive", "Slack",
]

# Stopwords to filter out generic English prose and web boilerplate
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

    # Web, feed, and domain-name boilerplate
    "com", "episode", "html", "http", "https", "join", "listen", "net",
    "org", "podcast", "subscribe", "www", "github", "youtube", "channel",
    "watch", "docs", "io", "dev", "ai", "co", "app", "link", "links",
}

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._+-]{1,}")
_URL_RE = re.compile(r"https?://[^\s)\]<\"']+")


def extract_latin_terms(text: str) -> list:
    """Latin-script tokens from mixed Hebrew/English text, deduped in order."""
    seen = {}
    for token in _LATIN_TOKEN_RE.findall(text or ""):
        stripped = token.strip("._-+")
        if len(stripped) < 2 or stripped.lower() in _STOPWORDS:
            continue
        # Preserve the first-seen casing; "NanoClaw" should not become "nanoclaw".
        seen.setdefault(stripped.lower(), stripped)
    return list(seen.values())


def extract_latin_phrases(text: str, max_words: int = 3) -> list:
    """Multi-word technical phrases within natural clause boundaries.

    Splits on punctuation/delimiters first, then extracts consecutive
    2-to-3 word sequences where neither word is a stopword.
    """
    if not text:
        return []
    # Split on punctuation boundaries so phrases don't span sentences or delimiters
    clauses = re.split(r"[,.:;()\[\]{}|/\"'\\]+|\s+-\s+", text)
    phrases = []
    seen = set()

    for clause in clauses:
        clean = re.sub(r"[^\w\s-]", " ", clause)
        tokens = [w for w in clean.split() if w]
        for n in range(2, max_words + 1):
            for i in range(len(tokens) - n + 1):
                window = tokens[i : i + n]
                if all(
                    re.match(r"^[A-Za-z][A-Za-z0-9-]*$", w)
                    and len(w) >= 2
                    and w.lower() not in _STOPWORDS
                    for w in window
                ):
                    phrase = " ".join(window)
                    key = phrase.lower()
                    if key not in seen:
                        seen.add(key)
                        phrases.append(phrase)
    return phrases


def extract_link_terms(links_or_urls: list) -> list:
    """Extract tool and project names from show-note URLs and outbound links."""
    terms = []
    seen = set()

    def add(term: str):
        cleaned = term.strip("._-+/")
        key = cleaned.lower()
        if (
            cleaned
            and len(cleaned) >= 2
            and key not in seen
            and key not in _STOPWORDS
            and re.match(r"^[A-Za-z][A-Za-z0-9._-]*$", cleaned)
        ):
            seen.add(key)
            terms.append(cleaned)

    for url in links_or_urls or []:
        if not url:
            continue
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname or ""
            path = parsed.path or ""

            # Check GitHub repository links: https://github.com/<owner>/<repo>
            if "github.com" in hostname.lower():
                segments = [s for s in path.split("/") if s]
                if len(segments) >= 2:
                    add(segments[1])  # repo name
                    add(segments[0])  # owner / org
                elif len(segments) == 1:
                    add(segments[0])
            else:
                # Extract domain name without common TLDs
                host_parts = hostname.split(".")
                if len(host_parts) >= 2:
                    domain_slug = host_parts[-2] if host_parts[-1] in (
                        "com", "org", "net", "io", "dev", "ai", "co", "app", "so", "sh"
                    ) else host_parts[0]
                    if domain_slug and domain_slug not in ("www", "feeds", "api"):
                        add(domain_slug)

            # Path segments often contain project names: /kortix-ai/suna
            for seg in path.split("/"):
                seg = seg.strip()
                if seg and not seg.isdigit() and len(seg) > 2:
                    add(seg)
        except Exception:
            continue

    return terms


def build(episode, extra_terms: list = None, limit: int = 400) -> list:
    """Automated, reproducible glossary for an episode.

    Order of priority:
    1. Episode title phrases and tokens (highest specificity)
    2. Episode description phrases and tokens
    3. Outbound show-note links and repository names
    4. Explicit extra terms (if supplied by caller)
    5. Curated domain technical vocabulary
    """
    terms = []
    seen = set()

    def add(term: str):
        if not term:
            return
        key = term.lower()
        if key not in seen:
            seen.add(key)
            terms.append(term)

    # 1. Episode title terms and phrases
    title = getattr(episode, "title", "") or ""
    for term in extract_latin_terms(title):
        add(term)
    for phrase in extract_latin_phrases(title):
        add(phrase)

    # 2. Episode description terms and phrases
    desc = getattr(episode, "description", "") or ""
    for phrase in extract_latin_phrases(desc):
        add(phrase)
    for term in extract_latin_terms(desc):
        add(term)

    # 3. Links from episode object and embedded in description
    links = list(getattr(episode, "links", []) or [])
    if desc:
        links.extend(_URL_RE.findall(desc))
    for term in extract_link_terms(links):
        add(term)

    # 4. Extra terms
    for term in extra_terms or []:
        add(term)

    # 5. Domain technical vocabulary
    for term in BASE_VOCABULARY:
        add(term)

    return terms[:limit]


def for_soniox(episode, limit: int = 400) -> dict:
    """Generate structured context configuration for Soniox STT Async V5 API.

    Soniox accepts:
    - general: structured key-value pairs (domain, topic, podcast)
    - text: clean narrative context from episode description
    - terms: prioritized array of technical vocabulary
    """
    terms = build(episode, limit=limit)
    title = getattr(episode, "title", "") or "LangTalks"
    desc = getattr(episode, "description", "") or ""
    # Strip HTML and raw URLs from description for narrative text
    clean_desc = _URL_RE.sub("", desc)
    clean_desc = re.sub(r"<[^>]+>", " ", clean_desc)
    clean_desc = " ".join(clean_desc.split()).strip()

    return {
        "general": [
            {"key": "domain", "value": "AI software engineering"},
            {"key": "podcast", "value": "LangTalks"},
            {"key": "topic", "value": title},
        ],
        "text": clean_desc or title,
        "terms": terms,
    }


def prompt_for_groq(episode, terms: list = None, max_chars: int = 350) -> str:
    """Generate prompt hint for Groq Whisper within the 224-token context limit.

    Whisper prompts must act as a simulated prior transcript or concise term hint,
    NOT as a repetitive meta-instruction which causes Whisper to repeat prompt
    phrases in silent audio sections.
    """
    all_terms = terms or build(episode)
    # Filter to terms containing Latin characters
    latin_terms = [t for t in all_terms if re.search(r"[A-Za-z]", t)]

    title = getattr(episode, "title", "") or ""
    # Clean leading episode number if present ("71 - Claw Architectures" -> "Claw Architectures")
    title_clean = re.sub(r"^\d+\s*[-:]\s*", "", title).strip()

    prefix = f"LangTalks: {title_clean}. " if title_clean else "LangTalks: "
    included = []
    seen = set()

    for term in latin_terms:
        key = term.lower()
        if key in seen or len(term) > 50:
            continue
        candidate = prefix + ", ".join(included + [term])
        if len(candidate) > max_chars:
            break
        included.append(term)
        seen.add(key)

    return prefix + ", ".join(included) if included else ""


def initial_prompt_for_ivrit(episode, terms: list = None, max_chars: int = 400) -> str:
    """Generate initial_prompt for ivrit.ai Whisper.

    Whisper keeps only the LAST 224 tokens if initial_prompt is too long.
    Keeping the prompt strictly under max_chars (~150-180 tokens) ensures
    the highest-priority episode-specific terms at the beginning are NEVER truncated.
    """
    all_terms = terms or build(episode)
    latin_terms = [t for t in all_terms if re.search(r"[A-Za-z]", t)]

    prefix = "מונחים טכניים באנגלית: "
    included = []
    seen = set()

    for term in latin_terms:
        key = term.lower()
        if key in seen or len(term) > 50:
            continue
        candidate = prefix + ", ".join(included + [term])
        if len(candidate) > max_chars:
            break
        included.append(term)
        seen.add(key)

    return prefix + ", ".join(included) if included else ""


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
