import json
from pathlib import Path
import re

DATA_DIR = Path(r"c:/Users/danpo/Documents/Programing/PodcastScraper/AI Thinkers podcast data")
MANIFEST_PATH = DATA_DIR / "manifest.json"

def normalize_title(t):
    if not t: return ""
    # Remove special chars and normalize spaces
    # The original normalize_title also removed '׳' and "'"
    t = t.replace('׳', '').replace("'", "")
    # Remove problematic characters for filenames and normalize spaces
    t = re.sub(r'[\\/*?:\"<>|]', "", t)
    # Replace multiple spaces with a single space and convert to lowercase
    return " ".join(t.split()).strip().lower()

def cleanup():
    if not MANIFEST_PATH.exists():
        print("Manifest not found.")
        return

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    episodes = manifest.get("episodes", {})
    
    # 1. Group and Merge
    processed_ids = set()
    merged_episodes = {}

    ids = list(episodes.keys())
    
    for i in range(len(ids)):
        eid1 = ids[i]
        if eid1 in processed_ids: continue
        
        entry1 = episodes[eid1]
        t1_norm = normalize_title(entry1['title'])
        t1_words = set(t1_norm.split())
        
        current_group = [(eid1, entry1)]
        processed_ids.add(eid1)
        
        for j in range(i + 1, len(ids)):
            eid2 = ids[j]
            if eid2 in processed_ids: continue
            
            entry2 = episodes[eid2]
            t2_norm = normalize_title(entry2['title'])
            t2_words = set(t2_norm.split())
            
            if not t1_words or not t2_words: continue
            
            # Intersection over union (words)
            overlap = len(t1_words & t2_words)
            score = overlap / min(len(t1_words), len(t2_words))
            
            if score > 0.5: # 50% word overlap is usually enough for these titles
                current_group.append((eid2, entry2))
                processed_ids.add(eid2)

        # Merge the group
        # Preference: YouTube ID (not starting with substack:)
        youtube_ids = [eid for eid, _ in current_group if not eid.startswith("substack:")]
        best_eid = youtube_ids[0] if youtube_ids else current_group[0][0]
        
        # Merge flags and find best title (usually the non-substack one or longer one)
        has_desc = any(e["has_description"] for _, e in current_group)
        has_trans = any(e["has_transcript"] for _, e in current_group)
        last_upd = max(e["last_updated"] for _, e in current_group)
        
        # Pick the most descriptive title (not starting with 🧠 unless it's the only one)
        titles = [e["title"] for _, e in current_group]
        best_title = titles[0]
        for t in titles:
            if not t.startswith("🧠") and len(t) > len(best_title):
                best_title = t
        
        merged_episodes[best_eid] = {
            "title": best_title,
            "clean_title": best_title, # Let it be cleaned by scraper next run
            "has_description": has_desc,
            "has_transcript": has_trans,
            "last_updated": last_upd
        }

    # Update manifest
    manifest["episodes"] = merged_episodes
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Consolidated manifest from {len(episodes)} to {len(merged_episodes)} entries.")

    # 2. Files cleanup based on consolidated manifest
    files_to_keep = set()
    for eid, entry in merged_episodes.items():
        # Consistent filename generation
        clean = re.sub(r'[\\/*?:\"<>|]', "", entry["title"])
        clean = " ".join(clean.split()).strip()
        files_to_keep.add(f"{clean}.md")

    # 2. Cleanup files
    for f in DATA_DIR.glob("*.md"):
        if f.name == "מה יש פה בעצם.md": # Trailer
            continue
        if f.name not in files_to_keep:
            print(f"Deleting redundant file: {f.name}")
            f.unlink()

if __name__ == "__main__":
    cleanup()
