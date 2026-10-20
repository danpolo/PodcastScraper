"""Generate self-contained ground-truth terminology review HTML for held-out evaluation.

Embeds the proposed terminology reference (Layer C candidate), full agent transcript,
and local audio reference for synchronized listening and validation in any browser.
Supports client-side and server-side migration of existing review progress, ensuring
reviewed decisions are preserved when concept discoveries are refined.
No external network dependencies or paid services are required.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List


def migrate_review_session(saved_session: Dict[str, Any], new_proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate a saved terminology review session onto a refined ground-truth proposal.

    Preserves:
    - Reviewed states ('confirmed', 'rejected') and notes for each occurrence.
    - Manually added terms and occurrences.
    - 'listened' approval checkbox state.

    Remaps:
    - Occurrences previously matched under broader concepts (e.g. AI agent) to refined concepts
      (e.g. AGENTS.md, Subagent, Agentic search, Agent harness) using cue ID and timestamp proximity.
    - Attaches `migrated_from` metadata and `reassigned: True` flag.
    """
    # 1. Convert new proposal into state structure
    if "term_groups" in new_proposal and isinstance(new_proposal.get("term_groups"), list):
        migrated_state = json.loads(json.dumps(new_proposal))
    elif "suggested_terms" in new_proposal:
        migrated_state = {
            "review_session": True,
            "episode_guid": new_proposal.get("episode_guid", ""),
            "episode_title": new_proposal.get("episode_title", ""),
            "window": new_proposal.get("window", {"start": 0, "end": 1848.89}),
            "audio_url": new_proposal.get("audio_url", "audio.mp3"),
            "suggested_missing": new_proposal.get("suggested_missing", []),
            "listened": bool(new_proposal.get("terms_exhaustive", False)),
            "term_groups": [
                {
                    "id": i + 1,
                    "canonical": g.get("canonical") or g.get("term") or "",
                    "term": g.get("canonical") or g.get("term") or "",
                    "surface": g.get("surface") or g.get("term") or "",
                    "surfaces": g.get("surfaces", [g.get("surface") or g.get("term") or ""]),
                    "kind": g.get("kind", "other"),
                    "editorial_reason": g.get("editorial_reason", ""),
                    "is_cross_script": bool(g.get("is_cross_script", False)),
                    "uncertainty_flag": bool(g.get("uncertainty_flag", False)),
                    "sources": g.get("sources", g.get("seen_in", [])),
                    "occurrences": [
                        {
                            "id": j + 1,
                            "start": float(o["start"]),
                            "end": float(o["end"]),
                            "precision": o.get("timestamp_precision") or o.get("precision", "asr_token_aligned"),
                            "source_cue_id": o.get("source_cue_id", ""),
                            "cue_start": float(o.get("cue_start", o["start"])),
                            "cue_end": float(o.get("cue_end", o["end"])),
                            "surface": o.get("surface") or o.get("matched_text") or g.get("canonical", ""),
                            "matched_text": o.get("matched_text") or o.get("surface") or g.get("canonical", ""),
                            "context": o.get("context", ""),
                            "sources": o.get("sources", g.get("sources", [])),
                            "hebrew_morphology": o.get("hebrew_morphology", None),
                            "state": o.get("state", "pending"),
                            "manual": bool(o.get("manual", False)),
                        }
                        for j, o in enumerate(g.get("occurrences", []))
                    ],
                }
                for i, g in enumerate(new_proposal.get("suggested_terms", []))
            ],
        }
    else:
        raise ValueError("Invalid proposal data format.")

    if not saved_session:
        return migrated_state

    # 2. Extract reviewed occurrences from saved_session
    saved_groups = saved_session.get("term_groups") or saved_session.get("suggested_terms") or []
    saved_occs = []
    for g in saved_groups:
        canon = g.get("canonical") or g.get("term") or ""
        for o in g.get("occurrences", []):
            saved_occs.append({
                "canonical": canon,
                "kind": g.get("kind", "technical_concept"),
                "occ": o,
            })

    preserved_decisions_count = 0
    remapped_count = 0
    remapped_details = []

    # 3. Match new occurrences against saved occurrences using prioritized bipartite matching
    # requiring meaningful surface/identity compatibility and strict time bounds.
    def _clean_str(s: str) -> str:
        return re.sub(r"[^a-zA-Z0-9\u0590-\u05fe]", "", s or "").lower()

    def _are_compatible(s_canon: str, s_surf: str, n_canon: str, n_surf: str, time_diff: float, same_cue: bool = False) -> bool:
        s_c = _clean_str(s_surf)
        n_c = _clean_str(n_surf)
        s_canon_c = _clean_str(s_canon)
        n_canon_c = _clean_str(n_canon)

        if not s_c or not n_c:
            return False

        # 1. Surface compatibility
        surface_compat = False
        if s_c == n_c:
            surface_compat = True
        elif s_c in n_c or n_c in s_c:
            surface_compat = True
        else:
            # Strip Hebrew prefixes (ובלמשכה)
            s_stem = re.sub(r"^[ובלמשכה]{1,3}-?", "", s_c)
            n_stem = re.sub(r"^[ובלמשכה]{1,3}-?", "", n_c)
            if s_stem and n_stem and (s_stem == n_stem or s_stem in n_stem or n_stem in s_stem):
                surface_compat = True

        # 2. Concept / Identity compatibility
        concept_compat = False
        if s_canon_c and n_canon_c and s_canon_c == n_canon_c:
            concept_compat = True
        elif s_c and n_canon_c and (s_c in n_canon_c or n_canon_c in s_c):
            concept_compat = True
        elif n_c and s_canon_c and (n_c in s_canon_c or s_canon_c in n_c):
            concept_compat = True

        # 3. Decision logic
        if same_cue:
            if surface_compat:
                return True
            if concept_compat and time_diff <= 1.5:
                return True
            return False

        # If not same cue:
        if not (surface_compat or concept_compat):
            return False
        if time_diff > 2.5:
            return False
        if not (s_c == n_c or (s_canon_c and s_canon_c == n_canon_c)) and time_diff > 1.2:
            return False

        return True

    new_occs_flat = []
    for group in migrated_state["term_groups"]:
        for occ in group["occurrences"]:
            new_occs_flat.append((group, occ))

    match_candidates = []
    for n_idx, (group, occ) in enumerate(new_occs_flat):
        n_clean = _clean_str(occ.get("surface"))
        for s_idx, s in enumerate(saved_occs):
            s_clean = _clean_str(s["occ"].get("surface"))
            time_diff = abs(float(s["occ"]["start"]) - float(occ["start"]))
            same_cue = bool(
                s["occ"].get("source_cue_id")
                and occ.get("source_cue_id")
                and s["occ"]["source_cue_id"] == occ.get("source_cue_id")
            )

            if not _are_compatible(s["canonical"], s["occ"].get("surface", ""), group["canonical"], occ.get("surface", ""), time_diff, same_cue):
                continue

            score = 0.0
            if n_clean and s_clean:
                if n_clean == s_clean:
                    score += 100.0
                elif n_clean in s_clean or s_clean in n_clean:
                    score += 50.0
                else:
                    score += 30.0  # stem match
            if s["canonical"] and group["canonical"] and s["canonical"].lower() == group["canonical"].lower():
                score += 25.0
            if same_cue:
                score += 15.0
            score -= time_diff * 10.0
            match_candidates.append((score, n_idx, s_idx))

    match_candidates.sort(key=lambda x: -x[0])
    used_n = set()
    used_s = set()
    matches = {}
    for score, n_idx, s_idx in match_candidates:
        if n_idx in used_n or s_idx in used_s:
            continue
        used_n.add(n_idx)
        used_s.add(s_idx)
        matches[n_idx] = s_idx

    for n_idx, s_idx in matches.items():
        group, occ = new_occs_flat[n_idx]
        s = saved_occs[s_idx]
        s_occ = s["occ"]
        is_reassigned = bool(
            s["canonical"]
            and group["canonical"]
            and s["canonical"].strip().lower() != group["canonical"].strip().lower()
        )

        if is_reassigned:
            occ["migrated_from"] = s["canonical"]
            occ["reassigned"] = True
            occ["reapproval_required"] = True
            occ["state"] = "pending"  # Always requires fresh decision on new association!
            remapped_count += 1

            if s_occ.get("state") == "rejected":
                occ["previously_rejected_under"] = s["canonical"]
                hist_note = f"Previously rejected under '{s['canonical']}' (requires fresh decision for '{group['canonical']}')."
                if s_occ.get("notes"):
                    occ["notes"] = f"{s_occ['notes']} [{hist_note}]"
                else:
                    occ["notes"] = hist_note
            elif s_occ.get("state") == "confirmed":
                occ["previously_confirmed_under"] = s["canonical"]
                if s_occ.get("notes"):
                    occ["notes"] = s_occ["notes"]
            else:
                if s_occ.get("notes"):
                    occ["notes"] = s_occ["notes"]

            remapped_details.append({
                "surface": occ["surface"],
                "cue": occ["source_cue_id"],
                "from": s["canonical"],
                "to": group["canonical"],
                "previous_state": s_occ.get("state"),
            })
        else:
            # Same concept: preserve user decision directly
            if s_occ.get("state") in ("confirmed", "rejected"):
                occ["state"] = s_occ["state"]
                preserved_decisions_count += 1
            if s_occ.get("notes"):
                occ["notes"] = s_occ["notes"]

    # 4. Carry over manually added items from saved session
    for g in saved_groups:
        for o in g.get("occurrences", []):
            if o.get("manual"):
                g_canon = g.get("canonical") or g.get("term") or ""
                target_g = next((x for x in migrated_state["term_groups"] if x["canonical"].lower() == g_canon.lower()), None)
                if not target_g:
                    target_g = {
                        "id": len(migrated_state["term_groups"]) + 1,
                        "canonical": g_canon,
                        "term": g_canon,
                        "surface": o.get("surface") or g_canon,
                        "surfaces": [o.get("surface") or g_canon],
                        "kind": g.get("kind", "technical_concept"),
                        "editorial_reason": "Manual addition from previous review session.",
                        "is_cross_script": False,
                        "uncertainty_flag": False,
                        "sources": ["manual"],
                        "occurrences": [],
                    }
                    migrated_state["term_groups"].append(target_g)

                # Check if already present
                if not any(abs(float(existing["start"]) - float(o["start"])) < 0.5 for existing in target_g["occurrences"]):
                    target_g["occurrences"].append(dict(o))
                    target_g["occurrences"].sort(key=lambda x: float(x["start"]))

    # 5. Carry over listened status
    if "listened" in saved_session:
        migrated_state["listened"] = bool(saved_session["listened"])

    migrated_state["_migration_stats"] = {
        "preserved_decisions_count": preserved_decisions_count,
        "remapped_count": remapped_count,
        "remapped_details": remapped_details[:30],
    }

    return migrated_state


def bulk_approve_confident(state: Dict[str, Any]) -> int:
    """Safely bulk approve only unambiguous, confident, non-reassigned pending occurrences.

    NEVER approves an occurrence with reapproval_required, reassigned, migrated_from,
    previously_rejected_under, or ambiguity flags, regardless of concept confidence flags.
    """
    approved_count = 0
    for g in state.get("term_groups", []):
        if not g.get("uncertainty_flag") and not g.get("is_cross_script"):
            for occ in g.get("occurrences", []):
                is_ambiguous_or_reassigned = bool(
                    occ.get("reapproval_required")
                    or occ.get("reassigned")
                    or occ.get("migrated_from")
                    or occ.get("previously_rejected_under")
                    or occ.get("ambiguous")
                )
                if occ.get("state") == "pending" and not is_ambiguous_or_reassigned:
                    occ["state"] = "confirmed"
                    approved_count += 1
    return approved_count


def reset_reviewed_occurrences(state: Dict[str, Any]) -> int:
    """Reset all confirmed or rejected occurrences back to pending, mirroring UI resetOccurrences."""
    reset_count = 0
    for g in state.get("term_groups", []):
        for occ in g.get("occurrences", []):
            if occ.get("state") in ("confirmed", "rejected"):
                occ["state"] = "pending"
                reset_count += 1
    state["listened"] = False
    return reset_count


def export_approved_reference(state: Dict[str, Any], transcript: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Export benchmark reference C from review state, mirroring the UI exportRef logic."""
    pending_count = sum(
        1 for g in state.get("term_groups", []) for o in g.get("occurrences", []) if o.get("state") == "pending"
    )
    is_exhaustive = bool(state.get("listened")) and pending_count == 0

    confirmed_groups = [
        g for g in state.get("term_groups", []) if any(o.get("state") == "confirmed" for o in g.get("occurrences", []))
    ]
    terms = sorted(list({g["canonical"] for g in confirmed_groups}))

    confirmed_occs = []
    for g in confirmed_groups:
        for o in g.get("occurrences", []):
            if o.get("state") == "confirmed":
                confirmed_occs.append({
                    "term": g["canonical"],
                    "surface": o.get("surface", g["canonical"]),
                    "canonical": g["canonical"],
                    "kind": g.get("kind", "technical_concept"),
                    "start": o.get("start", 0.0),
                    "end": o.get("end", 0.0),
                    "timestamp_precision": o.get("precision", "asr_token_aligned"),
                    "source_cue_id": o.get("source_cue_id", ""),
                    "source_models": o.get("sources", []),
                    "hebrew_morphology": o.get("hebrew_morphology"),
                    "review_status": "verified",
                })

    ref_out = {
        "protocol_layer": "C",
        "episode_guid": state.get("episode_guid", "0e404ceb-d04b-4818-907d-a74aafa7c155"),
        "episode_title": state.get("episode_title", "74 - Jev"),
        "window": state.get("window", "full_episode"),
        "technical_terms": terms,
        "reference_text": " ".join(t.get("text", "") for t in transcript.get("turns", [])) if transcript else "",
        "review_status": "approved" if is_exhaustive else "pending",
        "terms_exhaustive": is_exhaustive,
        "verified_occurrences": confirmed_occs,
        "concept_mentions": [
            {
                "id": f"mention-{i+1:04d}",
                "turn_id": o["source_cue_id"],
                "start_s": o["start"],
                "end_s": o["end"],
                "surface": o["surface"],
                "canonical": o["canonical"],
                "kind": o["kind"],
                "aliases": [],
                "review_status": "verified",
                "provenance": {
                    "models": o["source_models"],
                    "timestamp_alignment": o["timestamp_precision"],
                },
            }
            for i, o in enumerate(confirmed_occs)
        ],
    }
    return ref_out


def build_review_html(proposal: Dict[str, Any], transcript: Dict[str, Any], audio_rel_path: str = "audio.mp3") -> str:
    """Return self-contained HTML page for ground-truth technical terminology review."""
    proposal_json_str = json.dumps(proposal, ensure_ascii=False)
    transcript_json_str = json.dumps(transcript, ensure_ascii=False)

    html_template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PodcastScraper — Ground-Truth Terminology Review (Ep 74)</title>
<style>
:root{color-scheme:dark;--bg:#0d131a;--panel:#17232e;--panel2:#1e2d39;--line:#354655;--muted:#aabcc7;--text:#eff7fb;--accent:#74dfc6;--error:#f4a3a4;--warn:#f7d795;--badge-bg:#263c4d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
button,input,select,textarea{font:inherit}
button{cursor:pointer;color:inherit;border:1px solid var(--line);border-radius:8px;background:var(--panel2);padding:7px 11px}
button:hover{border-color:var(--accent)}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button.primary{background:#176d5d;color:white;border-color:#31a78e;font-weight:600}
button.warn-btn{background:#634d1b;color:#fce4a6;border-color:#a17e2e}
button.danger{border-color:#98616b;color:var(--error)}
button.flat{background:transparent}
button:disabled{opacity:.4;cursor:not-allowed}
header{padding:16px max(20px,calc((100vw - 1440px)/2));background:#121c25;border-bottom:1px solid var(--line)}
header h1{font-size:20px;letter-spacing:-.3px;margin:0 0 3px}
header p{margin:0;color:var(--muted);font-size:13px}
main{max-width:1440px;margin:auto;padding:16px 20px 50px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.cols{display:grid;grid-template-columns:minmax(300px,380px) 1fr;gap:18px;margin-top:16px}
.panel{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:16px}
.top-panel{display:grid;gap:12px}
small,.muted{color:var(--muted)}
label{font-size:13px;color:var(--muted)}
label.upload{display:inline-flex;align-items:center;gap:7px;cursor:pointer;padding:7px 11px;border-radius:8px;border:1px solid var(--line);background:var(--panel2)}
label.upload:hover{border-color:var(--accent)}.upload input{display:none}
input[type=text],input[type=search],input[type=url],textarea{background:#0f1923;color:var(--text);border:1px solid var(--line);padding:9px;border-radius:8px;min-width:0}
input[type=checkbox]{accent-color:var(--accent);width:17px;height:17px;vertical-align:middle;cursor:pointer}
input.long{width:100%}textarea{width:100%;min-height:68px;resize:vertical}
audio{width:100%;height:40px}
.stat{font-size:13px;color:var(--muted)}.stat strong{color:var(--text)}
.progress{height:8px;background:#283745;overflow:hidden;border-radius:8px;margin:10px 0}
.progress>div{height:100%;width:0;background:var(--accent);transition:width .2s}
#terms{display:grid;gap:4px;max-height:62vh;overflow-y:auto;margin-top:10px;padding-right:4px}
.term-item{display:flex;justify-content:space-between;gap:8px;text-align:left;padding:9px 10px;border-radius:8px;width:100%;background:transparent;border:1px solid transparent}
.term-item.selected{border-color:#3cbfa4;background:#15392f}
.term-item.has-uncertainty{border-left:3px solid var(--warn)}
.term-item.has-migrated{border-right:3px solid var(--accent)}
.term-name{font-weight:600;overflow-wrap:anywhere}
.pill{border-radius:16px;padding:2px 7px;font-size:11px;white-space:nowrap;border:1px solid #617380;color:#e1ecf1}
.pill.done{border-color:#328970;color:var(--accent)}
.pill.todo{border-color:#7f6870;color:var(--warn)}
.pill.flag{border-color:#a17e2e;background:#342c1c;color:var(--warn)}
.badge{display:inline-block;border-radius:4px;padding:2px 6px;font-size:11px;font-weight:500;margin-right:4px}
.badge.warn{background:#433418;color:#fce4a6;border:1px solid #826325}
.badge.info{background:#1b3244;color:#a2d6f9;border:1px solid #2f5470}
.badge.success{background:#163b2f;color:#7fe3c5;border:1px solid #2d735d}
.side-info{display:flex;align-items:center;justify-content:space-between}
h2{font-size:16px;margin:0 0 10px}h3{font-size:14px;margin:0 0 8px}
.occ{display:grid;grid-template-columns:85px 1fr 140px;align-items:start;gap:12px;padding:10px 0;border-bottom:1px solid #283745}
.occ:last-child{border-bottom:0}
.mono{font-variant-numeric:tabular-nums;font-feature-settings:"tnum"}
.seek{color:var(--accent);background:var(--panel2);font-variant-numeric:tabular-nums;padding:4px 8px;font-size:13px;border-radius:6px;width:100%}
.seek:hover{border-color:var(--accent)}
.sources{font-size:12px;color:var(--muted);margin-top:2px}
.occ-state{display:flex;align-items:center;gap:8px;justify-content:flex-end}
.reject{color:var(--error);padding:4px 8px;font-size:12px}
.reject[aria-pressed=true]{background:#5b313a;border-color:#c4717f}
mark{background:#534316;color:#fff0bc;padding:1px 4px;border-radius:4px;font-weight:600}
.context-box{background:#111b24;border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0;direction:auto;unicode-bidi:plaintext;text-align:start;line-height:1.6}
hr{border:0;border-top:1px solid var(--line);margin:14px 0}
.instructions{font-size:13px;line-height:1.55;color:var(--muted)}
.help-note{padding:10px 12px;border-radius:8px;border:1px solid #57513a;background:#342c1c;color:#fde7aa;margin-top:10px;font-size:13px}
.migration-banner{padding:10px 14px;border-radius:8px;border:1px solid #31a78e;background:#14372e;color:#b2f4e3;margin:8px 0;font-size:13px;line-height:1.5}
fieldset{border:1px solid var(--line);padding:12px;border-radius:10px;margin:12px 0}
legend{padding:0 6px;color:var(--accent);font-size:13px;font-weight:600}
#status{font-size:13px;min-height:1.3em;color:var(--accent)}
.kbd{display:inline-block;background:#243340;border:1px solid #455a6d;border-radius:4px;padding:1px 5px;font-size:11px;font-family:monospace;color:#ccdce8}
@media(max-width:840px){main{padding:12px}.cols{grid-template-columns:1fr}.occ{grid-template-columns:1fr;gap:8px}.occ-state{justify-content:flex-start}}
</style>
</head>
<body>
<header>
 <div class="row" style="justify-content:space-between">
  <div>
   <h1>PodcastScraper — Ground-Truth Terminology Review</h1>
   <p>LangTalks #74 (Jev) · Cross-Script Hebrew / English Linking · Offline Validation</p>
  </div>
  <div class="row">
   <button id="resetOccurrences" class="flat danger" title="Reset all reviewed occurrences back to pending">Reset Reviewed Occurrences</button>
   <button id="resetSession" class="flat danger" title="Discard cached session and reload clean AI proposals">Reset to Fresh Proposals</button>
   <button id="exportSession" title="Save current progress to JSON file">Save Session JSON</button>
   <button id="exportRef" class="primary" title="Export final approved benchmark reference">Export Approved Reference</button>
  </div>
 </div>
</header>
<main>
<section class="panel top-panel">
 <div class="row">
  <span class="stat"><strong>Audio:</strong></span>
  <audio id="player" controls preload="metadata"></audio>
  <span class="stat mono" id="clock">00:00</span>
  <button id="back2" title="Backward 2s [Key: Left]">↶ 2s</button>
  <button id="forward2" title="Forward 2s [Key: Right]">2s ↷</button>
  <label><input id="loop" type="checkbox"> Loop snippet</label>
  <label class="upload" style="margin-left:auto">Change Audio File<input type="file" id="audioFile" accept="audio/*,.mp3,.wav,.m4a"></label>
  <label class="upload">Open JSON Session<input type="file" id="proposal" accept=".json,application/json"></label>
 </div>
 <div id="migrationNotice" hidden class="migration-banner"></div>
 <div id="status" role="status">AI-proposed ground truth loaded from user-corrected SRT. Keyboard: <span class="kbd">Space</span> play/pause, <span class="kbd">j</span>/<span class="kbd">k</span> terms, <span class="kbd">a</span> approve, <span class="kbd">r</span> reject.</div>
</section>

<div class="cols">
 <aside class="panel">
  <div class="side-info">
   <h2>Technical Concepts</h2>
   <span class="stat" id="counts">0 / 0 reviewed</span>
  </div>
  <div class="progress"><div id="bar"></div></div>
  <input type="search" id="search" class="long" placeholder="Filter terms (e.g. AGENTS.md, harness, RAG...)" aria-label="Filter candidate terms">
  
  <div class="row" style="margin-top:8px">
   <button id="filterAll" class="primary">All</button>
   <button id="filterExceptions" class="warn-btn" title="Show Hebrewized cross-script and uncertain candidates first">Exceptions & Uncertain</button>
   <button id="filterMigrated" class="warn-btn" title="Show concepts with occurrences migrated/reassigned from broad groups">Migrated & Reassigned</button>
   <button id="filterPending">Pending</button>
   <button id="bulkApprove" title="Bulk approve all high-confidence unambiguous terms">Bulk Approve Confident</button>
   <button id="resetAllOccurrences" class="flat danger" title="Reset all reviewed occurrences back to pending">Reset Reviewed Occurrences</button>
  </div>
  
  <div class="row" style="margin-top:8px">
   <button id="mergeSelected" class="flat" style="font-size:12px">Merge selected</button>
  </div>

  <div id="missingSuggestions" class="instructions" style="margin-top:8px"></div>
  <div id="terms"></div>
 </aside>

 <section class="panel">
  <div id="empty" class="instructions">Choose a technical concept on the left to review its occurrences and verify audio timing.</div>
  
  <div id="detail" hidden>
   <div class="row" style="justify-content:space-between;align-items:flex-start">
    <div style="flex:1">
     <h2 id="conceptHeader" style="margin-bottom:4px"></h2>
     <div id="badgesContainer"></div>
    </div>
    <div class="row">
     <button id="approveTerm" class="primary" title="Confirm all occurrences [Key: a]">Approve Concept ✓</button>
     <button id="rejectTerm" class="danger" title="Reject all occurrences [Key: r]">Reject All ✕</button>
     <button id="resetTerm" class="flat" title="Reset occurrences of this concept back to pending [Key: u]">Reset Concept</button>
    </div>
   </div>
   
   <p id="conceptReason" class="instructions" style="margin:8px 0"></p>

   <div class="row" style="margin:12px 0 8px">
    <div style="flex:2;min-width:180px">
     <label for="editTerm">Canonical concept identity</label>
     <input type="text" id="editTerm" class="long" dir="auto">
    </div>
    <div style="flex:1;min-width:140px">
     <label for="conceptKind">Type</label>
     <select id="conceptKind" class="long" style="padding:9px;background:#0f1923;color:var(--text);border:1px solid var(--line);border-radius:8px">
      <option value="product">Product</option>
      <option value="tool">Tool</option>
      <option value="protocol">Protocol</option>
      <option value="technical_practice">Technical practice</option>
      <option value="technical_concept">Technical concept</option>
      <option value="descriptive_concept">Descriptive phrase</option>
      <option value="organization">Organization</option>
      <option value="other">Other</option>
     </select>
    </div>
    <div style="align-self:flex-end">
     <button id="applyTerm">Save</button>
    </div>
   </div>

   <div id="surfacesList" class="instructions" style="margin-bottom:12px"></div>

   <hr>
   <h3>Occurrences (<span id="occCountHeader">0</span>)</h3>
   <p class="instructions">Click timestamp to listen to the excerpt. Check 'Heard' to confirm or 'Reject' to exclude false detections.</p>
   
   <div id="occurrences"></div>

   <div class="row" style="margin-top:14px;background:#111b24;padding:8px 10px;border-radius:8px;border:1px solid var(--line)">
    <label style="flex:1">Add occurrence to this concept (time in sec or MM:SS):
     <input type="text" id="addAt" placeholder="Player time" style="width:110px;margin-left:6px">
    </label>
    <button id="addOccurrence">+ Add at time</button>
   </div>

   <hr>
   <h3>Add Missing Technical Term</h3>
   <div class="row">
    <input type="text" id="newTerm" placeholder="Canonical term (e.g. Model Context Protocol)" style="flex:2" dir="auto">
    <input type="text" id="newTime" placeholder="Time (optional)" style="width:130px">
    <button id="addTerm" class="primary">+ Add term</button>
   </div>
  </div>

  <hr style="margin-top:20px">
  <fieldset>
   <legend>Final Approval Status</legend>
   <label><input type="checkbox" id="listened"> I listened to the full audio, resolved all terminology exceptions, and verified this ground-truth reference.</label>
  </fieldset>
  <div class="help-note">
   Approval requires checking the box above and deciding on all proposed occurrences. When exported, the verified reference will be used for held-out evaluation scoring.
  </div>
 </section>
</div>
</main>

<script>
window.__localReviewProposal = """ + proposal_json_str + """;
window.__localAgentTranscript = """ + transcript_json_str + """;
window.__kitAudioPath = '""" + audio_rel_path + """';

(function(){
"use strict";
const $ = id => document.getElementById(id);
let state = null, selected = null, filterMode = "all", objectUrl = null, replayStart = null, replayEnd = null;
let mergeIds = new Set();
let transcriptDraft = null;
const audio = $("player");

function stamp(seconds){
 const n = Math.max(0, Math.round(Number(seconds) || 0));
 return [Math.floor(n/3600), Math.floor(n/60)%60, n%60]
 .map((x,i) => i === 0 ? String(x) : String(x).padStart(2, "0"))
 .filter((x,i,arr) => i > 0 || x !== "0").join(":");
}

function parseTime(value){
 const s = String(value || "").trim();
 if(!s) return null;
 if(/^\\d+(\\.\\d+)?$/.test(s)) return Number(s);
 if(!/^\\d{1,2}:\\d\\d(?::\\d\\d)?$/.test(s)) return NaN;
 const p = s.split(":").map(Number);
 return p.reduce((a,b) => a * 60 + b, 0);
}

function currentAbsolute(){ return Number(audio.currentTime) || 0; }
function status(msg){ $("status").textContent = msg; }

function seekTo(pos, end){
 if(!audio.src){ status("Audio not loaded."); return; }
 const local = Math.max(0, Number(pos) - 1.0);
 audio.currentTime = local;
 replayStart = local;
 replayEnd = Math.max(local + 1.5, Number(end) + 1.2);
 audio.play().catch(() => status("Audio playback started."));
}

function normalizeProposalToState(data){
 if(data.review_session && Array.isArray(data.term_groups)){
   return JSON.parse(JSON.stringify(data));
 }
 if(!Array.isArray(data.suggested_terms)) throw Error("Invalid proposal JSON.");
 return {
   review_session: true,
   episode_guid: data.episode_guid || "",
   episode_title: data.episode_title || "",
   window: data.window || {start: 0, end: 1848.89},
   audio_url: data.audio_url || "audio.mp3",
   suggested_missing: data.suggested_missing || [],
   listened: Boolean(data.terms_exhaustive),
   term_groups: data.suggested_terms.map((g, i) => ({
      id: i + 1,
      canonical: g.canonical || g.term || "",
      term: g.canonical || g.term || "",
      surface: g.surface || g.term || "",
      surfaces: g.surfaces || [g.surface || g.term || ""],
      kind: g.kind || "other",
      editorial_reason: g.editorial_reason || "",
      is_cross_script: Boolean(g.is_cross_script),
      uncertainty_flag: Boolean(g.uncertainty_flag),
      sources: g.sources || g.seen_in || [],
      occurrences: (g.occurrences || []).map((o, j) => ({
        id: j + 1,
        start: Number(o.start),
        end: Number(o.end),
        precision: o.timestamp_precision || o.precision || "asr_token_aligned",
        source_cue_id: o.source_cue_id || "",
        cue_start: Number(o.cue_start || o.start),
        cue_end: Number(o.cue_end || o.end),
        surface: o.surface || o.matched_text || g.canonical,
        matched_text: o.matched_text || o.surface || g.canonical,
        context: o.context || "",
        sources: o.sources || g.sources || [],
        hebrew_morphology: o.hebrew_morphology || null,
        state: o.state || "pending",
        manual: Boolean(o.manual),
        migrated_from: o.migrated_from || null,
        reassigned: Boolean(o.reassigned)
      }))
   }))
 };
}

function migrateReviewSession(savedSession, newProposal){
 const newState = normalizeProposalToState(newProposal);
 if(!savedSession) return newState;

 const savedGroups = savedSession.term_groups || savedSession.suggested_terms || [];
 if(!Array.isArray(savedGroups)) return newState;

 const savedOccs = [];
 for(const g of savedGroups){
  const canon = g.canonical || g.term || "";
  for(const o of (g.occurrences || [])){
    savedOccs.push({
      canonical: canon,
      kind: g.kind || "technical_concept",
      occ: o
    });
  }
 }

 let preservedDecisionsCount = 0;
 let remappedCount = 0;
 const remappedDetails = [];
 function cleanStr(s){ return (s || "").replace(/[^a-zA-Z0-9\u0590-\u05fe]/g, "").toLowerCase(); }

 function areCompatible(sCanon, sSurf, nCanon, nSurf, timeDiff, sameCue = false){
  const sC = cleanStr(sSurf);
  const nC = cleanStr(nSurf);
  const sCanonC = cleanStr(sCanon);
  const nCanonC = cleanStr(nCanon);

  if(!sC || !nC) return false;

  let surfaceCompat = false;
  if(sC === nC) surfaceCompat = true;
  else if(sC.includes(nC) || nC.includes(sC)) surfaceCompat = true;
  else {
    const sStem = sC.replace(/^[ובלמשכה]{1,3}-?/, "");
    const nStem = nC.replace(/^[ובלמשכה]{1,3}-?/, "");
    if(sStem && nStem && (sStem === nStem || sStem.includes(nStem) || nStem.includes(sStem))){
      surfaceCompat = true;
    }
  }

  let conceptCompat = false;
  if(sCanonC && nCanonC && sCanonC === nCanonC) conceptCompat = true;
  else if(sC && nCanonC && (sC.includes(nCanonC) || nCanonC.includes(sC))) conceptCompat = true;
  else if(nC && sCanonC && (nC.includes(sCanonC) || sCanonC.includes(nC))) conceptCompat = true;

  if(sameCue){
    if(surfaceCompat) return true;
    if(conceptCompat && timeDiff <= 1.5) return true;
    return false;
  }

  if(!surfaceCompat && !conceptCompat) return false;

  if(timeDiff > 2.5) return false;
  if(!(sC === nC || (sCanonC && sCanonC === nCanonC)) && timeDiff > 1.2) return false;

  return true;
 }

 const newOccsFlat = [];
 for(const group of newState.term_groups){
  for(const occ of group.occurrences){
    newOccsFlat.push({ group, occ });
  }
 }

 const matchCandidates = [];
 for(let nIdx = 0; nIdx < newOccsFlat.length; nIdx++){
  const n = newOccsFlat[nIdx];
  const nClean = cleanStr(n.occ.surface);
  for(let sIdx = 0; sIdx < savedOccs.length; sIdx++){
    const s = savedOccs[sIdx];
    const sClean = cleanStr(s.occ.surface);
    const timeDiff = Math.abs(Number(s.occ.start) - Number(n.occ.start));
    const sameCue = Boolean(
      s.occ.source_cue_id && n.occ.source_cue_id && s.occ.source_cue_id === n.occ.source_cue_id
    );

    if(!areCompatible(s.canonical, s.occ.surface, n.group.canonical, n.occ.surface, timeDiff, sameCue)){
      continue;
    }

    let score = 0.0;
    if(nClean && sClean){
      if(nClean === sClean) score += 100.0;
      else if(nClean.includes(sClean) || sClean.includes(nClean)) score += 50.0;
      else score += 30.0;
    }
    if(s.canonical && n.group.canonical && s.canonical.toLowerCase() === n.group.canonical.toLowerCase()){
      score += 25.0;
    }
    if(sameCue) score += 15.0;
    score -= timeDiff * 10.0;
    matchCandidates.push({ score, nIdx, sIdx });
  }
 }

 matchCandidates.sort((a, b) => b.score - a.score);
 const usedN = new Set();
 const usedS = new Set();
 for(const cand of matchCandidates){
  if(usedN.has(cand.nIdx) || usedS.has(cand.sIdx)) continue;
  usedN.add(cand.nIdx);
  usedS.add(cand.sIdx);

  const n = newOccsFlat[cand.nIdx];
  const s = savedOccs[cand.sIdx];
  const group = n.group;
  const occ = n.occ;
  const sOcc = s.occ;
  const isReassigned = Boolean(
    s.canonical &&
    group.canonical &&
    s.canonical.trim().toLowerCase() !== group.canonical.trim().toLowerCase()
  );

  if(isReassigned){
    occ.migrated_from = s.canonical;
    occ.reassigned = true;
    occ.reapproval_required = true;
    occ.state = "pending"; // Always require fresh decision on new association
    remappedCount++;

    if(sOcc.state === "rejected"){
      occ.previously_rejected_under = s.canonical;
      const histNote = `Previously rejected under '${s.canonical}' (requires fresh decision for '${group.canonical}').`;
      occ.notes = sOcc.notes ? `${sOcc.notes} [${histNote}]` : histNote;
    } else if(sOcc.state === "confirmed"){
      occ.previously_confirmed_under = s.canonical;
      if(sOcc.notes) occ.notes = sOcc.notes;
    } else {
      if(sOcc.notes) occ.notes = sOcc.notes;
    }

    remappedDetails.push(`"${occ.surface}" (${occ.source_cue_id}): ${s.canonical} → ${group.canonical} [was: ${sOcc.state}]`);
  } else {
    // Same concept: preserve user decision directly
    if(sOcc.state === "confirmed" || sOcc.state === "rejected"){
      occ.state = sOcc.state;
      preservedDecisionsCount++;
    }
    if(sOcc.notes) occ.notes = sOcc.notes;
  }
 }

 // Preserve manual additions
 for(const g of savedGroups){
  for(const o of (g.occurrences || [])){
    if(o.manual){
      const gCanon = g.canonical || g.term || "";
      let targetG = newState.term_groups.find(x => x.canonical.toLowerCase() === gCanon.toLowerCase());
      if(!targetG){
        targetG = {
          id: newState.term_groups.length + 1,
          canonical: gCanon,
          term: gCanon,
          surface: o.surface || gCanon,
          surfaces: [o.surface || gCanon],
          kind: g.kind || "technical_concept",
          editorial_reason: "Manual user addition.",
          is_cross_script: false,
          uncertainty_flag: false,
          sources: ["manual"],
          occurrences: []
        };
        newState.term_groups.push(targetG);
      }
      if(!targetG.occurrences.some(x => Math.abs(Number(x.start) - Number(o.start)) < 0.5)){
        targetG.occurrences.push(Object.assign({}, o));
        targetG.occurrences.sort((a,b) => a.start - b.start);
      }
    }
  }
 }

 if(savedSession.listened !== undefined){
   newState.listened = Boolean(savedSession.listened);
 }

 newState._migrationStats = {
   preservedDecisionsCount,
   remappedCount,
   remappedDetails
 };

 return newState;
}

function storageKey(){ return "podcast-review:" + (state?.episode_guid || "74"); }
function saveLocal(){
 try{
  localStorage.setItem(storageKey(), JSON.stringify(state));
 }catch(e){}
}

function loadData(data){
 if(data.review_session && Array.isArray(data.term_groups)){
   state = data;
 } else {
   state = normalizeProposalToState(data);
 }
 mergeIds.clear();
 selected = state.term_groups[0]?.id || null;
 $("listened").checked = Boolean(state.listened);
 render();
 renderMissing();
 saveLocal();
}

function renderMissing(){
 const root = $("missingSuggestions");
 root.replaceChildren();
 const suggestions = state?.suggested_missing || [];
 if(!suggestions.length) return;
 const title = document.createElement("p");
 title.textContent = "Overlooked candidates from machine inventories A/B (click to add):";
 root.append(title);
 for(const term of suggestions.slice(0, 25)){
  const b = document.createElement("button");
  b.className = "flat";
  b.style.margin = "2px";
  b.textContent = "+ " + term;
  b.onclick = () => { $("newTerm").value = term; $("newTerm").focus(); };
  root.append(b);
 }
}

function decide(group, occ, v){
 occ.state = v;
 saveLocal();
 render();
}

function count(){
 const oc = state.term_groups.flatMap(g => g.occurrences);
 const done = oc.filter(o => o.state !== "pending").length;
 $("counts").textContent = done + " / " + oc.length + " occurrences reviewed";
 $("bar").style.width = oc.length ? (100 * done / oc.length) + "%" : "0%";
}

function renderTerms(){
 const termRoot = $("terms");
 termRoot.replaceChildren();
 const search = $("search").value.trim().toLowerCase();
 
 const list = state.term_groups.filter(g => {
  if(search && !g.canonical.toLowerCase().includes(search) && !g.surfaces.some(s=>s.toLowerCase().includes(search))) return false;
  if(filterMode === "exceptions" && !g.uncertainty_flag && !g.is_cross_script) return false;
  if(filterMode === "migrated" && !g.occurrences.some(o => o.reassigned || o.migrated_from)) return false;
  if(filterMode === "pending" && g.occurrences.every(o => o.state !== "pending")) return false;
  return true;
 });

 for(const g of list){
  const container = document.createElement("div");
  container.className = "row";
  container.style.flexWrap = "nowrap";

  const pick = document.createElement("input");
  pick.type = "checkbox";
  pick.checked = mergeIds.has(g.id);
  pick.title = "Select to merge concepts";
  pick.onchange = () => { if(pick.checked) mergeIds.add(g.id); else mergeIds.delete(g.id); };

  const hasMigrated = g.occurrences.some(o => o.reassigned || o.migrated_from);
  const b = document.createElement("button");
  b.className = "term-item" + (selected === g.id ? " selected" : "") + (g.uncertainty_flag ? " has-uncertainty" : "") + (hasMigrated ? " has-migrated" : "");
  b.style.flex = "1";

  const left = document.createElement("span");
  left.className = "term-name";
  left.textContent = g.canonical;

  if(g.is_cross_script){
   const sub = document.createElement("div");
   sub.className = "sources";
   sub.textContent = "Hebrew: " + g.surfaces.slice(0, 3).join(", ");
   left.append(sub);
  }

  const right = document.createElement("span");
  const approved = g.occurrences.filter(o => o.state === "confirmed").length;
  const allDecided = g.occurrences.every(o => o.state !== "pending");
  right.className = "pill " + (allDecided ? "done" : "todo");
  right.textContent = approved + "/" + g.occurrences.length + (approved === g.occurrences.length && allDecided ? " ✓" : "");

  b.append(left, right);
  b.onclick = () => { selected = g.id; render(); };

  container.append(pick, b);
  termRoot.append(container);
 }

 if(!list.length){
  const p = document.createElement("p");
  p.className = "instructions";
  p.textContent = "No concepts match filter.";
  termRoot.append(p);
 }
}

function highlightInContext(context, term){
 if(!context) return "";
 const safeTerm = term.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
 const reg = new RegExp("(" + safeTerm + ")", "i");
 return context.replace(reg, "<mark>$1</mark>");
}

function renderDetail(){
 const group = state.term_groups.find(g => g.id === selected);
 $("detail").hidden = !group;
 $("empty").hidden = Boolean(group);
 if(!group) return;

 $("conceptHeader").textContent = group.canonical;
 $("editTerm").value = group.canonical;
 $("conceptKind").value = group.kind || "technical_concept";
 $("conceptReason").textContent = group.editorial_reason || "Verified against audio in corrected SRT.";
 $("occCountHeader").textContent = group.occurrences.length;

 const badgeBox = $("badgesContainer");
 badgeBox.replaceChildren();

 const kindBadge = document.createElement("span");
 kindBadge.className = "badge info";
 kindBadge.textContent = group.kind;
 badgeBox.append(kindBadge);

 if(group.is_cross_script){
  const csBadge = document.createElement("span");
  csBadge.className = "badge warn";
  csBadge.textContent = "Cross-Script Concept Linking";
  badgeBox.append(csBadge);
 }

 if(group.uncertainty_flag){
  const unBadge = document.createElement("span");
  unBadge.className = "badge warn";
  unBadge.textContent = "Needs Verification";
  badgeBox.append(unBadge);
 }

 const hasMigratedOcc = group.occurrences.some(o => o.migrated_from);
 if(hasMigratedOcc){
  const migBadge = document.createElement("span");
  migBadge.className = "badge success";
  migBadge.textContent = "Refined / Migrated Concept";
  badgeBox.append(migBadge);
 }

 $("surfacesList").innerHTML = "<strong>Observed spoken/written surfaces:</strong> " + group.surfaces.map(s=>`<code>${s}</code>`).join(", ");

 const list = $("occurrences");
 list.replaceChildren();

 for(const occ of group.occurrences.slice().sort((a,b) => a.start - b.start)){
  const row = document.createElement("div");
  row.className = "occ";

  const jump = document.createElement("button");
  jump.className = "seek";
  jump.textContent = stamp(occ.start);
  jump.title = "Play audio around " + stamp(occ.start);
  jump.onclick = () => seekTo(occ.start, occ.end);

  const detail = document.createElement("div");
  const surfRow = document.createElement("div");
  surfRow.style.fontWeight = "600";
  surfRow.dir = "auto";
  surfRow.innerHTML = `<span class="badge ${occ.precision.includes('aligned')?'success':'info'}">${occ.precision}</span> <code>${occ.surface}</code>`;
  
  if(occ.migrated_from){
    const migTag = document.createElement("span");
    if(occ.previously_rejected_under){
      migTag.className = "badge warn";
      migTag.style.background = "#55311e";
      migTag.style.color = "#ffd188";
      migTag.style.borderColor = "#995c2b";
      migTag.textContent = "⚠️ Prev. Rejected under " + occ.previously_rejected_under + " (Fresh decision required)";
    } else if(occ.reassigned && occ.state === "pending"){
      migTag.className = "badge warn";
      migTag.textContent = "⚠️ Reassigned from " + occ.migrated_from + " (Approval required)";
    } else if(occ.state === "confirmed"){
      migTag.className = "badge success";
      migTag.textContent = "✓ Reassigned from " + occ.migrated_from + " (Approved)";
    } else if(occ.state === "rejected"){
      migTag.className = "badge danger";
      migTag.textContent = "✕ Rejected under " + occ.migrated_from;
    } else {
      migTag.className = "badge info";
      migTag.textContent = "Migrated from " + occ.migrated_from;
    }
    surfRow.append(migTag);
  }

  const ctx = document.createElement("div");
  ctx.className = "context-box";
  ctx.dir = "auto";
  ctx.innerHTML = highlightInContext(occ.context, occ.surface);

  if(occ.previously_rejected_under){
    const histBox = document.createElement("div");
    histBox.className = "help-note";
    histBox.style.margin = "4px 0 6px";
    histBox.style.padding = "6px 8px";
    histBox.style.fontSize = "12px";
    histBox.style.background = "#331c18";
    histBox.style.borderColor = "#783b2e";
    histBox.style.color = "#fed7aa";
    histBox.innerHTML = `⚠️ <strong>Historical Review Evidence:</strong> This occurrence was previously marked <strong>Rejected</strong> under <em>${occ.previously_rejected_under}</em>. A fresh decision is required to determine whether it is valid for <strong>${group.canonical}</strong>.`;
    ctx.append(histBox);
  }

  if(occ.notes){
    const noteBox = document.createElement("div");
    noteBox.className = "help-note";
    noteBox.style.margin = "4px 0 6px";
    noteBox.style.padding = "6px 8px";
    noteBox.style.fontSize = "12px";
    noteBox.style.background = "#1b2a38";
    noteBox.style.borderColor = "#35526b";
    noteBox.style.color = "#c5e1f5";
    noteBox.textContent = "📝 Note: " + occ.notes;
    ctx.append(noteBox);
  }

  if(occ.state === "rejected" && occ.migrated_from && !occ.previously_rejected_under){
    const warnBox = document.createElement("div");
    warnBox.className = "help-note";
    warnBox.style.margin = "4px 0 6px";
    warnBox.style.padding = "6px 8px";
    warnBox.style.fontSize = "12px";
    warnBox.innerHTML = `⚠️ Was previously marked <strong>Rejected</strong> under <em>${occ.migrated_from}</em> (preserved). Please verify whether it is valid for <strong>${group.canonical}</strong>.`;
    ctx.append(warnBox);
  }

  const cueInfo = document.createElement("div");
  cueInfo.className = "sources";
  cueInfo.textContent = `${occ.source_cue_id} [${stamp(occ.cue_start)}–${stamp(occ.cue_end)}] · Sources: ${(occ.sources || []).join(", ")}`;

  detail.append(surfRow, ctx, cueInfo);

  const decision = document.createElement("div");
  decision.className = "occ-state";

  const approveLabel = document.createElement("label");
  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = occ.state === "confirmed";
  check.title = "Confirmed heard in audio";
  check.onchange = () => decide(group, occ, check.checked ? "confirmed" : "pending");
  approveLabel.append(check, document.createTextNode(" Heard"));

  const reject = document.createElement("button");
  reject.className = "flat reject";
  reject.setAttribute("aria-pressed", String(occ.state === "rejected"));
  reject.title = "Reject false occurrence";
  reject.textContent = occ.state === "rejected" ? "Rejected ✕" : "Reject";
  reject.onclick = () => decide(group, occ, occ.state === "rejected" ? "pending" : "rejected");

  decision.append(approveLabel, reject);
  row.append(jump, detail, decision);
  list.append(row);
 }
}

function render(){
 if(!state) return;
 count();
 renderTerms();
 renderDetail();
}

function download(name, data){
 const blob = new Blob([JSON.stringify(data, null, 2) + "\\n"], {type: "application/json"});
 const url = URL.createObjectURL(blob), a = document.createElement("a");
 a.href = url; a.download = name; a.click();
 setTimeout(() => URL.revokeObjectURL(url), 3000);
}

function setAudio(src){
 if(objectUrl){ URL.revokeObjectURL(objectUrl); objectUrl = null; }
 audio.src = src; audio.load();
 status("Audio loaded: " + src);
}

$("filterAll").onclick = () => { filterMode = "all"; render(); };
$("filterExceptions").onclick = () => { filterMode = "exceptions"; render(); };
$("filterMigrated").onclick = () => { filterMode = "migrated"; render(); };
$("filterPending").onclick = () => { filterMode = "pending"; render(); };

$("bulkApprove").onclick = () => {
 if(!state) return;
 let count = 0;
 for(const g of state.term_groups){
   if(!g.uncertainty_flag && !g.is_cross_script){
     for(const occ of g.occurrences){
       const isAmbiguousOrReassigned = Boolean(
         occ.reapproval_required ||
         occ.reassigned ||
         occ.migrated_from ||
         occ.previously_rejected_under ||
         occ.ambiguous
       );
       if(occ.state === "pending" && !isAmbiguousOrReassigned){
         occ.state = "confirmed";
         count++;
       }
     }
   }
 }
 saveLocal();
 render();
 status(`Bulk approved ${count} occurrences across unambiguous concepts (reassigned / re-approval items excluded).`);
};

function resetAllReviewedOccurrences(){
 if(!state) return;
 const reviewed = state.term_groups.flatMap(g => g.occurrences).filter(o => o.state === "confirmed" || o.state === "rejected").length;
 if(reviewed === 0){
   status("No reviewed occurrences to reset; all occurrences are already pending.");
   return;
 }
 if(typeof confirm === "function" && !confirm(`Reset all ${reviewed} reviewed occurrence(s) across all concepts back to pending?`)){
   return;
 }
 for(const g of state.term_groups){
   for(const occ of g.occurrences){
     if(occ.state === "confirmed" || occ.state === "rejected"){
       occ.state = "pending";
     }
   }
 }
 state.listened = false;
 if($("listened")) $("listened").checked = false;
 saveLocal();
 render();
 status(`Reset ${reviewed} occurrence(s) to pending.`);
}

$("resetOccurrences").onclick = resetAllReviewedOccurrences;
if($("resetAllOccurrences")) $("resetAllOccurrences").onclick = resetAllReviewedOccurrences;

$("approveTerm").onclick = () => {
 if(!state) return;
 const g = state.term_groups.find(x => x.id === selected);
 if(!g) return;
 g.occurrences.forEach(o => o.state = "confirmed");
 saveLocal();
 render();
 status(`All occurrences of '${g.canonical}' approved.`);
};

$("rejectTerm").onclick = () => {
 if(!state) return;
 const g = state.term_groups.find(x => x.id === selected);
 if(!g) return;
 g.occurrences.forEach(o => o.state = "rejected");
 saveLocal();
 render();
 status(`All occurrences of '${g.canonical}' rejected.`);
};

$("resetTerm").onclick = () => {
 if(!state) return;
 const g = state.term_groups.find(x => x.id === selected);
 if(!g) return;
 const reviewed = g.occurrences.filter(o => o.state === "confirmed" || o.state === "rejected").length;
 if(reviewed === 0){
   status(`No reviewed occurrences to reset for '${g.canonical}'.`);
   return;
 }
 g.occurrences.forEach(o => o.state = "pending");
 state.listened = false;
 if($("listened")) $("listened").checked = false;
 saveLocal();
 render();
 status(`Reset ${reviewed} occurrence(s) of '${g.canonical}' to pending.`);
};

$("applyTerm").onclick = () => {
 if(!state) return;
 const g = state.term_groups.find(x => x.id === selected);
 const canonical = $("editTerm").value.trim();
 if(!canonical){ status("Concept name cannot be empty."); return; }
 g.canonical = canonical;
 g.term = canonical;
 g.kind = $("conceptKind").value;
 saveLocal();
 render();
 status("Saved concept metadata.");
};

$("addOccurrence").onclick = () => {
 if(!state) return;
 const g = state.term_groups.find(x => x.id === selected);
 const raw = $("addAt").value.trim();
 const n = raw ? parseTime(raw) : currentAbsolute();
 if(n === null || !Number.isFinite(n) || n < 0){ status("Enter valid time in seconds or MM:SS."); return; }
 g.occurrences.push({
   id: Date.now(),
   start: Math.round(n * 100) / 100,
   end: Math.round((n + 1.0) * 100) / 100,
   precision: "manual_exact",
   source_cue_id: "manual",
   cue_start: n, cue_end: n + 1.0,
   surface: g.canonical,
   matched_text: g.canonical,
   context: "Manual occurrence added at " + stamp(n),
   sources: ["manual"],
   state: "confirmed",
   manual: true
 });
 g.occurrences.sort((a,b) => a.start - b.start);
 $("addAt").value = "";
 saveLocal();
 render();
 status("Added new occurrence.");
};

$("addTerm").onclick = () => {
 if(!state) return;
 const text = $("newTerm").value.trim();
 if(!text){ status("Enter concept name."); return; }
 const raw = $("newTime").value.trim();
 const n = raw ? parseTime(raw) : currentAbsolute();
 let g = state.term_groups.find(x => x.canonical.toLowerCase() === text.toLowerCase());
 if(!g){
   g = {
     id: Math.max(0, ...state.term_groups.map(x=>x.id)) + 1,
     canonical: text, term: text, surface: text, surfaces: [text],
     kind: "technical_concept", editorial_reason: "Manual user addition.",
     is_cross_script: false, uncertainty_flag: false,
     sources: ["manual"], occurrences: []
   };
   state.term_groups.push(g);
 }
 if(n !== null && Number.isFinite(n)){
   g.occurrences.push({
     id: Date.now(),
     start: n, end: n + 1.0,
     precision: "manual_exact",
     source_cue_id: "manual",
     cue_start: n, cue_end: n + 1.0,
     surface: text, matched_text: text,
     context: "Manual term added at " + stamp(n),
     sources: ["manual"], state: "confirmed", manual: true
   });
 }
 selected = g.id;
 $("newTerm").value = ""; $("newTime").value = "";
 saveLocal();
 render();
 status("Added term: " + text);
};

$("resetSession").onclick = () => {
 if(!confirm("Reset will discard your local progress cache and reload the fresh unedited proposals. Are you sure?")) return;
 const key = "podcast-review:" + (window.__localReviewProposal.episode_guid || "74");
 try{ localStorage.removeItem(key); }catch(e){}
 loadData(window.__localReviewProposal);
 $("migrationNotice").hidden = true;
 status("Reset to clean AI proposals.");
};

$("listened").onchange = e => {
 if(!state) return;
 state.listened = e.target.checked;
 saveLocal();
};

$("exportSession").onclick = () => {
 if(!state) return;
 state.listened = $("listened").checked;
 download("review-" + (state.episode_guid || "74") + ".json", state);
 status("Review session saved.");
};

$("exportRef").onclick = () => {
 if(!state) return;
 const pending = state.term_groups.flatMap(g => g.occurrences).filter(o => o.state === "pending").length;
 const exhaustive = $("listened").checked && pending === 0;
 const confirmedGroups = state.term_groups.filter(g => g.occurrences.some(o => o.state === "confirmed"));
 
 const terms = [...new Set(confirmedGroups.map(g => g.canonical))];
 const confirmedOccs = confirmedGroups.flatMap(g => g.occurrences.filter(o => o.state === "confirmed").map(o => ({
   term: g.canonical,
   surface: o.surface,
   canonical: g.canonical,
   kind: g.kind,
   start: o.start,
   end: o.end,
   timestamp_precision: o.precision,
   source_cue_id: o.source_cue_id,
   source_models: o.sources,
   hebrew_morphology: o.hebrew_morphology,
   review_status: "verified"
 })));

 const refOut = {
   protocol_layer: "C",
   episode_guid: state.episode_guid,
   episode_title: state.episode_title,
   window: state.window,
   technical_terms: terms,
   reference_text: transcriptDraft ? transcriptDraft.turns.map(t => t.text).join(" ") : "",
   review_status: exhaustive ? "approved" : "pending",
   terms_exhaustive: exhaustive,
   verified_occurrences: confirmedOccs,
   concept_mentions: confirmedOccs.map((o, i) => ({
     id: "mention-" + String(i + 1).padStart(4, "0"),
     turn_id: o.source_cue_id,
     start_s: o.start,
     end_s: o.end,
     surface: o.surface,
     canonical: o.canonical,
     kind: o.kind,
     aliases: [],
     review_status: "verified",
     provenance: {
       models: o.source_models,
       timestamp_alignment: o.timestamp_precision
     }
   })),
   review_timestamp: new Date().toISOString()
 };

 download("reference_terms.approved.json", refOut);
 status(exhaustive ? "Approved ground-truth reference exported!" : "Provisional reference exported (status: pending). Mark approval checkbox to approve.");
};

$("back2").onclick = () => { audio.currentTime = Math.max(0, audio.currentTime - 2); };
$("forward2").onclick = () => { audio.currentTime = Math.min(audio.duration || Infinity, audio.currentTime + 2); };

audio.ontimeupdate = () => {
 $("clock").textContent = stamp(currentAbsolute());
 if(replayEnd !== null && audio.currentTime >= replayEnd){
   if($("loop").checked){ audio.currentTime = replayStart; }
   else { audio.pause(); replayStart = null; replayEnd = null; }
 }
};

$("search").oninput = () => { if(state) renderTerms(); };

document.addEventListener("keydown", e => {
 if(["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
 if(e.key === " "){
   if(audio.paused) audio.play(); else audio.pause();
   e.preventDefault();
 } else if(e.key === "ArrowLeft"){
   audio.currentTime = Math.max(0, audio.currentTime - 2);
   e.preventDefault();
 } else if(e.key === "ArrowRight"){
   audio.currentTime = Math.min(audio.duration || Infinity, audio.currentTime + 2);
   e.preventDefault();
 } else if(e.key === "j" || e.key === "ArrowDown"){
   const idx = state.term_groups.findIndex(x => x.id === selected);
   if(idx !== -1 && idx < state.term_groups.length - 1){
     selected = state.term_groups[idx + 1].id;
     render();
   }
   e.preventDefault();
 } else if(e.key === "k" || e.key === "ArrowUp"){
   const idx = state.term_groups.findIndex(x => x.id === selected);
   if(idx > 0){
     selected = state.term_groups[idx - 1].id;
     render();
   }
   e.preventDefault();
 } else if(e.key === "a"){
   $("approveTerm").click();
   e.preventDefault();
 } else if(e.key === "r"){
   $("rejectTerm").click();
   e.preventDefault();
 } else if(e.key === "u"){
   if($("resetTerm")) $("resetTerm").click();
   e.preventDefault();
 }
});

// File upload handler with automatic migration
$("proposal").onchange = e => {
 const file = e.target.files?.[0];
 if(!file) return;
 const reader = new FileReader();
 reader.onload = ev => {
   try {
     const imported = JSON.parse(ev.target.result);
     const migrated = migrateReviewSession(imported, window.__localReviewProposal);
     loadData(migrated);
     const stats = migrated._migrationStats;
     showMigrationBanner(stats);
     status(`Loaded session file: ${stats?.preservedDecisionsCount || 0} decisions preserved.`);
   } catch(err) {
     status("Error loading session file: " + err.message);
   }
 };
 reader.readAsText(file);
};

$("audioFile").onchange = e => {
 const file = e.target.files?.[0];
 if(!file) return;
 if(objectUrl){ URL.revokeObjectURL(objectUrl); }
 objectUrl = URL.createObjectURL(file);
 setAudio(objectUrl);
};

function showMigrationBanner(stats){
 const notice = $("migrationNotice");
 if(!stats || (!stats.preservedDecisionsCount && !stats.remappedCount)){
   notice.hidden = true;
   return;
 }
 notice.hidden = false;
 notice.innerHTML = `<strong>Review Progress Restored & Migrated:</strong> 
   Preserved <strong>${stats.preservedDecisionsCount}</strong> reviewed decisions. 
   Remapped <strong>${stats.remappedCount}</strong> occurrences from broad parent groups to refined specific concepts (e.g. <code>AGENTS.md</code>, <code>Subagent</code>, <code>Agentic search</code>, <code>Agent harness</code>) — <em>reassigned occurrences require renewed approval</em>. 
   Use the <em>Migrated & Reassigned</em> filter to inspect and approve them.`;
}

// Initialize with embedded proposal and transcript
try{
 const original = window.__localReviewProposal;
 const key = "podcast-review:" + (original.episode_guid || "74");
 let cached = null;
 try{
   const raw = localStorage.getItem(key);
   if(raw) cached = JSON.parse(raw);
 }catch(e){}

 if(cached){
   const migrated = migrateReviewSession(cached, original);
   loadData(migrated);
   showMigrationBanner(migrated._migrationStats);
   status(`Restored review session: ${migrated._migrationStats?.preservedDecisionsCount || 0} decisions preserved; ${migrated._migrationStats?.remappedCount || 0} occurrences migrated.`);
 } else {
   loadData(original);
   status(`Loaded ground-truth terminology reference for Episode 74 (${state.term_groups.length} concepts, ${state.term_groups.flatMap(g=>g.occurrences).length} occurrences).`);
 }

 if(window.__localAgentTranscript?.turns){
  transcriptDraft = window.__localAgentTranscript;
 }
 if(window.__kitAudioPath){
  setAudio(window.__kitAudioPath);
 }
}catch(err){
 status("Initialization error: " + err.message);
}

window.migrateReviewSession = migrateReviewSession;
window.loadData = loadData;
window.__reviewEngine = {
 migrateReviewSession,
 loadData,
 getState: () => state,
 bulkApprove: () => $("bulkApprove").onclick(),
 resetReviewedOccurrences: resetAllReviewedOccurrences
};

})();
</script>
</body>
</html>
"""
    return html_template


def generate_evaluation_review_html(eval_dir: Path) -> Path:
    """Read proposed terminology JSON and agent transcript JSON, generate self-contained review.html."""
    proposal_path = eval_dir / "reference_terms.proposed.json"
    transcript_path = eval_dir / "reference_transcript.agent_ready.json"
    out_path = eval_dir / "review.html"

    if not proposal_path.exists():
        raise FileNotFoundError(f"Missing proposal JSON: {proposal_path}")
    if not transcript_path.exists():
        raise FileNotFoundError(f"Missing transcript JSON: {transcript_path}")

    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    html_content = build_review_html(proposal, transcript, audio_rel_path="audio.mp3")
    out_path.write_text(html_content, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", required=True, type=Path, help="Path to evaluation directory")
    args = parser.parse_args()
    out = generate_evaluation_review_html(args.eval_dir)
    print(f"Generated review HTML at: {out}")
