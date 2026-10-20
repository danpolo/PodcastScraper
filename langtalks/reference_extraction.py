"""Extract proposed ground-truth technical terminology reference from user-corrected SRT.

Prepares Dataset C candidate proposals by:
1. Discovering Latin technical terms, products, tools, protocols, acronyms, and compounds.
2. Identifying Hebrewized technical terms and linking them cross-script to canonical English concepts (e.g., ההרנס -> harness).
3. Handling Hebrew prefixes (ו, ב, ל, מ, ה, ש, כ), transliterations, and mixed expressions.
4. Preserving verbatim spoken/written surfaces separate from semantic canonical identities.
5. Performing context-aware semantic discovery where multi-word compounds and specific canonical
   identities take precedence over broad generic parent concepts (e.g. AGENTS.md, Subagent,
   Agentic search, Agent harness are not subsumed under AI agent).
6. Inferring precise word-level timestamps from machine tokens when aligned, marking precision.
7. Preserving candidate provenance from Dataset B and flagging uncertainties.
8. Reconciling with Dataset A (pre-ASR glossary) and Dataset B (machine detected) for suggested missing terms.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

try:
    from .import_reviewed_srt import parse_srt
except ImportError:
    from langtalks.import_reviewed_srt import parse_srt


# Canonical Concept Definitions with patterns, kinds, priorities, and cross-script metadata
LEXICON = [
    # --- Products & Projects ---
    {
        "canonical": "Jev",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Jev(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ג['׳״]?ב(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ג['׳״]?אב(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Primary subject of episode: Jev classification model.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Jev Piano",
        "kind": "product",
        "priority": 15,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Jev\s+Piano(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ג['׳״]?ב\s+Piano(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Community project built on Jev.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "LangTalks",
        "kind": "organization",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?LangTalks(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?LankTox(?:\.AI)?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Podcast name and community URL.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Claude Code",
        "kind": "product",
        "priority": 15,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Claude\s+Code(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Anthropic coding agent product.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Claude Haiku",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Claude\s+Haiku(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?הייקו(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Anthropic Claude Haiku compact model; Hebrew phonetics הייקו.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Claude",
        "kind": "product",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Claude(?!\s+Code)(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Anthropic model family.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "ChatGPT",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ChatGPT(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?JetGPT(?![A-Za-z0-9])",
        ],
        "editorial_reason": "OpenAI conversational product.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "GPT",
        "kind": "product",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?gpt(?:\s+5\.6)?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?GPT(?![A-Za-z0-9])",
        ],
        "editorial_reason": "OpenAI model reference (gpt 5.6).",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Gemini Flash",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ג['׳״]?מיני\s+Flash(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Flash(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Google Gemini Flash model reference.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Notion",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Notion(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Product workspace tool used in examples.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Slack",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?סלק(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Slack(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Slack messaging platform used in event stream classification example.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "RoBERTa",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?רוברטה(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?RoBERTa(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Meta RoBERTa transformer classifier model; Hebrew phonetics רוברטה.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "DeBERTa",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?דיברט(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?DeBERTa(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Microsoft DeBERTa transformer classifier model; Hebrew phonetics דיברט.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Hugging Face Spaces",
        "kind": "product",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?(?:הגיד|האגינג)\s+פייס(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?ה?ספייסים(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Hugging\s+Face(?:\s+Spaces)?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Hugging Face Spaces platform; spoken as מהגיד פייס / ספייסים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "AGENTS.md",
        "kind": "tool",
        "priority": 15,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?(?:א[י]*ג['׳״]?נטס|agents?)\s*(?:\.|\s+)MD(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Configuration instruction file for AI agents (AGENTS.md); spoken phonetically in Hebrew (באג'נטס MD / האג'נטס MD / ב-agents MD).",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },

    # --- Agent Architecture & Components ---
    {
        "canonical": "Agent harness",
        "kind": "technical_concept",
        "priority": 15,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?agent\s+harness(?:es)?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?א[י]*ג['׳״]?נט\s+ה?הרנס(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Execution harness runtime environment specifically tailored for AI agents.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "harness",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?harness(?:es)?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?ה?הרנס(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?בארנס(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Execution harness runtime; cross-script Hebrewized ההרנס/בארנס mapped to harness.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Subagent",
        "kind": "technical_concept",
        "priority": 12,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?סאב[\s-]*א[י]*ג['׳״]?נט(?:ים)?(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?sub-?agents?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Subagent architecture in multi-agent orchestration; Hebrewized loanword סאב אייג'נט.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Agentic search",
        "kind": "technical_practice",
        "priority": 12,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?א[י]*ג['׳״]?נטיק\s+ס[א]?ר[ץצ]['׳״]?(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?agentic\s+search(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Autonomous agentic search practice; Hebrewized איג'נטיק סארץ' / האג'נטיק סרצ'.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "AI agent",
        "kind": "technical_concept",
        "priority": 2,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?agents?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?(?:ה|ש|כ|ל|ב|מ)?א[י]*ג['׳״]?נט(?:ים|ס|יות|ית|יים|י|יק)?(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Autonomous AI agent; common Hebrewized loanword (when not part of a specific compound).",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Hook",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?הוק(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?hooks?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Agent callback hook in execution harness; Hebrew loanword הוק.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Skill",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?סקיל(?:ים)?(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?skills?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Agent skill capability definition; Hebrew loanword סקיל.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Feedback",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?פידבק(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?feedback(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Agent feedback loop; Hebrew loanword פידבק.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Event",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?איבנט(?:ים)?(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?events?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Event trigger in agent event loops; Hebrew loanword איבנט / איבנטים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },

    # --- Classification & Model Types ---
    {
        "canonical": "Zero-shot classifier",
        "kind": "technical_concept",
        "priority": 12,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?Zero-shot\s+Classifiers?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?Zero-shot(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?ז[י]?רו[\s-]*שוט\s+קלאסיפייר(?:ס|ים|י)?(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Zero-shot classification model category; includes Hebrewized זירושוט קלאסיפיירס / הזירושוט קלאסיפיירים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "classification model",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכה]{1,3}-?)?מודל\s+ק(?:לא|ל)סיפיקציה(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?classification\s+models?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Dedicated classification model entity (distinct from generic classification task).",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "classifier",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?classifiers?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכה]{1,3}-?)?קלאסיפייר(?:ים|ס)?(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Machine learning classifier model; includes Hebrewized קלאסיפיירים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "classification",
        "kind": "technical_concept",
        "priority": 3,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכה]{1,3}-?)?ק(?:לא|ל)סיפיקצי(?:ה|ות)(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?קלאסיפיקיישן(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?classification(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Classification task / inference.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },

    # --- RAG & Data Operations ---
    {
        "canonical": "Chunking",
        "kind": "technical_practice",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?צ['׳״]?אנקינג(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?chunking(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Text chunking and segmentation practice in RAG/retrieval; Hebrew transliteration צ'אנקינג.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Filtering",
        "kind": "technical_practice",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?פילטור(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?filtering(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Data filtering stage in RAG and search workflows; Hebrew transliteration פילטור.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Feature extraction",
        "kind": "technical_practice",
        "priority": 7,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?חילוץ\s+(?:של\s+)?פיצ['׳״]?רים(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?פיצ['׳״]?רים(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?feature\s+extraction(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Feature extraction from text; Hebrew loanword פיצ'רים / חילוץ פיצ'רים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Lost in the Middle",
        "kind": "technical_concept",
        "priority": 12,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?lost\s+in\s+the\s+middle(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Known LLM context retrieval degradation phenomenon (Lost in the Middle).",
        "uncertainty_flag": False,
    },

    # --- System Architecture & Mechanics ---
    {
        "canonical": "Reasoning",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?ר[י]?זנינג(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?reasoning(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Model reasoning capabilities / reasoning tokens; Hebrew loanword ריזנינג.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Fallback",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?פולבק(?:ים)?(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?fallbacks?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Architectural fallback strategy; Hebrewized loanword פולבק / פולבקים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Input",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכה]{1,3}-?)?אינפוט(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?input(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Model input tokens and context feeding; Hebrew loanword אינפוט.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Output",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכה]{1,3}-?)?אאוטפוט(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?output(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Model output tokens and generation; Hebrew loanword אאוטפוט.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Schema",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?סכמה(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?schemas?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Model output schema definition; Hebrewized transliteration סכמה.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Parameters",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?פרמטרים(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?parameters?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Configuration parameters in structured model inputs/outputs; פרמטרים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Pre-training",
        "kind": "technical_practice",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?ה?פרי[\s-]*טריין(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?pre-?training(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Foundation model pre-training phase; Hebrew loanword הפרי-טריין.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Reliability",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?רלבילי(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?reliability(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Production system reliability metric; colloquial loanword רלבילי.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Autonomous driving",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכה]{1,3}-?)?נהיגה\s+ה?אוטונומית(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?autonomous\s+driving(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Autonomous driving domain use case mentioned in classification comparisons.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Closed source",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?closed\s+source(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Proprietary / closed source model architecture.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Safe to merge",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?safe\s+to\s+merge(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Automated PR merge decision label (safe to merge).",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Silver bullet",
        "kind": "descriptive_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?סילבר\s+בולט(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?silver\s+bullet(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Silver bullet software metaphor; Hebrewized transliteration סילבר בולט.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Bulk operations",
        "kind": "technical_practice",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכה]{1,3}-?)?באלק(?:\s+אופריישנס)?(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?bulk(?:\s+operations?)?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Batch / bulk processing operations; Hebrewized transliteration באלק (אופריישנס).",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Configuration",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?קונפיגורצי(?:ה|ות)(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?configuration(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Model configuration parameter; Hebrew transliteration קונפיגורציה.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Timestamps",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?טיימסטפ(?:ים)?(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?timestamps?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Token timestamp markers in model generation; Hebrew loanword טיימסטפים.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Probability",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?-?pobability(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?|ה-?)?probability(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Classification prediction probability; note ASR typo in cue 118 '-pobability'.",
        "uncertainty_flag": False,
    },

    # --- Core Architectures & Technologies ---
    {
        "canonical": "LLM",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?LLM(?:ים)?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?מללם(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Large Language Model; ubiquitous baseline comparison.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "RAG",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?RAG(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Retrieval-Augmented Generation architecture.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "SDLC",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?SDLC(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Software Development Life Cycle.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "DOM",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?DOM\s+elements(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?DOM(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Document Object Model elements for web agent interaction.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "HTML",
        "kind": "protocol",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?HTML(?![A-Za-z0-9])",
        ],
        "editorial_reason": "HyperText Markup Language standard.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "tool calling",
        "kind": "technical_practice",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?tool\s+calling(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Function / tool calling mechanism in agents.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "vector database",
        "kind": "tool",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?vector\s+database(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Vector database storage for embeddings.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "embeddings",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ה?אמבדינגס(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?embeddings?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Vector representation embeddings; Hebrewized loanword.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "loss function",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ה?לוס\s+פונקשן(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?loss\s+function(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Machine learning loss function; transliterated Hebrew phrasing.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "guardrails",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?גארד\s+רייל(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?guardrails?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Agent safety guardrails; Hebrew transliteration.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "reinforcement learning",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?reinforcement\s+learning(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Machine learning optimization method.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "time series",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?time\s+series(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Sequential data series.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "TypeSafe",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Type-safe(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?TypeSafe(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Type-safety constraint in Jev schema questions.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "system prompt",
        "kind": "technical_concept",
        "priority": 10,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?system\s+prompt(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?System\s+prompt(?![A-Za-z0-9])",
        ],
        "editorial_reason": "LLM instructions context / system prompt.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "context window",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?קונטקסט\s+ווינדוס(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?context\s+window(?![A-Za-z0-9])",
        ],
        "editorial_reason": "LLM token context window; Hebrewized transliteration.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "state",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?State(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ה?סטייט(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "State parameter in Jev architecture.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "Questions",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Questions(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Questions schema property in Jev model.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "pull request",
        "kind": "technical_practice",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?PR(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Git pull request / code review artifact.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "PR Score",
        "kind": "technical_concept",
        "priority": 12,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?PR\s+Score(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Pull request evaluation scoring metric.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "SLA",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?SLA(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Service Level Agreement.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "Markdown",
        "kind": "technical_concept",
        "priority": 2,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?MD(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Markdown document format.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "sweet spot",
        "kind": "descriptive_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?sweet\s+spot(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Descriptive trade-off optimum phrase.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "black box",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?black\s+box(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Opaque model / uninterpretable system.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "autoregressive",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?autoregressive(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?אוטו-רגרסיב?(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Autoregressive generation model characteristic.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "use case",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Use\s+Cases?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?use\s+cases?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Application scenario / use case.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "batch",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?batch(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Batch inference processing.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "pipeline",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?pipeline(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Processing pipeline.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "workflow",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?workflows?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Workflows?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Agent / automation workflow.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "latency",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?latency(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?Latency(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Model response time / latency.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "token",
        "kind": "technical_concept",
        "priority": 4,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?tokens?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?טוקנ(?:ים)?(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Text token unit in LLMs.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "endpoint",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?endpoint(?![A-Za-z0-9])",
        ],
        "editorial_reason": "API endpoint service.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "instruction",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?instruction(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Prompt instruction tuning.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "confidence score",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?confidence(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?confident(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Probability confidence score.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "thinking tokens",
        "kind": "technical_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?thinking(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Reasoning / thinking tokens in modern LLMs.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "boolean",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?true\s+false(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?בוליאן(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?false(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?true(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Boolean classification output.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "action",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?action(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ה?אקשן(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Agent action decision.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "A/B testing",
        "kind": "technical_practice",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?A-B\s+טסטינג(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?A-B(?![A-Za-z0-9])",
        ],
        "editorial_reason": "A/B testing experimentation.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "best in class",
        "kind": "descriptive_concept",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?best\s+in\s+Class(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Top tier evaluation label.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "LLM judging",
        "kind": "technical_practice",
        "priority": 8,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?judging(?![A-Za-z0-9])",
        ],
        "editorial_reason": "LLM-as-a-judge practice.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "policy",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?policy(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Security / operational compliance policy.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "provision",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?provision(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Resource provisioning.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "next steps",
        "kind": "technical_concept",
        "priority": 6,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?next\s+steps?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Agent execution step proposal.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "browser",
        "kind": "tool",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ב?בראוזר(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?browser(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Web browser environment for DOM actions.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "benchmark",
        "kind": "technical_practice",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?בנצ['׳״]?מארק(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?benchmarks?(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Model evaluation benchmark.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "architecture",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?לארכיטקטורה(?![A-Za-z0-9\u0590-\u05fe])",
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ארכיטקטורה(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Model architecture.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "deterministic",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?דטרמיניסטי(?:ת)?(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Deterministic execution / classification.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "production",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?ה?פרודקשן(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Production environment deployment.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "integration",
        "kind": "technical_practice",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?אינטגרציה(?![A-Za-z0-9\u0590-\u05fe])",
        ],
        "editorial_reason": "Software integration.",
        "is_cross_script": True,
        "uncertainty_flag": True,
    },
    {
        "canonical": "repository",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?repos(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Code repositories.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "query",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?query(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Search / RAG query.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "domain",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?domain(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Domain-specific vertical expertise.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "double down",
        "kind": "descriptive_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?double\s+down(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Investigative drill-down action.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "calibrated",
        "kind": "technical_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?calibrated(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Well-calibrated prediction probabilities.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "healthcare",
        "kind": "descriptive_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?health\s+care(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Domain vertical: healthcare.",
        "uncertainty_flag": False,
    },
    {
        "canonical": "legal tech",
        "kind": "descriptive_concept",
        "priority": 5,
        "patterns": [
            r"(?<![A-Za-z0-9\u0590-\u05fe])(?:[ובלמשכ]-?)?law(?![A-Za-z0-9])",
        ],
        "editorial_reason": "Domain vertical: law.",
        "uncertainty_flag": False,
    },
]


def _clean_token(t: str) -> str:
    return re.sub(r"^[^\w\u0590-\u05fe]+|[^\w\u0590-\u05fe]+$", "", t).strip()


def _align_term_in_cue(
    cue_text: str,
    match_span: Tuple[int, int],
    c_tokens: List[Dict[str, Any]],
    cue_start: float,
    cue_end: float,
) -> Tuple[float, float, str]:
    """Accurately resolve word timestamps against machine ASR tokens or interpolate."""
    m_start, m_end = match_span
    surface = cue_text[m_start:m_end].strip(" .,!?:;\t\n\r")
    clean_target = re.sub(r"[^a-zA-Z0-9\u0590-\u05fe]", "", surface).lower()

    if not clean_target:
        return cue_start, cue_end, "approximate_from_reviewed_subtitle_cue"

    dur = max(0.1, cue_end - cue_start)
    pos_ratio = m_start / max(1, len(cue_text))
    expected_time = cue_start + pos_ratio * dur

    # 1. Collect all matching token sequences
    matching_candidates = []
    for i, t in enumerate(c_tokens):
        t_clean = re.sub(r"[^a-zA-Z0-9\u0590-\u05fe]", "", t.get("text", "")).lower()
        if t_clean == clean_target:
            matching_candidates.append([t])
            continue
        acc = ""
        seq = []
        for j in range(i, min(i + 6, len(c_tokens))):
            part = re.sub(r"[^a-zA-Z0-9\u0590-\u05fe]", "", c_tokens[j].get("text", "")).lower()
            acc += part
            seq.append(c_tokens[j])
            if acc == clean_target:
                matching_candidates.append(seq)
                break
            if len(acc) > len(clean_target):
                break

    if matching_candidates:
        # Pick matching sequence whose start is closest to expected_time
        matching_candidates.sort(key=lambda seq: abs(float(seq[0]["start"]) - expected_time))
        best_cand = matching_candidates[0]
        cand_start = float(best_cand[0]["start"])
        max_deviation = max(3.0, dur * 0.45)
        if abs(cand_start - expected_time) <= max_deviation:
            s = float(best_cand[0]["start"])
            e = float(best_cand[-1]["end"])
            return round(s, 3), round(max(s + 0.1, e), 3), "asr_token_aligned"

    # 2. Position-proportional interpolation within cue bounds
    ratio_s = m_start / max(1, len(cue_text))
    ratio_e = m_end / max(1, len(cue_text))
    est_s = cue_start + ratio_s * dur
    est_e = cue_start + ratio_e * dur
    return round(est_s, 2), round(max(est_s + 0.3, est_e), 2), "approximate_character_interpolated"


def extract_reference_candidates(
    srt_path: Path,
    hybrid_tokens_path: Optional[Path] = None,
    dataset_a_path: Optional[Path] = None,
    dataset_b_path: Optional[Path] = None,
    guid: str = "0e404ceb-d04b-4818-907d-a74aafa7c155",
    title: str = "74 - Jev",
) -> Dict[str, Any]:
    """Derive ground-truth candidate technical terms and occurrences from corrected SRT."""
    srt_content = srt_path.read_text(encoding="utf-8-sig")
    cues = parse_srt(srt_content)

    hybrid_tokens = []
    if hybrid_tokens_path and hybrid_tokens_path.exists():
        hybrid_data = json.loads(hybrid_tokens_path.read_text(encoding="utf-8"))
        hybrid_tokens = hybrid_data.get("tokens", [])

    b_candidates_by_key = {}
    if dataset_b_path and dataset_b_path.exists():
        b_data = json.loads(dataset_b_path.read_text(encoding="utf-8"))
        for c in b_data.get("combined_candidate_terms", []):
            b_candidates_by_key[c["key"]] = c

    glossary_a_terms = set()
    if dataset_a_path and dataset_a_path.exists():
        a_data = json.loads(dataset_a_path.read_text(encoding="utf-8"))
        glossary_a_terms = set(a_data.get("ordered_terms", []))

    # Compile lexicon regexes
    compiled_lexicon = []
    for item in LEXICON:
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in item["patterns"]]
        compiled_lexicon.append({**item, "compiled": compiled_patterns})

    concept_groups: Dict[str, Dict[str, Any]] = {}
    total_occurrences_count = 0

    for cue_idx, cue in enumerate(cues, 1):
        cue_text = cue["text"]
        cue_start = float(cue["start"])
        cue_end = float(cue["end"])
        cue_id = f"turn-{cue_idx:04d}"

        # Sub-tokens belonging to this cue interval
        c_tokens = [
            t for t in hybrid_tokens
            if (cue_start - 0.4 <= float(t.get("start", 0)) <= cue_end + 0.4)
        ]

        # 1. Collect all candidate matches from all lexicon entries across the cue
        candidate_matches = []
        for entry in compiled_lexicon:
            for pattern in entry["compiled"]:
                for match in pattern.finditer(cue_text):
                    m_start, m_end = match.span()
                    surface = cue_text[m_start:m_end].strip(" .,!?:;\t\n\r")
                    if surface:
                        candidate_matches.append({
                            "span": (m_start, m_end),
                            "match_length": m_end - m_start,
                            "priority": entry.get("priority", 5),
                            "surface": surface,
                            "entry": entry,
                        })

        # 2. Sort candidate matches:
        # Longer surface span wins first, then higher priority, then earlier appearance
        candidate_matches.sort(
            key=lambda m: (-m["match_length"], -m["priority"], m["span"][0])
        )

        # 3. Accept non-overlapping matches greedily
        matched_spans = []
        for cand in candidate_matches:
            m_start, m_end = cand["span"]
            if any(not (m_end <= s or m_start >= e) for s, e in matched_spans):
                continue

            matched_spans.append((m_start, m_end))
            surface = cand["surface"]
            entry = cand["entry"]

            canonical = entry["canonical"]
            kind = entry["kind"]
            reason = entry["editorial_reason"]
            is_cross_script = entry.get("is_cross_script", False)
            uncertain = entry.get("uncertainty_flag", False)

            # Align word-level timestamp
            word_start, word_end, precision = _align_term_in_cue(
                cue_text, (m_start, m_end), c_tokens, cue_start, cue_end
            )

            # Determine sources from Dataset B
            b_key = re.sub(r"[^a-z0-9]", "", canonical.lower())
            b_info = b_candidates_by_key.get(b_key)
            sources = b_info.get("sources", []) if b_info else ["user_corrected_srt"]

            # Hebrew morphology detection
            hebrew_prefix = None
            stem = None
            if is_cross_script:
                prefix_match = re.match(r"^([ובלמשכ]-?|ה-?|וה-?|וב-?|ומ-?)(.+)$", surface)
                if prefix_match:
                    raw_pref = prefix_match.group(1)
                    hebrew_prefix = raw_pref if raw_pref.endswith("-") else raw_pref + "-"
                    stem = prefix_match.group(2)
                else:
                    stem = surface

            total_occurrences_count += 1
            occ_id = total_occurrences_count

            occ_record = {
                "id": occ_id,
                "start": word_start,
                "end": word_end,
                "timestamp_precision": precision,
                "source_cue_id": cue_id,
                "cue_start": cue_start,
                "cue_end": cue_end,
                "surface": surface,
                "matched_text": surface,
                "context": cue_text,
                "sources": sources,
                "state": "pending",
                "manual": False,
            }
            if hebrew_prefix or stem:
                occ_record["hebrew_morphology"] = {
                    "prefix": hebrew_prefix,
                    "stem": stem,
                }

            group = concept_groups.setdefault(canonical, {
                "id": len(concept_groups) + 1,
                "canonical": canonical,
                "term": canonical,
                "surface": surface,
                "surfaces": set(),
                "kind": kind,
                "editorial_reason": reason,
                "is_cross_script": is_cross_script,
                "uncertainty_flag": uncertain,
                "sources": set(),
                "occurrences": [],
            })
            group["surfaces"].add(surface)
            for s in sources:
                group["sources"].add(s)
            group["occurrences"].append(occ_record)

    # Format term groups
    suggested_terms = []
    found_canonicals = set(concept_groups.keys())

    for idx, (canonical, g) in enumerate(
        sorted(concept_groups.items(), key=lambda x: (-len(x[1]["occurrences"]), x[0].casefold())),
        1
    ):
        g["id"] = idx
        g["surfaces"] = sorted(g["surfaces"])
        g["sources"] = sorted(g["sources"])
        if len(g["surfaces"]) == 1:
            g["surface"] = g["surfaces"][0]
        else:
            g["surface"] = f"{canonical} ({', '.join(g['surfaces'][:3])})"
        g["occurrences"].sort(key=lambda o: o["start"])
        suggested_terms.append(g)

    # Reconcile against Datasets A and B for suggested missing terms
    suggested_missing = []
    for key, c in sorted(b_candidates_by_key.items()):
        guess = c.get("canonical_guess", key)
        if guess not in found_canonicals and not any(guess.lower() == g["canonical"].lower() for g in suggested_terms):
            if c.get("total_estimated_occurrences", 0) >= 2 and len(guess) >= 3:
                suggested_missing.append(guess)

    for a_term in sorted(glossary_a_terms):
        if a_term not in found_canonicals and not any(a_term.lower() == g["canonical"].lower() for g in suggested_terms):
            if a_term not in suggested_missing and len(a_term) >= 3:
                suggested_missing.append(a_term)

    cross_script_groups = [g for g in suggested_terms if g.get("is_cross_script")]
    uncertain_groups = [g for g in suggested_terms if g.get("uncertainty_flag")]

    proposal = {
        "protocol_layer": "C",
        "description": "Proposed ground-truth technical terminology reference derived from user-corrected SRT",
        "episode_guid": guid,
        "episode_title": title,
        "audio_url": "audio.mp3",
        "window": {"start": 0.0, "end": 1848.89},
        "draft_only": True,
        "review_status": "needs_review",
        "terms_exhaustive": False,
        "summary": {
            "total_concepts_count": len(suggested_terms),
            "total_occurrences_count": total_occurrences_count,
            "cross_script_concepts_count": len(cross_script_groups),
            "uncertain_concepts_count": len(uncertain_groups),
            "suggested_missing_count": len(suggested_missing),
            "cues_scanned": len(cues),
        },
        "suggested_missing": suggested_missing[:40],
        "suggested_terms": suggested_terms,
    }

    return proposal


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", required=True, type=Path, help="Path to evaluation directory")
    args = parser.parse_args()

    eval_dir = args.eval_dir
    srt_path = eval_dir / "reference_user_corrected.original.srt"
    hybrid_path = eval_dir / "hybrid_revised.original.json"
    glossary_a_path = eval_dir / "engine_glossary.original.json"
    detected_b_path = eval_dir / "engine_terms_detected.original.json"
    out_path = eval_dir / "reference_terms.proposed.json"

    proposal = extract_reference_candidates(
        srt_path=srt_path,
        hybrid_tokens_path=hybrid_path,
        dataset_a_path=glossary_a_path,
        dataset_b_path=detected_b_path,
    )
    out_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Generated proposed technical terms reference at: {out_path}")
    print(f"Total concepts: {proposal['summary']['total_concepts_count']}")
    print(f"Total occurrences: {proposal['summary']['total_occurrences_count']}")
