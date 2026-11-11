"""Laedt eingereihte Videos zu YouTube hoch. Laeuft in GitHub Actions; die Zugangsdaten kommen aus den Repository-Secrets
YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN und werden nie ausgegeben.

Auftrag: queue/<id>.json = {"id", "branch", "video", "thumb", "sha256", "when", "meta": {"title", "description", "tags", "categoryId", "lang"}}
  branch = Branch dieses Repositorys, in dem Video und Vorschaubild liegen (Standard: handoff-quiz)
  when = ISO-Zeit mit Versatz (wird zu diesem Termin oeffentlich; liegt sie schon in der Vergangenheit: sofort oeffentlich),
         "sofort" (sofort oeffentlich) oder "privat" (bleibt privat, fuer Tests)
Die Mediendateien holt das Skript selbst aus dem genannten Branch. Nummerierte Branches (handoff-quiz-...) werden nach
erfolgreichem Upload geloescht, damit das Repository klein bleibt.
Ergebnis: results/<id>.json (Erfolg, wird nie zweimal hochgeladen) oder results/<id>.fehler.json (Grund des Fehlschlags).
"""
import hashlib, json, os, re, subprocess, sys, tempfile, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

KANAL = "UCr0YDQrupcIcmU_y8vv67SA"      # @BirdParadiseTube - es wird nur auf diesen Kanal hochgeladen
API = "https://youtube.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
RAW = "https://raw.githubusercontent.com/" + os.environ.get("GITHUB_REPOSITORY", "ShraTTT/big-bet-videos")

class Fehler(Exception):
    pass

def call(url, data=None, headers=None, method=None, want_headers=False):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read()
            return (r.headers, body) if want_headers else body
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(txt); err = j.get("error")
            reason = err.get("message") if isinstance(err, dict) else f"{err}: {j.get('error_description', '')}"
        except Exception:
            reason = txt[:200]
        raise Fehler(f"{urllib.parse.urlsplit(url).netloc} antwortet {e.code}: {reason}")
    except urllib.error.URLError as e:
        raise Fehler(f"{urllib.parse.urlsplit(url).netloc} nicht erreichbar ({e.reason})")

def token():
    c = {k: os.environ.get(k, "").strip() for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")}
    missing = [k for k, v in c.items() if not v]
    if missing: raise Fehler("Secret fehlt im Repository: " + ", ".join(missing))
    body = urllib.parse.urlencode({"client_id": c["YT_CLIENT_ID"], "client_secret": c["YT_CLIENT_SECRET"],
                                   "refresh_token": c["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    j = json.loads(call("https://oauth2.googleapis.com/token", body, {"Content-Type": "application/x-www-form-urlencoded"}))
    if "access_token" not in j: raise Fehler("Google hat keinen Zugang ausgestellt")
    print(f"::add-mask::{j['access_token']}")
    return j["access_token"]

def kanal(tok):
    j = json.loads(call(f"{API}/channels?part=snippet,status,contentDetails&mine=true", headers={"Authorization": f"Bearer {tok}"}))
    items = j.get("items") or []
    if not items: raise Fehler("Der Zugang gehoert zu keinem YouTube-Kanal (bei der Freigabe den Kanal Bird Paradise waehlen)")
    ch = items[0]
    if ch["id"] != KANAL: raise Fehler(f"Zugang gehoert zu Kanal {ch['id']}, erwartet {KANAL} - nichts hochgeladen")
    return ch["snippet"]["title"], ch["contentDetails"]["relatedPlaylists"]["uploads"], ch.get("status", {}).get("longUploadsStatus", "?")

def schon_da(tok, uploads, title):
    """Sucht den Titel unter den letzten Uploads, damit nach einem Abbruch nichts doppelt hochgeladen wird."""
    j = json.loads(call(f"{API}/playlistItems?part=snippet&maxResults=15&playlistId={uploads}", headers={"Authorization": f"Bearer {tok}"}))
    for it in j.get("items", []):
        if it["snippet"]["title"].strip() == title.strip():
            return it["snippet"]["resourceId"]["videoId"]
    return None

def holen(branch, name, dest):
    """Laedt eine Datei aus einem Branch dieses (oeffentlichen) Repositorys."""
    if not re.fullmatch(r"[\w.\-]+", name) or not re.fullmatch(r"[\w.\-/]+", branch): raise Fehler("Unzulaessiger Datei- oder Branchname im Auftrag")
    r = subprocess.run(["curl", "-sSfL", "--retry", "3", "-m", "900", "-o", str(dest), f"{RAW}/{branch}/{name}"], capture_output=True, text=True)
    if r.returncode != 0 or not dest.exists(): raise Fehler(f"Datei {name} im Branch {branch} nicht gefunden")
    return dest

def pruefsumme(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""): h.update(block)
    return h.hexdigest()

def hochladen(tok, job, media):
    meta = job["meta"]; branch = job.get("branch", "handoff-quiz"); media.mkdir(exist_ok=True)
    video = holen(branch, job["video"], media / job["video"])
    if video.stat().st_size < 100000: raise Fehler("Videodatei ist leer")
    if job.get("sha256") and pruefsumme(video) != job["sha256"]:
        raise Fehler(f"Videodatei passt nicht zum Auftrag (Pruefsumme) - Branch {branch} wurde inzwischen ueberschrieben")
    status = {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(meta.get("synthetic", True))}
    when = job.get("when", "privat")
    if when == "sofort": status["privacyStatus"] = "public"
    elif when == "privat": status["privacyStatus"] = "private"
    else:
        t = datetime.fromisoformat(when)
        if t.tzinfo is None: raise Fehler("Sendetermin braucht einen Zeitversatz, z. B. +01:00")
        if (t - datetime.now(timezone.utc)).total_seconds() < 600: status["privacyStatus"] = "public"      # Termin (fast) vorbei -> sofort
        else:
            status["privacyStatus"] = "private"; status["publishAt"] = t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"snippet": {"title": meta["title"][:100], "description": meta["description"][:4900], "tags": meta.get("tags", []),
                        "categoryId": str(meta.get("categoryId", 27)), "defaultLanguage": meta.get("lang", "de")}, "status": status}
    hdr, _ = call(f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status", json.dumps(body).encode("utf-8"),
                  {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                   "X-Upload-Content-Length": str(video.stat().st_size), "X-Upload-Content-Type": "video/mp4"}, want_headers=True)
    session = hdr.get("Location")
    if not session: raise Fehler("YouTube hat keine Upload-Sitzung geoeffnet")
    with tempfile.NamedTemporaryFile("w", suffix=".hdr", delete=False) as f:
        os.chmod(f.name, 0o600); f.write(f"Authorization: Bearer {tok}\nContent-Type: video/mp4\n"); hf = f.name
    try:
        r = subprocess.run(["curl", "-sS", "--fail-with-body", "-m", "1500", "-T", str(video), "-H", f"@{hf}", session], capture_output=True, text=True)
    finally:
        os.unlink(hf)
    if r.returncode != 0: raise Fehler("Upload abgebrochen: " + (r.stdout or r.stderr)[:300].replace(tok, "***"))
    vid = json.loads(r.stdout).get("id")
    if not vid: raise Fehler("YouTube hat keine Video-Nummer zurueckgegeben")
    res = {"id": job["id"], "videoId": vid, "url": f"https://www.youtube.com/watch?v={vid}", "privacy": status["privacyStatus"],
           "publishAt": status.get("publishAt"), "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "thumbnail": "keins"}
    if job.get("thumb"):
        try:
            tp = holen(branch, job["thumb"], media / job["thumb"])
        except Fehler:
            tp = None
        if tp is not None:
            req = urllib.request.Request(f"{UPLOAD}/thumbnails/set?videoId={vid}&uploadType=media", data=tp.read_bytes(),
                                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"}, method="POST")
            try:
                urllib.request.urlopen(req, timeout=120).read(); res["thumbnail"] = "ok"
            except urllib.error.HTTPError as e:
                res["thumbnail"] = f"abgelehnt (HTTP {e.code}) - Kanal per Telefon bestaetigen: youtube.com/verify"
        else:
            res["thumbnail"] = "Datei fehlt"
    if re.fullmatch(r"handoff-quiz-[\w\-]+", branch):     # nummerierter Branch: nach dem Upload entfernen
        subprocess.run(["git", "push", "-q", "origin", "--delete", branch], capture_output=True)
    return res

def main():
    root = Path("."); media = Path(tempfile.mkdtemp()); (root / "results").mkdir(exist_ok=True)
    jobs = [p for p in sorted((root / "queue").glob("*.json")) if not (root / "results" / p.name).exists()]
    if not jobs:
        print("Keine offenen Auftraege."); return 0
    bad = 0; tok = None
    for p in jobs:
        errfile = root / "results" / (p.stem + ".fehler.json")
        try:
            job = json.loads(p.read_text())
            if job.get("id") != p.stem: raise Fehler("id im Auftrag passt nicht zum Dateinamen")
            if tok is None:
                tok = token(); title, uploads, long_ok = kanal(tok); print(f"Kanal: {title}, lange Videos: {long_ok}")
            vid = schon_da(tok, uploads, job["meta"]["title"])
            if vid:
                res = {"id": job["id"], "videoId": vid, "url": f"https://www.youtube.com/watch?v={vid}", "note": "war bereits hochgeladen - nicht doppelt gesendet"}
            else:
                res = hochladen(tok, job, media)
            (root / "results" / p.name).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
            if errfile.exists(): errfile.unlink()
            print(f"{job['id']}: {res['url']} ({res.get('privacy', '')}{', ' + res['publishAt'] if res.get('publishAt') else ''}; Vorschaubild: {res.get('thumbnail', '-')})")
        except Exception as e:
            bad += 1
            msg = str(e) if isinstance(e, Fehler) else f"{type(e).__name__}: {e}"
            errfile.write_text(json.dumps({"id": p.stem, "error": msg, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, ensure_ascii=False, indent=1) + "\n")
            print(f"::error::{p.stem}: {msg}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
