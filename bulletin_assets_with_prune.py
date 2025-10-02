import os, io, json, csv, base64, hashlib, datetime
from pathlib import Path
import requests
from PIL import Image
import pillow_avif  # registers AVIF decoding
from slugify import slugify
import argparse

# ================== CONFIG ==================
OWNER  = "LogunLACC"
REPO   = "lacc-bulletin-assets"          # GitHub Pages repo name
BRANCH = "main"
PAGES_BASE = f"https://{OWNER}.github.io/{REPO}"

INPUT_JSON  = "events.json"              # input file with "image" fields (AVIF URLs)
OUTPUT_JSON = "updated_events.json"      # output with added "image_jpg" URLs
MAP_CSV     = "image_map.csv"            # convenience mapping

MANIFEST_PATH = "manifest.json"          # committed at repo root

MAX_WIDTH     = 1200                     # resize to this width (email-friendly), 0 = no resize
JPEG_QUALITY  = 88

# Pin folders/files from deletion (prefix match, repo-relative)
PROTECT_PREFIXES = [
    "img/static/",       # example pinned folder; change/remove as you like
]

# ============================================

def now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def sha8(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]

def month_folder_from_date(datestr: str) -> str:
    # "Sat, 06 Sep 2025" -> "2025/09"
    try:
        parts = datestr.strip().split()
        year = parts[-1]
        mon  = parts[2]
        months = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
                  'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
        return f"{year}/{months.get(mon,'00')}"
    except Exception:
        return "undated"

def to_jpg_bytes(data: bytes) -> bytes:
    im = Image.open(io.BytesIO(data))
    if MAX_WIDTH and im.width > MAX_WIDTH:
        h = int((MAX_WIDTH / im.width) * im.height)
        im = im.resize((MAX_WIDTH, h), Image.LANCZOS)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue()

def gh_headers():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN environment variable.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

def gh_get_sha(path: str):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    r = requests.get(url, headers=gh_headers(), timeout=30)
    if r.status_code == 200:
        return r.json().get("sha")
    return None

def gh_put_file(path: str, content_bytes: bytes, message: str):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    # If file exists, include its sha to update
    sha = gh_get_sha(path)
    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(url, headers=gh_headers(), json=payload, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"PUT {path} failed: {resp.status_code} {resp.text}")

def gh_delete_file(path: str, message: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[DRY-RUN] Would delete: {path}")
        return True
    sha = gh_get_sha(path)
    if not sha:
        return False
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    payload = {"message": message, "sha": sha, "branch": BRANCH}
    r = requests.delete(url, headers=gh_headers(), json=payload, timeout=60)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Delete failed for {path}: {r.status_code} {r.text}")
    return True

def load_manifest() -> dict:
    # Try to read manifest from the repo (raw view). If missing, start fresh.
    raw_url = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{MANIFEST_PATH}"
    r = requests.get(raw_url, timeout=20)
    if r.status_code == 200:
        try:
            return json.loads(r.text)
        except Exception:
            pass
    return {"images": {}}   # maps path -> record

def save_manifest(manifest: dict):
    content = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    gh_put_file(MANIFEST_PATH, content, "Update manifest.json (auto)")

def is_protected(path: str) -> bool:
    for pref in PROTECT_PREFIXES:
        if path.startswith(pref):
            return True
    return False

def process_events(input_json: str, updated_json: str, map_csv: str):
    with open(input_json, "r", encoding="utf-8") as f:
        events = json.load(f)

    manifest = load_manifest()
    images = manifest.setdefault("images", {})

    now = now_iso()
    seen_paths = set()
    rows = [["index","title","original_image","final_jpg_url","status"]]
    updated_events = []

    for i, ev in enumerate(events):
        src = ev.get("image")
        title = ev.get("title") or ""
        date  = ev.get("date") or ""
        if not src:
            rows.append([i, title, "", "", "no_image"])
            updated_events.append(ev)
            continue
        try:
            r = requests.get(src, timeout=30)
            r.raise_for_status()
            jpg = to_jpg_bytes(r.content)

            stem = slugify(title)[:60] or "img"
            fname = f"{stem}-{sha8(src)}.jpg"
            subdir = month_folder_from_date(date)
            rel_path = f"img/{subdir}/{fname}"       # path in repo
            public_url = f"{PAGES_BASE}/{rel_path}"

            gh_put_file(rel_path, jpg, f"Add/Update {fname}")
            ev["image_jpg"] = public_url
            rows.append([i, title, src, public_url, "ok"])
            updated_events.append(ev)

            rec = images.get(rel_path, {"first_added": now, "title": title, "source": src})
            rec["last_seen"] = now
            rec["title"] = title or rec.get("title")
            rec["source"] = src
            images[rel_path] = rec
            seen_paths.add(rel_path)

        except Exception as e:
            ev["image_jpg_error"] = str(e)
            rows.append([i, title, src, "", f"error: {e}"])
            updated_events.append(ev)

    with open(updated_json, "w", encoding="utf-8") as f:
        json.dump(updated_events, f, ensure_ascii=False, indent=2)
    with open(map_csv, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    return manifest, seen_paths

def prune_old(manifest: dict, seen_paths: set, retention_days: int, dry_run: bool = False):
    cutoff_dt = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
    cutoff_iso = cutoff_dt.replace(microsecond=0).isoformat() + "Z"

    to_delete = []
    for path, rec in list(manifest.get("images", {}).items()):
        last_seen = rec.get("last_seen")
        if is_protected(path):
            continue
        # delete only if not seen this run AND last_seen older than cutoff
        if path not in seen_paths and last_seen and last_seen < cutoff_iso:
            to_delete.append(path)

    deleted = []
    for path in to_delete:
        if gh_delete_file(path, f"Prune unused asset (> {retention_days}d): {path}", dry_run=dry_run):
            deleted.append(path)
            if not dry_run:
                manifest["images"].pop(path, None)

    return deleted

def main():
    parser = argparse.ArgumentParser(description="Upload JPGs to GitHub Pages, update JSON, and prune old files.")
    parser.add_argument("--input", default=INPUT_JSON, help="Path to events.json")
    parser.add_argument("--output", default=OUTPUT_JSON, help="Path to write updated_events.json")
    parser.add_argument("--mapcsv", default=MAP_CSV, help="Path to write image_map.csv")
    parser.add_argument("--prune", action="store_true", help="Prune unused assets")
    parser.add_argument("--retention", type=int, default=60, help="Retention days before deletion (default: 60)")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions (no actual delete)")
    args = parser.parse_args()

    manifest, seen_paths = process_events(args.input, args.output, args.mapcsv)

    deleted = []
    if args.prune:
        deleted = prune_old(manifest, seen_paths, args.retention, dry_run=args.dry_run)
        print(f"{'(DRY-RUN) ' if args.dry_run else ''}Prune candidates deleted: {len(deleted)}")
        if args.dry_run and deleted:
            for p in deleted:
                print("  -", p)

    # Always save manifest (so last_seen gets recorded). In dry-run, we still update manifest for new/seen files.
    save_manifest(manifest)
    print(f"Finished. Wrote {args.output} and {args.mapcsv}. {len(deleted)} file(s) {'would be ' if args.dry_run else ''}deleted.")

if __name__ == "__main__":
    main()
