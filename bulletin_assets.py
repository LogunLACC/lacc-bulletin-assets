import os, io, json, base64, hashlib
from pathlib import Path
import requests
from PIL import Image
import pillow_avif  # registers AVIF
from slugify import slugify

# --- Config ---
OWNER = "LogunLACC"
REPO  = "lacc-bulletin-assets"
BRANCH = "main"
PAGES  = f"https://{OWNER}.github.io/{REPO}"
IN_JSON  = "events.json"
OUT_JSON = "updated_events.json"
MAX_W = 1200
Q = 88

def sha8(s): return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]

def month_folder(date_str):
    # "Sat, 06 Sep 2025" -> "2025/09"
    try:
        parts = date_str.split()
        y, mon = parts[-1], parts[2]
        m = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
             'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}[mon]
        return f"{y}/{m}"
    except: return "undated"

def to_jpg(data: bytes) -> bytes:
    im = Image.open(io.BytesIO(data))
    if MAX_W and im.width > MAX_W:
        im = im.resize((MAX_W, int(im.height*MAX_W/im.width)), Image.LANCZOS)
    if im.mode not in ("RGB","L"): im = im.convert("RGB")
    out = io.BytesIO(); im.save(out, "JPEG", quality=Q, optimize=True, progressive=True)
    return out.getvalue()

def gh_headers():
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok: raise RuntimeError("Set GITHUB_TOKEN env var.")
    return {"Authorization": f"Bearer {tok}", "Accept":"application/vnd.github+json"}

def gh_put(path: str, content: bytes, message: str):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    r = requests.get(url, headers=gh_headers(), timeout=30)
    sha = r.json().get("sha") if r.status_code==200 else None
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode(),
        "branch": BRANCH
    }
    if sha: payload["sha"] = sha
    x = requests.put(url, headers=gh_headers(), json=payload, timeout=60)
    x.raise_for_status()

def main():
    events = json.load(open(IN_JSON, "r", encoding="utf-8"))
    out = []
    for ev in events:
        url = ev.get("image"); title = ev.get("title") or ""; date = ev.get("date") or ""
        if not url:
            out.append(ev); continue
        try:
            raw = requests.get(url, timeout=30); raw.raise_for_status()
            jpg = to_jpg(raw.content)
            stem = slugify(title)[:60] or "img"
            fname = f"{stem}-{sha8(url)}.jpg"
            rel = f"img/{month_folder(date)}/{fname}"
            gh_put(rel, jpg, f"Add/Update {fname}")
            ev["image_jpg"] = f"{PAGES}/{rel}"
        except Exception as e:
            ev["image_jpg_error"] = str(e)
        out.append(ev)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Done. Wrote {OUT_JSON}")

if __name__ == "__main__":
    main()
