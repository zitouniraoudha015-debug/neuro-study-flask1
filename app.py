"""Neuro-Study — point d'entrée Flask (pages + API JSON)."""
import html
import json
import os
import re
import tempfile
import hashlib
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.error import HTTPError
import requests

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

from services import ai_service as ai, pdf_service as pdf, youtube_service as yt, translate_service as tr
from services.captions import clean_captions, clean_line
from services.profiles import PROFILES, STYLES
from services.session_store import store
from services.history_store import history

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
BASE = os.path.dirname(__file__)

# --- Cache : désactivé par défaut pour que CSS/JS/HTML se mettent à jour au simple rechargement.
# En production, mettre NO_CACHE=0 dans .env pour réactiver le cache navigateur.
NO_CACHE = os.getenv("NO_CACHE", "1") != "0"
if NO_CACHE:
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0      # fichiers /static : Cache-Control: no-cache
    app.config["TEMPLATES_AUTO_RELOAD"] = True       # recharge index.html même sans debug
    app.jinja_env.auto_reload = True


@app.context_processor
def asset_version():
    """Ajoute ?v=<date de modification> aux CSS/JS : le navigateur recharge dès que le fichier change."""
    def static_v(filename):
        try:
            v = int(os.path.getmtime(os.path.join(BASE, "static", filename)))
        except OSError:
            v = 0
        return f"/static/{filename}?v={v}"
    return {"static_v": static_v}

ILLUSTRATION_CACHE = {}

extension_state = {
    "connected": False,
    "last_seen": None,
    "platform": None,
    "title": None,
    "url": None,
    "last_caption": "",
    "attention_score": None,
}


ALLOWED_ORIGIN = re.compile(r"^(chrome-extension://[a-p]{32}|https?://(127\.0\.0\.1|localhost)(:\d+)?)$")


@app.before_request
def block_foreign_origins():
    """Un site tiers ne peut pas utiliser vos clés IA : on refuse toute écriture venant d'une autre origine."""
    origin = request.headers.get("Origin")
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and origin and not ALLOWED_ORIGIN.match(origin):
        return jsonify(error="Origine non autorisée."), 403


@app.before_request
def ignore_conditional_static():
    """Ignore If-Modified-Since / If-None-Match sur /static : jamais de 304, toujours le fichier à jour."""
    if NO_CACHE and request.path.startswith("/static/"):
        request.environ.pop("HTTP_IF_MODIFIED_SINCE", None)
        request.environ.pop("HTTP_IF_NONE_MATCH", None)


@app.after_request
def disable_cache(response):
    """Pas de cache sur les pages et les fichiers statiques (ni 304 périmés)."""
    if NO_CACHE and (request.path.startswith("/static/") or response.mimetype == "text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers.pop("ETag", None)
        response.headers.pop("Last-Modified", None)
    return response


@app.after_request
def attach_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if ALLOWED_ORIGIN.match(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


def body():
    return request.get_json(silent=True) or {}


def profile_of(d):
    return d.get("profile") if d.get("profile") in PROFILES else "standard"


def chunk_of(p):
    return PROFILES.get(p, PROFILES["standard"])["chunk_words"]


def demo_file(name):
    with open(os.path.join(BASE, "demo_data", name), encoding="utf-8") as f:
        return f.read()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    prov = ai.configured_providers()
    return jsonify(ok=True, llm=bool(prov), has_ai=bool(prov), providers=prov, errors=ai.last_errors(),
                   model=ai._gemini_ok["model"],
                   hint=None if prov else "Aucune IA configurée : ajoutez une clé gratuite (GEMINI_API_KEY) dans le fichier .env puis relancez le serveur.")


@app.get("/api/llm/test")
def llm_test():
    """Diagnostic : essaie réellement vos fournisseurs IA et dit lequel répond (ou pourquoi aucun)."""
    r = ai.ask_ex("Réponds exactement : OK", max_tokens=20, timeout=15, priority=True)
    configured = ai.configured_providers()
    hint = None
    if not configured:
        hint = "Aucune clé IA trouvée. Créez le fichier .env (copie de .env.example) et mettez GEMINI_API_KEY=votre_clé."
    elif not r["text"]:
        hint = "Une clé est présente mais aucun modèle ne répond : lisez le message d'erreur ci-dessus (clé invalide, quota, modèle retiré…)."
    return jsonify(ok=bool(r["text"]), provider=r["provider"], model=ai._gemini_ok["model"] if r["provider"] == "gemini" else None,
                   answer=r["text"], errors=r["errors"], configured=configured, hint=hint)


@app.post("/api/subtitle")
def api_subtitle():
    d = body()
    r = ai.subtitle(
        d.get("text", ""),
        str(d.get("source", "fr"))[:2],
        d.get("target", "fr"),
        profile_of(d),
    )
    if r.get("subtitle"):
        store.add_transcript(d.get("t", 0), r["subtitle"])
    return jsonify(r)


@app.post("/api/translate_batch")
def api_translate_batch():
    """Traduit plusieurs phrases d'un coup (sous-titres) vers fr / en / ar. Utilisé pour précharger les sous-titres d'une vidéo."""
    d = body()
    texts = d.get("texts")
    if not isinstance(texts, list):
        return jsonify(error="« texts » doit être une liste."), 400
    texts = [str(t)[:1200] for t in texts[:40]]
    target = str(d.get("target") or "fr").lower()
    target = target if target in ai.LANGS else "fr"
    profile = profile_of(d)
    hint = ai.HINTS.get(profile, "") if profile != "standard" else ""
    r = tr.translate_batch(texts, target, hint)
    out = [ai.adapt(it["translation"], profile, target) for it in r["items"]]
    return jsonify(translations=out, items=r["items"], provider=r["provider"], fallback=r["fallback"],
                   errors=r["errors"], target=target)


@app.post("/api/catchup")
def api_catchup():
    d = body()
    return jsonify(ai.catchup(d.get("context", "")[:3000], profile_of(d)))


@app.post("/api/micropulse")
def api_micropulse():
    return jsonify(ai.micropulse(body().get("text", "")[:3000]))


@app.post("/api/simplify")
def api_simplify():
    d = body()
    return jsonify(ai.simplify(d.get("text", "")[:3000], profile_of(d)))


def _lost_context(d):
    """Assemble ce qui vient d'être dit : transcription YouTube autour de l'instant + sous-titres captés par l'extension."""
    parts, t = [], d.get("current_time")
    t = float(t) if isinstance(t, (int, float)) else None
    vid = yt.video_id(d.get("video_id") or "")
    if vid and t is not None:
        try:
            parts.append(yt.window(yt.cached_transcript(vid), t, before=75, after=3))
        except Exception:
            pass
    caps = d.get("captions")
    lines = []
    if isinstance(caps, list):
        for c in clean_captions(caps):
            ct = c.get("t")
            stamp = f"[{int(ct) // 60}:{int(ct) % 60:02d}] " if isinstance(ct, (int, float)) else ""
            who = f"{c['speaker']} : " if c.get("speaker") else ""
            lines.append(f"{stamp}{who}{c['text']}")
        if lines and not (parts and parts[0]):          # la transcription complète prime, sinon sous-titres captés
            parts.append("\n".join(lines))
    if not lines:                                       # ancien format : texte brut, nettoyé du bruit d'interface
        parts.append("\n".join(x for x in (clean_line(l) for l in str(d.get("context") or "").splitlines()) if x))
    if not any(p.strip() for p in parts):
        parts.append(clean_line(extension_state.get("last_caption")) or store.full_text()[-2500:])
    return "\n".join(p for p in parts if p.strip())


@app.route("/api/lost", methods=["POST", "OPTIONS"])
def api_lost():
    """« Je suis perdu » : repère le point non compris, l'explique (texte, schéma, courbe, image) et l'enregistre."""
    if request.method == "OPTIONS":
        return ("", 204)
    d = body()
    target = str(d.get("target") or "fr").strip().lower()
    prof = profile_of(d)
    t = d.get("current_time")
    t = float(t) if isinstance(t, (int, float)) else None
    title = str(d.get("source_title") or extension_state.get("title") or "").strip()

    live = str(d.get("platform") or "").lower() == "meet" or bool(d.get("live"))     # réunion en direct : pas de pause possible
    focus = str(d.get("focus") or "").strip()[:120]            # terme précisé par l'étudiant (facultatif)
    old = history.get(str(d["replace_id"])) if d.get("replace_id") else None
    old_res = (old or {}).get("result") or {}
    attempt = int(d.get("attempt") or 0) or (int(old_res.get("attempt") or 1) + 1 if old else 1)
    previous = str(d.get("previous") or "")[:500] or (old_res.get("paragraph") or "")[:500] or None
    focus = focus or (old or {}).get("focus", "")

    ctx = _lost_context(d)[:4000]
    if live and not focus and len(re.sub(r"\W+", "", ctx)) < 12:
        # Réunion en direct sans aucun sous-titre capté : inutile d'inventer, on dit quoi faire.
        return jsonify(needs_input=True, error="Aucun sous-titre capté dans la réunion. Activez les sous-titres (CC) de Meet, "
                       "ou écrivez dans la case « Sur quoi es-tu perdu(e) ? » (par exemple : écart-type) puis recliquez.")
    result = ai.explain_when_lost(
        context=ctx, target=target, profile=prof, source_title=title,
        current_time=t, previous=previous, attempt=attempt, focus=focus, live=live,
    )
    store.add_point(t if t is not None else "Live", 30, result["point"][:60], True)

    source = {"platform": d.get("platform"), "title": title, "url": d.get("url"),
              "video_id": yt.video_id(d.get("video_id") or "") or ""}
    versions = list((old or {}).get("versions") or [])
    if old:                          # « Expliquer autrement » : on garde l'ancienne explication dans « autres versions »
        versions.append({"attempt": int(old_res.get("attempt") or 1), "created_at": old.get("created_at"),
                         **{k: old_res.get(k, "") for k in ("point", "paragraph", "analogy", "example")}})
        history.delete(old["id"])
    entry = history.add(source, t, result, target, prof, versions=versions[-6:], live=live, focus=focus)
    return jsonify({**result, "id": entry["id"], "created_at": entry["created_at"], "video_time": t,
                    "live": live, "versions": entry["versions"]})


@app.get("/api/history")
def api_history():
    return jsonify(items=history.list(int(request.args.get("limit", 200))))


@app.post("/api/history/<entry_id>/understood")
def api_history_understood(entry_id):
    e = history.set_understood(entry_id, body().get("understood", True))
    return (jsonify(e), 200) if e else (jsonify(error="Introuvable."), 404)


@app.route("/api/history/<entry_id>", methods=["DELETE", "OPTIONS"])
def api_history_delete(entry_id):
    if request.method == "OPTIONS":
        return ("", 204)
    return jsonify(ok=history.delete(entry_id))


@app.route("/api/history/<entry_id>/translate", methods=["POST", "OPTIONS"])
def api_history_translate(entry_id):
    """Relire un point non compris dans une autre langue (fr / en / ar). Résultat gardé pour ne pas retraduire."""
    if request.method == "OPTIONS":
        return ("", 204)
    e = history.get(entry_id)
    if not e:
        return jsonify(error="Introuvable."), 404
    target = str(body().get("target") or "fr").lower()
    if target not in ai.LANGS:
        return jsonify(error="Langue inconnue."), 400
    if target == e.get("target"):
        return jsonify(fields=None, same=True)
    cached = (e.get("translations") or {}).get(target)
    if cached:
        return jsonify(fields=cached, cached=True)
    fields, res = ai.translate_result(e["result"], target, e.get("profile", "standard"))
    history.set_translation(entry_id, target, fields)
    return jsonify(fields=fields, provider=res["provider"], fallback=res["fallback"])


@app.post("/api/history/clear")
def api_history_clear():
    history.clear()
    return jsonify(ok=True)


@app.get("/history")
def history_page():
    return render_template("history.html", items=history.list())


@app.route("/api/extension/heartbeat", methods=["POST", "OPTIONS"])
def api_extension_heartbeat():
    if request.method == "OPTIONS":
        return ("", 204)
    d = body()
    att_score = d.get("attention_score")
    extension_state.update(
        {
            "connected": True,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "platform": d.get("platform"),
            "title": d.get("title"),
            "url": d.get("url"),
            "last_caption": d.get("last_caption") or extension_state.get("last_caption", ""),
            "attention_score": (
                att_score
                if isinstance(att_score, (int, float))
                else extension_state.get("attention_score")
            ),
        }
    )
    if isinstance(att_score, (int, float)):
        store.add_point("Ext", float(att_score), "Caméra extension", False)
    return jsonify(ok=True)


@app.get("/api/extension/status")
def api_extension_status():
    active = False
    if extension_state["last_seen"]:
        try:
            dt = datetime.fromisoformat(extension_state["last_seen"])
            active = (datetime.now(timezone.utc) - dt).total_seconds() <= 8.0
        except Exception:
            active = False
    return jsonify({**extension_state, "connected": active})


@app.post("/api/pdf")
def api_pdf():
    f = request.files.get("file")
    if not f:
        return jsonify(error="Aucun fichier reçu."), 400
    text = pdf.extract_text(f)
    if not text.strip():
        return jsonify(error="Aucun texte trouvé (PDF scanné ?). Essayez un PDF texte ou un .txt."), 422
    return jsonify(sections=pdf.to_sections(text, chunk_of(request.form.get("profile"))))


@app.get("/api/pdf/demo")
def api_pdf_demo():
    return jsonify(sections=pdf.to_sections(demo_file("sample_course.txt"), chunk_of(request.args.get("profile"))))


@app.get("/api/demo")
def api_demo():
    return app.response_class(demo_file("sample_meet.json"), mimetype="application/json")


@app.post("/api/youtube/transcript")
def api_youtube():
    d = body()
    vid = yt.video_id(d.get("url", ""))
    if not vid:
        return jsonify(error="Lien YouTube invalide."), 400
    text = (d.get("text") or "").strip()
    if text:
        return jsonify(video_id=vid, segments=yt.from_text(text[:60000]), source="manuel")
    try:
        segs = yt.fetch_transcript(vid)
    except ImportError:
        return jsonify(error="Installez : pip install youtube-transcript-api"), 501
    except Exception:
        segs = []
    if not segs:
        return jsonify(error="Transcription indisponible pour cette vidéo. Utilisez « Coller une transcription »."), 422
    return jsonify(video_id=vid, segments=segs, source="youtube")


@app.post("/api/session/point")
def session_point():
    d = body()
    store.add_point(d.get("t", 0), d.get("attention", 0), str(d.get("label", ""))[:60], d.get("lost", False))
    return jsonify(ok=True)


@app.get("/api/session/summary")
def api_session_summary():
    summary = dict(store.summary())
    summary["comprehension_score"] = store.comprehension()
    return jsonify(summary)


@app.post("/api/session/reset")
def session_reset():
    store.reset()
    return jsonify(ok=True)


@app.get("/api/profiles")
def api_profiles():
    return jsonify(profiles=PROFILES, styles=STYLES)


@app.post("/api/illustration")
def api_illustration():
    """Récupère une image pédagogique Wikipédia uniquement après une demande explicite."""
    d = body()
    title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip()[:120]
    context = re.sub(r"\s+", " ", str(d.get("context") or "")).strip()[:300]
    if not title:
        return jsonify(error="Titre de la notion manquant."), 400
    key = hashlib.sha1(f"{title}|{context}".encode("utf-8")).hexdigest()
    if key in ILLUSTRATION_CACHE:
        return jsonify(**ILLUSTRATION_CACHE[key])

    headers = {"User-Agent": "NeuroStudy/1.0 (educational application)"}
    candidates = [title]
    first_words = title.split()
    if len(first_words) > 6:
        candidates.append(" ".join(first_words[:6]))

    for query in candidates:
        try:
            summary_url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{quote(query, safe='')}"
            r = requests.get(summary_url, headers=headers, timeout=8)
            if not r.ok:
                continue
            data = r.json()
            image = data.get("thumbnail", {}).get("source") or data.get("originalimage", {}).get("source")
            description = data.get("description") or data.get("extract") or ""
            if image:
                result = {
                    "ok": True,
                    "image": image,
                    "title": data.get("title") or query,
                    "caption": description[:220],
                    "source": "Wikipédia",
                }
                if len(ILLUSTRATION_CACHE) >= 100:
                    ILLUSTRATION_CACHE.pop(next(iter(ILLUSTRATION_CACHE)))
                ILLUSTRATION_CACHE[key] = result
                return jsonify(**result)
        except Exception:
            continue

    result = {
        "ok": False,
        "error": "Aucune image pédagogique fiable n’a été trouvée pour cette notion. Vous pouvez continuer avec le texte.",
    }
    return jsonify(**result), 404


@app.post("/api/lesson")
def api_lesson():
    d = body()
    return jsonify(ai.lesson(d.get("text", "")[:4000], profile_of(d), d.get("style", "visuel"), str(d.get("title", ""))[:120]))


@app.post("/api/checklist")
def api_checklist():
    d = body()
    return jsonify(ai.checklist(d.get("task", "")[:2000], profile_of(d)))


@app.post("/api/gaps")
def api_gaps():
    d = body()
    return jsonify(ai.gaps(d.get("text", "")[:3000], profile_of(d)))


@app.post("/api/pack")
def api_pack():
    d = body()
    text = (d.get("text") or store.full_text()).strip()
    if not text:
        return jsonify(error="Aucune transcription dans la séance."), 422
    return jsonify(ai.pack(text, profile_of(d)))


@app.post("/api/reexplain")
def api_reexplain():
    d = body()
    ctx = store.near(float(d.get("t", 0))) or d.get("context", "")
    return jsonify(ai.reexplain(str(d.get("notion", ""))[:60], ctx[:3000], profile_of(d)))


@app.post("/api/board")
def api_board():
    f = request.files.get("image")
    if not f:
        return jsonify(error="Aucune image."), 400
    try:
        return jsonify(text=ai.board(f.read(), f.mimetype or "image/jpeg", request.form.get("profile", "standard")))
    except RuntimeError:
        return jsonify(error="La lecture du tableau demande une clé GEMINI_API_KEY dans .env."), 501
    except Exception:
        return jsonify(error="Lecture du tableau impossible pour le moment."), 502


@app.get("/api/visual")
def api_visual():
    return jsonify(ai.visual(request.args.get("q", "")[:60]))


@app.post("/api/session/meta")
def session_meta():
    d = body()
    store.set_meta(source=d.get("source", ""), title=d.get("title", ""), url=d.get("url", ""))
    return jsonify(ok=True)


@app.post("/api/transcribe")
def transcribe():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return jsonify(error="faster-whisper non installé : utilisez la Web Speech API."), 501
    f = request.files.get("audio")
    if not f:
        return jsonify(error="Aucun audio."), 400
    if not hasattr(transcribe, "model"):
        transcribe.model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny"), compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=".webm") as tmp:
        f.save(tmp.name)
        segs, _ = transcribe.model.transcribe(tmp.name, vad_filter=True)
        return jsonify(text=" ".join(s.text.strip() for s in segs))


@app.errorhandler(413)
def too_big(_):
    return jsonify(error="Fichier trop volumineux (15 Mo max)."), 413


@app.errorhandler(Exception)
def on_error(e):
    code = getattr(e, "code", 500)
    return jsonify(error=str(getattr(e, "description", e))), code if isinstance(code, int) else 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG", "0") == "1")