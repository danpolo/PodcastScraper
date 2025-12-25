
import json
from pathlib import Path

DATA_DIR = Path(r"c:/Users/danpo/Documents/Programing/PodcastScraper/AI Thinkers podcast data")
MANIFEST_PATH = DATA_DIR / "manifest.json"

def fix_manifest():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    episodes = manifest["episodes"]
    
    # 1. Merge "כשעיצוב פוגש קוד" duplicates
    yt_id = "b8d-g3VT9aE"
    sb_id = "substack:post:179427589"
    
    if sb_id in episodes and yt_id in episodes:
        print(f"Merging {sb_id} into {yt_id}")
        episodes[yt_id]["has_description"] = True
        episodes[yt_id]["has_transcript"] = True
        episodes[yt_id]["title"] = "כשעיצוב פוגש קוד עם חן ויצמן" # Fixed typo
        del episodes[sb_id]
        
    # 2. Merge "רועי זלטא" duplicates
    yt_id_roey = "zta5ZCy1vUI"
    sb_id_roey = "substack:post:178368507"
    if sb_id_roey in episodes and yt_id_roey in episodes:
        print(f"Merging {sb_id_roey} into {yt_id_roey}")
        episodes[yt_id_roey]["has_description"] = True
        episodes[yt_id_roey]["has_transcript"] = True
        del episodes[sb_id_roey]

    # Save
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Manifest fixed.")

if __name__ == "__main__":
    fix_manifest()
