"""YouTube : extraction de l'ID, transcription (youtube-transcript-api), segments prêts à synchroniser."""
import re
import time

ID = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/|live/)([A-Za-z0-9_-]{11})")


def video_id(url):
    url = (url or "").strip()
    m = ID.search(url)
    if m:
        return m.group(1)
    return url if re.fullmatch(r"[A-Za-z0-9_-]{11}", url) else None


def clean(raw, min_secs=6, min_chars=80):
    """Fusionne les mini-segments (~2 s) en blocs d'environ 6 s : moins d'appels IA, sous-titres plus lisibles."""
    out, cur = [], None
    for s in raw:
        txt = re.sub(r"\s+", " ", str(s["text"]).replace("\n", " ")).strip()
        if not txt:
            continue
        if cur is None:
            cur = {"start": round(float(s["start"]), 1), "text": txt}
        else:
            cur["text"] += " " + txt
        if float(s["start"]) - cur["start"] >= min_secs or len(cur["text"]) >= min_chars:
            out.append(cur); cur = None
    if cur:
        out.append(cur)
    return out


def fetch_transcript(vid, langs=("fr", "en", "ar")):
    from youtube_transcript_api import YouTubeTranscriptApi   # ImportError géré par la route
    try:                                                     # versions récentes (1.x)
        api = YouTubeTranscriptApi()
        try:
            tr = api.fetch(vid, languages=list(langs))
        except Exception:                                    # langue demandée absente → première piste disponible
            tr = next(iter(api.list(vid))).fetch()
        raw = [{"start": s.start, "text": s.text} for s in tr]
    except (AttributeError, TypeError):                      # anciennes versions
        raw = YouTubeTranscriptApi.get_transcript(vid, languages=list(langs))
    return clean(raw)


_cache = {}   # vid -> (horodatage, segments)


def cached_transcript(vid, ttl_ok=6 * 3600, ttl_fail=300):
    """Transcription mise en cache (réussite 6 h, échec 5 min). [] si indisponible."""
    now = time.time()
    hit = _cache.get(vid)
    if hit and now - hit[0] < (ttl_ok if hit[1] else ttl_fail):
        return hit[1]
    try:
        segs = fetch_transcript(vid)
    except Exception:
        segs = []
    _cache[vid] = (now, segs)
    return segs


def window(segs, t, before=75, after=0):
    """Segments entre t-before et t+after, formatés « [mm:ss] texte » (le plus récent en bas)."""
    out = [s for s in segs if t - before <= s["start"] <= t + after]
    return "\n".join(f"[{int(s['start']) // 60}:{int(s['start']) % 60:02d}] {s['text']}" for s in out)


def from_text(text, step=5):
    """Transcription collée à la main : on répartit les phrases toutes les `step` secondes."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    return [{"start": i * step, "text": p} for i, p in enumerate(parts)]
