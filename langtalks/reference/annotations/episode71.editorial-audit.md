# Episode 71 — editorial review of all 41 expressions

All 69 user-confirmed occurrences remain preserved in `verified_occurrences`; the unmodified original is `episode71.user-approved.json`. AI-assigned classifications are editorial metadata, not a second listening verification.

33 technical expressions are used in strict Latin-script recall. `agent`, `container`, `multi tenant`, and `Auth` remain as confirmed evidence but are excluded from strict spelling scoring (generic, Hebrewized, or phonetic uncertainty).

| Original user expression | Concept type | Canonical search concept | Indexed? | Reason |
|---|---|---|---|---|
| `supply chain security` | `technical_concept` | `supply chain security` | Yes | Approved technical speech; useful for semantic retrieval. |
| `code review` | `technical_practice` | `code review` | Yes | Approved technical speech; useful for semantic retrieval. |
| `security best practices` | `technical_practice` | `security best practices` | Yes | Approved technical speech; useful for semantic retrieval. |
| `NanoClaw` | `product` | `NanoClaw` | Yes | Approved technical speech; useful for semantic retrieval. |
| `OpenClaw` | `product` | `OpenClaw` | Yes | Approved technical speech; useful for semantic retrieval. |
| `agent` | `technical_concept` | `AI agent` | Yes | Generic architectural actor; preserving occurrences doesn't require strict Latin spelling. |
| `orchestration` | `technical_concept` | `orchestration` | Yes | Approved technical speech; useful for semantic retrieval. |
| `file system` | `technical_concept` | `file system` | Yes | Approved technical speech; useful for semantic retrieval. |
| `mounted directory` | `technical_concept` | `mounted directory` | Yes | Approved technical speech; useful for semantic retrieval. |
| `credentials` | `technical_concept` | `credentials` | Yes | Approved technical speech; useful for semantic retrieval. |
| `gateway` | `technical_concept` | `credential gateway` | Yes | Approved technical speech; useful for semantic retrieval. |
| `human-in-the-loop approval` | `technical_practice` | `human-in-the-loop approval` | Yes | Approved technical speech; useful for semantic retrieval. |
| `OneCLI` | `product` | `OneCLI` | Yes | Speaker explicitly confirmed OneCLI at all six appearances; preserve raw ASR separately. |
| `Composio` | `product` | `Composio` | Yes | Approved technical speech; useful for semantic retrieval. |
| `Auth` | `protocol` | `OAuth` | Yes | ASR Auth vs canonical OAuth remains an exact spoken-form ambiguity. |
| `API` | `technical_concept` | `API` | Yes | Approved technical speech; useful for semantic retrieval. |
| `refresh token` | `technical_concept` | `refresh token` | Yes | Approved technical speech; useful for semantic retrieval. |
| `standalone` | `descriptive_concept` | `standalone authentication solution` | Transcript only | Isolated adjective; standalone authentication solution requires clause context. |
| `third-party tools` | `technical_concept` | `third-party tool integrations` | Yes | Approved technical speech; useful for semantic retrieval. |
| `managed hosted version` | `descriptive_concept` | `managed hosting` | Yes | Index as managed hosting, while preserving spoken phrasing. |
| `Gmail` | `product` | `Gmail` | Yes | Approved technical speech; useful for semantic retrieval. |
| `Calendar` | `product` | `Google Calendar` | Yes | Approved technical speech; useful for semantic retrieval. |
| `Drive` | `product` | `Google Drive` | Yes | Approved technical speech; useful for semantic retrieval. |
| `dependency` | `technical_concept` | `software dependency` | Yes | Approved technical speech; useful for semantic retrieval. |
| `multi tenant` | `technical_concept` | `multi-tenancy` | Yes | Hebrewized מולטי-טננט is acceptable speech; index under multi-tenancy. |
| `Hermes` | `product` | `Hermes` | Yes | Approved technical speech; useful for semantic retrieval. |
| `use cases` | `other` | `use cases` | Transcript only | Common planning phrase, not a distinctive concept. |
| `container` | `technical_concept` | `container` | Yes | Some uses are Hebrewized קונטיינר; strict Latin spelling would violate policy. |
| `process` | `technical_concept` | `OS process` | Yes | Approved technical speech; useful for semantic retrieval. |
| `preserved` | `descriptive_concept` | `persistent state` | Transcript only | State persistence is covered by file system/mounted directory. |
| `HTTP network` | `technical_concept` | `HTTP network traffic` | Yes | Approved technical speech; useful for semantic retrieval. |
| `header` | `technical_concept` | `HTTP Authorization header` | Transcript only | Merge as a proposed HTTP Authorization header concept, preserving component evidence. |
| `authorization` | `technical_concept` | `HTTP Authorization header` | Transcript only | Merge as a proposed HTTP Authorization header concept, preserving component evidence. |
| `Google Workspace` | `product` | `Google Workspace` | Yes | Approved technical speech; useful for semantic retrieval. |
| `Log in with Google` | `technical_practice` | `Sign in with Google` | Yes | Concrete named sign-in flow, useful to an implementing agent. |
| `coupled` | `descriptive_concept` | `decoupled integration` | Transcript only | Only meaningful in context of a negated coupling claim. |
| `harness` | `technical_concept` | `agent harness` | Yes | Approved technical speech; useful for semantic retrieval. |
| `Codex` | `product` | `Codex` | Yes | Approved technical speech; useful for semantic retrieval. |
| `open source` | `descriptive_concept` | `open-source software` | Yes | Approved technical speech; useful for semantic retrieval. |
| `Anthropic` | `organization` | `Anthropic` | Yes | Approved technical speech; useful for semantic retrieval. |
| `vault` | `technical_concept` | `credential vault` | Yes | Approved technical speech; useful for semantic retrieval. |

## Merge suggestions and separations

**Suggested merge:** `header` + `authorization` (around 11:12–11:14) to a single semantic concept **HTTP Authorization header**. The source words were user-approved individually, but the new composite remains `suggested` rather than falsely user-verified.

**Keep separate:** `file system` vs `mounted directory`; `OneCLI` vs `OAuth`; `Gmail`, `Google Calendar`, `Google Drive` vs `Google Workspace`; and the `Log in with Google` user-flow vs underlying `OAuth` protocol.

**Transcript-only:** `coupled`, `standalone`, `preserved`, `use cases`, and ordinary expressions such as `nice`, `partnership`, and `as far as I know`. Preserve all speech and especially epistemic qualifiers in context, but don't index them as technologies.

## OneCLI: six corrected occurrences

The user confirmed hearing **OneCLI** at approximately 10:46.7, 10:59.3, 11:05.2, 11:29.5, 12:15.1 and 12:52.4. ASR had `Onecli` / `1.cli`. The original model spelling remains available as error evidence; generic `CLI` is not an acceptable product identity.

## Benchmark limitations

The existing type-level recall can pass if a model recognizes one out of six OneCLI mentions. A supplementary timestamp-based occurrence diagnostic now catches repeated failures; it is not part of weighted provider rankings until cross-model timing is validated.

No paid API was used.
