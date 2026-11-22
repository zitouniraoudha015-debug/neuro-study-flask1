"""IA : sous-titres/traduction, Catch-Up 15 s, Micro-Pulse, simplification par profil.
Chaque fonction a un repli déterministe : la démo fonctionne sans clé ni réseau."""
import html
import json
import os
import re
import time
import hashlib
from urllib.parse import quote
import base64
import requests

from .pdf_service import keywords, sentences, find_definition, key_terms
from .profiles import PROFILES, LITERAL, qualitative_numbers, literalize, has_math
from . import translate_service as tr
from . import knowledge

TIMEOUT = float(os.getenv("LLM_TIMEOUT", "8"))
_cache, _down = {}, {}          # cache de réponses ; fournisseurs en panne (disjoncteur 60 s)
LANGS = {"fr": "français", "en": "anglais", "ar": "arabe"}
SYSTEM = ("Tu es l'assistant pédagogique de Neuro-Study. Réponds uniquement avec le texte demandé, "
          "sans préambule ni commentaire.")
HINTS = {k: v["prompt"] for k, v in PROFILES.items()}                         # extension (Meet / YouTube)
SITE_HINTS = {k: v.get("prompt_site", v["prompt"]) for k, v in PROFILES.items()}   # site (cours écrits / PDF)
DERJA = {"chnowa": "quoi", "barcha": "beaucoup", "yesser": "beaucoup", "mouch": "pas", "lyoum": "aujourd'hui",
         "bech": "nous allons", "nechrhou": "expliquer", "fhemtou": "avez-vous compris", "fhemt": "compris",
         "mouchkla": "problème", "ya3ni": "c'est-à-dire", "kifech": "comment", "3lech": "pourquoi",
         "taw": "maintenant", "behi": "d'accord", "el": "le", "awel": "premier", "haja": "chose", "hiya": "c'est",
         "houwa": "c'est", "mta3": "de", "wost": "milieu", "a9des": "combien", "mbaajdin": "éloignées",
         "tla3": "monte", "tnez": "descend", "wa7da": "l'une", "o5ra": "l'autre", "dima": "toujours",
         "na3mlou": "nous faisons", "kif": "comme", "w": "et", "famma": "il y a", "nheb": "je veux",
         "3andek": "tu as", "9olt": "j'ai dit", "enti": "tu", "ena": "je", "ahna": "nous", "yezzi": "assez",
         "sahit": "merci", "salam": "bonjour", "3aslema": "bonjour"}
QUALI = {"corrélation négative": "quand l'un monte, l'autre descend",
         "corrélation positive": "quand l'un monte, l'autre monte aussi",
         "écart-type": "à quel point les valeurs sont dispersées", "moyenne": "la valeur du milieu",
         "dérivée": "la vitesse à laquelle une valeur change", "probabilité": "la chance que cela arrive"}

LANGUAGE_INSTRUCTIONS = {
    "ar": (
        "Réponds en arabe clair, soigné et grammaticalement correct, "
        "avec une orthographe irréprochable et un vocabulaire accessible."
    ),
    "fr": (
        "Réponds en français clair, naturel et grammaticalement correct, "
        "avec une orthographe soignée et sans formulation approximative."
    ),
    "en": (
        "Respond in clear, natural, grammatically correct English "
        "with accurate spelling and accessible wording."
    ),
}


# ---------- Couche LLM multi-fournisseurs : cache + disjoncteur + diagnostic ----------
# Fournisseurs : gemini, openai (alias chatgpt), claude (alias anthropic), groq, ollama.
# Ordre = variable LLM_PROVIDER (ex. "openai,gemini,groq"). Un fournisseur sans clé est ignoré.
ALIASES = {"chatgpt": "openai", "anthropic": "claude"}
_ERRORS = {}                    # dernière erreur par fournisseur (visible via /api/health et /api/llm/test)
BREAKER_SECONDS = 20            # pause d'un fournisseur en erreur (ignorée pour « Je suis perdu »)


class HttpError(RuntimeError):
    """Erreur HTTP d'un fournisseur IA (garde le code et le corps pour décider : autre modèle ? autre fournisseur ?)."""

    def __init__(self, status, body):
        super().__init__(f"HTTP {status} : {body[:160]}")
        self.status, self.body = status, body


def _post(url, payload, headers=None, timeout=8):
    r = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
    if not r.ok:
        raise HttpError(r.status_code, r.text)
    return r.json()


_MODEL_GONE = re.compile(r"model|not found|decommission|deprecat|no longer|does not exist|unavailable", re.I)


def _try_models(models, fn):
    """Essaie les modèles dans l'ordre ; ne passe au suivant que si le modèle est introuvable / retiré."""
    models = [m for m in dict.fromkeys(models) if m]
    last = None
    for m in models:
        try:
            return fn(m)
        except HttpError as e:
            if e.status in (400, 403, 404) and _MODEL_GONE.search(e.body) and not re.search(r"api key|api_key", e.body, re.I):
                last = e
                continue
            raise
    raise last or RuntimeError("aucun modèle disponible")


# Gemini : les noms de modèles changent (gemini-2.5-flash répond 404 aux nouvelles clés depuis mi-2026).
# On essaie GEMINI_MODEL (s'il est défini), puis cette liste, puis on demande à Google la liste réelle.
GEMINI_DEFAULTS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
_GEM = "https://generativelanguage.googleapis.com/v1beta"
_gemini_ok = {"model": None}               # dernier modèle qui a répondu (essayé en premier ensuite)


def _gemini_call(model, key, prompt, system, max_tokens, json_mode, timeout):
    """Un appel à UN modèle. Le réglage de « réflexion » diffère selon la génération : on essaie les deux formes."""
    variants = ["budget0", None] if model.startswith("gemini-2.5") else ["minimal", None]
    last = None
    for v in variants:
        cfg = {"temperature": 0.3, "maxOutputTokens": max_tokens + (0 if v else 1500)}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        if v == "budget0":
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
        elif v == "minimal":
            cfg["thinkingConfig"] = {"thinkingLevel": "minimal"}
        try:
            j = _post(f"{_GEM}/models/{model}:generateContent",
                      {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": cfg}, {"x-goog-api-key": key}, timeout)
        except HttpError as e:
            if e.status == 400 and "think" in e.body.lower():
                last = e
                continue
            raise
        cand = (j.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [])
        if not text.strip():
            raise RuntimeError(f"réponse vide ({cand.get('finishReason', '?')})")
        return text
    raise last


def _gemini_discover(key, tried):
    """Demande à Google quels modèles « flash » existent vraiment pour cette clé (les plus récents d'abord)."""
    try:
        r = requests.get(f"{_GEM}/models", params={"pageSize": 200}, headers={"x-goog-api-key": key}, timeout=8)
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception:
        return []
    ok = [n for n in names if "flash" in n and n not in tried
          and not re.search(r"image|tts|live|audio|embed|robot|computer|exp", n)]
    ver = lambda n: float((re.search(r"gemini-(\d+(?:\.\d+)?)", n) or [0, 0])[1] or 0)
    return sorted(ok, key=lambda n: (-ver(n), "lite" in n))[:3]


def _gemini(prompt, system, max_tokens, json_mode, timeout):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    tried, last = [], None
    pool = [_gemini_ok["model"], os.getenv("GEMINI_MODEL", "").strip()] + GEMINI_DEFAULTS
    for stage in ("known", "discovered"):
        for model in ([m for m in dict.fromkeys(pool) if m] if stage == "known" else _gemini_discover(key, tried)):
            tried.append(model)
            try:
                out = _gemini_call(model, key, prompt, system, max_tokens, json_mode, timeout)
                _gemini_ok["model"] = model
                return out
            except HttpError as e:
                if e.status in (403, 404) and re.search(r"model", e.body, re.I) and not re.search(r"api key", e.body, re.I):
                    last = e
                    continue
                if e.status == 400 and re.search(r"not (found|supported)|no longer", e.body, re.I):
                    last = e
                    continue
                raise
    raise last or RuntimeError("aucun modèle Gemini disponible pour cette clé")


OPENAI_DEFAULTS = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini"]


def _openai(prompt, system, max_tokens, json_mode, timeout):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")   # compatible OpenRouter, LM Studio…

    def run(model):
        reasoning = model.startswith(("gpt-5", "o1", "o3", "o4"))
        payload = {"model": model, "max_completion_tokens": max_tokens + (1500 if reasoning else 0),
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if not reasoning:
            payload["temperature"] = 0.3
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        j = _post(f"{base}/chat/completions", payload, {"Authorization": f"Bearer {key}"}, timeout)
        return j["choices"][0]["message"]["content"]

    return _try_models([os.getenv("OPENAI_MODEL", "").strip()] + OPENAI_DEFAULTS, run)


def _claude(prompt, system, max_tokens, json_mode, timeout):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    j = _post(
        "https://api.anthropic.com/v1/messages",
        {"model": os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"), "max_tokens": max_tokens, "system": system,
         "messages": [{"role": "user", "content": prompt}]},
        {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
    return "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")


GROQ_DEFAULTS = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "openai/gpt-oss-20b"]


def _groq(prompt, system, max_tokens, json_mode, timeout):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None

    def run(model):
        payload = {"model": model, "temperature": 0.3, "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        j = _post("https://api.groq.com/openai/v1/chat/completions", payload, {"Authorization": f"Bearer {key}"}, timeout)
        return j["choices"][0]["message"]["content"]

    return _try_models([os.getenv("GROQ_MODEL", "").strip()] + GROQ_DEFAULTS, run)


def _ollama(prompt, system, max_tokens, json_mode, timeout):
    # Un modèle local met souvent > 30 s au 1er appel (chargement en mémoire) : délai propre à Ollama + modèle gardé chargé.
    timeout = max(float(timeout or 0), float(os.getenv("OLLAMA_TIMEOUT", "90")))
    payload = {"model": os.getenv("OLLAMA_MODEL", "llama3.2"), "stream": False,
               "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
               "options": {"num_predict": max_tokens, "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096"))},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if json_mode:
        payload["format"] = "json"
    j = _post(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat", payload, None, timeout)
    return j["message"]["content"]


PROVIDERS = {"gemini": _gemini, "openai": _openai, "claude": _claude, "groq": _groq, "ollama": _ollama}
KEY_VARS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY"}


def provider_order():
    names = [ALIASES.get(n.strip().lower(), n.strip().lower())
             for n in os.getenv("LLM_PROVIDER", "gemini,openai,claude,groq,ollama").split(",") if n.strip()]
    return [n for n in dict.fromkeys(names) if n in PROVIDERS]


_ollama_state = {"t": 0.0, "up": False}


def ollama_available():
    """Ollama local est-il lancé ? (test rapide, mémorisé 30 s)"""
    now = time.time()
    if now - _ollama_state["t"] > 30:
        try:
            requests.get(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags", timeout=0.6)
            up = True
        except Exception:
            up = False
        _ollama_state.update(t=now, up=up)
    return _ollama_state["up"]


def configured_providers():
    """Fournisseurs réellement utilisables : clé présente, ou Ollama local s'il tourne."""
    return [n for n in provider_order() if (ollama_available() if n == "ollama" else bool(os.getenv(KEY_VARS[n])))]


def has_ai():
    return bool(configured_providers())


def last_errors():
    return dict(_ERRORS)


def ask_ex(prompt, system=SYSTEM, *, json_mode=False, max_tokens=900, timeout=None, priority=False):
    """Interroge les fournisseurs dans l'ordre. Retourne {"text", "provider", "errors"} (text=None si tout échoue).
    priority=True : ignore le disjoncteur (utilisé par « Je suis perdu » : on tente TOUJOURS tous les modèles)."""
    k = hashlib.sha1(f"{system}|{json_mode}|{max_tokens}|{prompt}".encode()).hexdigest()
    if k in _cache:
        return {"text": _cache[k][0], "provider": _cache[k][1], "errors": {}, "cached": True}
    errors = {}
    for name in configured_providers():
        if not priority and _down.get(name, 0) > time.time():
            errors[name] = "en pause après une erreur récente"
            continue
        try:
            out = PROVIDERS[name](prompt, system, max_tokens, json_mode, timeout or TIMEOUT)
            if out is None:                      # pas de clé : on passe au suivant sans bruit
                continue
            if out.strip():
                _cache[k] = (out.strip(), name)
                if len(_cache) > 500:
                    _cache.pop(next(iter(_cache)))
                _ERRORS.pop(name, None)
                return {"text": out.strip(), "provider": name, "errors": errors}
            errors[name] = "réponse vide"
        except Exception as e:
            errors[name] = str(e)[:200]
            _ERRORS[name] = errors[name]
            _down[name] = time.time() + BREAKER_SECONDS
    return {"text": None, "provider": None, "errors": errors}


def ask(prompt, system=SYSTEM, **kw):
    """Retourne le texte du LLM ou None (→ repli local)."""
    return ask_ex(prompt, system, **kw)["text"]


def _json(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def _short(text, n):
    w = text.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def adapt(text, profile, lang="fr"):
    """Traitement propre au profil, appliqué à TOUTE sortie : chiffres → sens (dyscalculie), langage littéral (autisme).
    Ces règles sont écrites pour le français : dans une autre langue on laisse le texte tel quel (le LLM a déjà reçu
    la consigne du profil dans son prompt)."""
    if lang != "fr":
        return text
    cfg = PROFILES.get(profile, PROFILES["standard"])
    if cfg["qualitative"]:
        text = qualitative_numbers(text)
    if cfg["literal"]:
        text = literalize(text)
    return text


# ---------- Fonctions publiques ----------
def subtitle(text, source="fr", target="fr", profile="standard"):
    """Sous-titre TRADUIT dans la langue choisie (fr/en/ar). Chaîne : LLM → traducteur gratuit → dictionnaire derja."""
    text = (text or "").strip()
    target = target if target in LANGS else "fr"
    if not text:
        return {"subtitle": "", "original": "", "translation": "", "keywords": [], "fallback": False,
                "provider": None, "same": True, "target": target}
    hint = HINTS.get(profile, "") if profile != "standard" else ""
    r = tr.translate_batch([text], target, hint)
    it = r["items"][0]
    trans = adapt(it["translation"], profile, target)
    return {"subtitle": trans, "original": text, "translation": trans, "keywords": keywords(trans, 3),
            "fallback": r["fallback"], "provider": it["provider"], "same": it["same"], "target": target}


def catchup(context, profile="standard"):
    out = ask(
        f"Voici ce qui vient d'être dit en cours :\n{context}\n\nRésume en 2 phrases courtes (≈30 mots) "
        f"pour que l'étudiant retrouve le fil. {HINTS.get(profile, '')}"
    )
    if out:
        return {"text": adapt(out, profile), "fallback": False}
    return {"text": adapt(_short(" ".join(sentences(context)[-2:]), 35), profile), "fallback": True}


def micropulse(text):
    out = ask(
        f"Texte : {text}\nDonne UNIQUEMENT un JSON {{\"phrase\":\"phrase clé (max 15 mots)\","
        f"\"question\":\"question flash\",\"answer\":\"réponse courte\"}}"
    )
    d = _json(out)
    if d and all(k in d for k in ("phrase", "question", "answer")):
        return {**d, "fallback": False}
    term, sent, _ = find_definition(text)
    ss = sentences(text)
    phrase = re.sub(r"^•\s*", "", sent or (ss[0] if ss else text))
    kw = term or (key_terms(phrase, "", 1) or keywords(phrase, 1) or [""])[0]
    q = re.sub(re.escape(kw), "___", phrase, count=1, flags=re.I) if kw else phrase
    return {"phrase": phrase, "question": "Complète : " + q, "answer": kw, "fallback": True}


def simplify(text, profile="standard"):
    out = ask(f"Reformule ce passage de cours pour un étudiant. {SITE_HINTS.get(profile, SITE_HINTS['standard'])}\n\n{text}")
    if out:
        return {"text": adapt(out, profile), "fallback": False}
    t = text
    for k, v in QUALI.items() if profile == "dyscalculie" else []:
        t = re.sub(re.escape(k), lambda m, v=v: f"{m.group(0)} ({v})", t, count=1, flags=re.I)
    for k, v in LITERAL.items() if profile == "autisme" else []:
        t = re.sub(re.escape(k), v, t, flags=re.I)
    parts = [p.strip() for p in re.split(r"(?<=[.!?;])\s+|,\s+(?=(?:et|mais|donc|car)\b)", t) if p.strip()]
    if profile in ("dyscalculie", "autisme"):
        parts = [f"{i}. {p}" for i, p in enumerate(parts, 1)]
    return {"text": adapt("\n".join(parts), profile), "fallback": True}


# ---------- Leçon structurée, outils, pack de rattrapage ----------
def lesson(text, profile="standard", style="visuel", title=""):
    """Leçon fidèle au passage : idée → explication → exemple → vérification → action. Adaptée au profil.
    Le passage est une NOTION COMPLÈTE (titre, définition ou paragraphe) : on ne l'invente pas, on le reformule."""
    cfg = PROFILES.get(profile, PROFILES["standard"])
    head = f" (notion : {title})" if title else ""
    out = ask(
        f"Passage de cours{head} :\n{text}\n\n"
        "Reformule UNIQUEMENT ce qui figure dans ce passage : n'invente rien, n'ajoute aucun exemple absent du texte. "
        "Donne UNIQUEMENT un JSON {\"idea\":\"la notion expliquée en une phrase complète\","
        "\"explain\":\"explication complète et fidèle, en phrases entières\","
        "\"example\":\"exemple tiré du passage, sinon chaîne vide\","
        "\"check_q\":\"question de vérification sur ce passage\",\"check_a\":\"réponse courte\","
        "\"activity\":\"mini-action pratique liée à la notion\",\"steps\":[\"étape tirée du passage\"]}. " + cfg.get("prompt_site", cfg["prompt"])
    )
    d = _json(out)
    term, _, _ = find_definition(text)
    kws = key_terms(text, term, 4) or keywords(text, 4)
    fb = not (d and d.get("idea") and d.get("explain"))
    if fb:                                              # repli sans IA : on garde le texte du cours, phrases entières
        ss = [re.sub(r"^•\s*", "", x) for x in sentences(text)]
        ex = next((x for x in ss if re.search(r"\bexemple\b", x, re.I)), "")
        main = [x for x in ss if x != ex]
        mp = micropulse(text)
        d = {
            "idea": main[0] if main else text,
            "explain": " ".join(main[1:]),
            "example": ex,
            "check_q": mp["question"],
            "check_a": mp["answer"],
            "steps": main[:5],
            "activity": f"Écris avec tes mots ce que veut dire « {term or kws[0]} »." if (term or kws) else "Résume ce bloc en une phrase.",
        }
    L = {k: str(d.get(k, "") or "").strip() for k in ("idea", "explain", "example", "check_q", "check_a", "activity")}
    steps = d.get("steps") if isinstance(d.get("steps"), list) else []
    calc = []
    if cfg["qualitative"]:
        sents = sentences(L["explain"])
        calc = [x for x in sents if has_math(x)]
        L["explain"] = " ".join(x for x in sents if not has_math(x)) or L["explain"]
    L = {k: adapt(v, profile) for k, v in L.items()}
    return {**L, "steps": [adapt(str(x), profile) for x in steps][:6], "calc": calc, "keywords": kws, "term": term, "fallback": fb}


def checklist(task, profile="standard"):
    out = ask(
        f"Consigne : {task}\nTransforme-la en checklist d'actions littérales et concrètes (max 8). "
        f"JSON uniquement : {{\"steps\":[\"...\"]}}"
    )
    d = _json(out)
    if d and isinstance(d.get("steps"), list) and d["steps"]:
        return {"steps": [adapt(str(s), profile) for s in d["steps"]][:8], "fallback": False}
    parts = [p.strip(" .") for p in re.split(r"[.;\n]|\b(?:puis|ensuite)\b", task, flags=re.I) if p.strip(" .")]
    return {"steps": [adapt(p[0].upper() + p[1:], profile) for p in parts][:8] or [task], "fallback": True}


def gaps(text, profile="standard"):
    out = ask(
        f"Passage de cours :\n{text}\nListe (max 4) les notions à connaître AVANT de le comprendre. "
        f"JSON uniquement : {{\"gaps\":[{{\"prereq\":\"...\",\"explain\":\"1-2 phrases\"}}]}}. {SITE_HINTS.get(profile, '')}"
    )
    d = _json(out)
    if d and isinstance(d.get("gaps"), list) and d["gaps"]:
        return {
            "gaps": [
                {"prereq": adapt(str(g.get("prereq", "")), profile), "explain": adapt(str(g.get("explain", "")), profile)}
                for g in d["gaps"]
            ][:4],
            "fallback": False,
        }
    ss = sentences(text)
    return {
        "gaps": [
            {"prereq": f"Savoir ce que veut dire « {k} »", "explain": adapt(next((s for s in ss if k in s.lower()), ""), profile)}
            for k in keywords(text, 4)
        ],
        "fallback": True,
    }


def pack(text, profile="standard"):
    """Pack de rattrapage : résumé, termes clés, 5 questions."""
    out = ask(
        f"Cours :\n{text[:6000]}\nJSON uniquement : {{\"summary\":\"résumé en 6 phrases max\","
        f"\"terms\":[{{\"term\":\"\",\"def\":\"\"}}],\"questions\":[{{\"q\":\"\",\"a\":\"\"}}]}} avec 6 termes max et exactement 5 questions. {SITE_HINTS.get(profile, '')}"
    )
    d = _json(out)
    if d and d.get("summary") and d.get("questions"):
        return {
            "summary": adapt(str(d["summary"]), profile),
            "terms": d.get("terms", [])[:6],
            "questions": d["questions"][:5],
            "fallback": False,
        }
    ss = sentences(text)
    qs = []
    for s in ss[:5]:
        mp = micropulse(s)
        qs.append({"q": mp["question"], "a": mp["answer"]})
    return {
        "summary": adapt(" ".join(ss[:4]), profile),
        "questions": qs,
        "fallback": True,
        "terms": [{"term": k, "def": adapt(next((s for s in ss if k in s.lower()), ""), profile)} for k in keywords(text, 6)],
    }


def reexplain(notion, context, profile="standard"):
    out = ask(
        f"Contexte du cours : {context}\nL'étudiant s'est perdu sur « {notion} ». Réexplique-le simplement, avec un exemple. {SITE_HINTS.get(profile, '')}"
    )
    if out:
        return {"text": adapt(out, profile), "fallback": False}
    s = next((x for x in sentences(context) if notion and notion.lower() in x.lower()), _short(context, 40))
    return {"text": adapt(s, profile), "fallback": True}


def board(data, mime, profile="standard"):
    """Photo du tableau → OCR + notes structurées (Gemini vision, clé requise)."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY manquante")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        timeout=30,
        json={
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
                        {
                            "text": "Transcris ce tableau (OCR) puis structure-le en notes : titres, puces, formules. En français. "
                            + HINTS.get(profile, "")
                        },
                    ]
                }
            ]
        },
    )
    r.raise_for_status()
    return adapt(r.json()["candidates"][0]["content"]["parts"][0]["text"], profile)


_vis = {}


def visual(q, lang="fr"):
    """Image + extrait Wikipédia pour un mot-clé (gratuit, sans clé). {} si rien."""
    k = (lang, q.lower())
    if k not in _vis:
        out = {}
        try:
            r = requests.get(
                f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(q.replace(' ', '_'))}",
                timeout=4,
                headers={"User-Agent": "NeuroStudy/1.0"},
            )
            if r.ok:
                j = r.json()
                out = {
                    "image": (j.get("thumbnail") or {}).get("source"),
                    "title": j.get("title"),
                    "extract": j.get("extract"),
                }
        except Exception:
            pass
        if out:                      # on ne mémorise pas un échec réseau
            _vis[k] = out
        return out
    return _vis[k]


def build_concept_svg(concept: str, context: str = "") -> str:
    """Génère une courbe ou un schéma SVG lisible pour illustrer la notion."""
    safe_concept = html.escape((concept or "Notion clé")[:24])
    low = f"{concept} {context}".lower()

    if "inverse_curve" in low or any(
        k in low for k in ["négative", "negative", "inverse", "décroissant", "baisse", "diminue"]
    ):
        return f"""<svg viewBox="0 0 320 150" xmlns="http://www.w3.org/2000/svg">
          <line x1="40" y1="120" x2="290" y2="120" stroke="#94a3b8" stroke-width="2"/>
          <line x1="40" y1="20" x2="40" y2="120" stroke="#94a3b8" stroke-width="2"/>
          <polyline points="54,32 150,68 266,108" fill="none" stroke="#f59e0b" stroke-width="3"/>
          <circle cx="54" cy="32" r="4" fill="#38bdf8"/>
          <circle cx="266" cy="108" r="4" fill="#ef4444"/>
          <text x="155" y="138" fill="#cbd5e1" font-size="10.5">Quand X augmente →</text>
          <text x="8" y="15" fill="#cbd5e1" font-size="10">Y baisse</text>
          <text x="115" y="46" fill="#fde047" font-size="10.5">{safe_concept}</text>
        </svg>"""

    if "growth_curve" in low or any(
        k in low for k in ["croissant", "affine", "linéaire", "exponentiel", "augmentation", "courbe", "fonction", "suite"]
    ):
        return f"""<svg viewBox="0 0 320 150" xmlns="http://www.w3.org/2000/svg">
          <line x1="40" y1="120" x2="290" y2="120" stroke="#94a3b8" stroke-width="2"/>
          <line x1="40" y1="20" x2="40" y2="120" stroke="#94a3b8" stroke-width="2"/>
          <path d="M 52 106 Q 155 86 266 28" fill="none" stroke="#22c55e" stroke-width="3"/>
          <circle cx="52" cy="106" r="4" fill="#38bdf8"/>
          <circle cx="266" cy="28" r="4" fill="#22c55e"/>
          <text x="155" y="138" fill="#cbd5e1" font-size="10.5">Évolution →</text>
          <text x="8" y="15" fill="#cbd5e1" font-size="10">Valeur</text>
          <text x="115" y="54" fill="#86efac" font-size="10.5">{safe_concept}</text>
        </svg>"""

    return f"""<svg viewBox="0 0 320 126" xmlns="http://www.w3.org/2000/svg">
      <rect x="10" y="34" width="90" height="58" rx="8" fill="#1d4ed8"/>
      <text x="55" y="57" text-anchor="middle" fill="#ffffff" font-size="10.5" font-weight="bold">1. Idée</text>
      <text x="55" y="75" text-anchor="middle" fill="#dbeafe" font-size="9">Règle simple</text>

      <line x1="100" y1="63" x2="115" y2="63" stroke="#38bdf8" stroke-width="2"/>

      <rect x="115" y="28" width="92" height="70" rx="8" fill="#0f766e"/>
      <text x="161" y="52" text-anchor="middle" fill="#ffffff" font-size="10.5" font-weight="bold">2. Exemple</text>
      <text x="161" y="72" text-anchor="middle" fill="#ccfbf1" font-size="9">Cas concret</text>

      <line x1="207" y1="63" x2="222" y2="63" stroke="#38bdf8" stroke-width="2"/>

      <rect x="222" y="34" width="88" height="58" rx="8" fill="#b45309"/>
      <text x="266" y="57" text-anchor="middle" fill="#ffffff" font-size="10.5" font-weight="bold">3. Retenir</text>
      <text x="266" y="75" text-anchor="middle" fill="#fef3c7" font-size="8.5">{safe_concept}</text>
    </svg>"""


def format_subtitle_clean(text: str, target: str = "fr", profile: str = "standard", llm_call=None) -> dict:
    """Produit un sous-titre propre et grammaticalement correct dans la langue cible."""
    lang_rule = LANGUAGE_INSTRUCTIONS.get(target, LANGUAGE_INSTRUCTIONS["fr"])
    prompt = (
        f"Corrige, clarifie et traduis ce passage de cours pour un étudiant (profil : {profile}). "
        f"{lang_rule} Renvoie uniquement le texte final, sans préfixe ni guillemets.\n"
        f"Texte : {text}"
    )
    runner = llm_call if callable(llm_call) else ask
    out = runner(prompt)
    if out and out.strip():
        return {"subtitle": adapt(out.strip(), profile), "fallback": False}

    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if target == "ar":
        cleaned = f"الخلاصة الواضحة: {cleaned}" if cleaned else "في انتظار النص."
    elif target == "en":
        cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else "Waiting for speech."
    else:
        cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else "En attente du discours."
    return {"subtitle": adapt(cleaned, profile), "fallback": True}


LOST_TIMEOUT = float(os.getenv("LLM_LOST_TIMEOUT", "30"))

# Un angle différent à chaque « Expliquer autrement » : le contenu ne se répète plus d'un clic à l'autre.
ANGLES = {
    1: "Donne l'explication la plus simple possible : mots du quotidien, 3 à 5 phrases courtes, une seule idée.",
    2: "Cette fois, explique PAR UNE ANALOGIE tirée de la vie quotidienne (cuisine, sport, argent, téléphone…), "
       "puis relie-la au cours.",
    3: "Cette fois, explique PAS À PAS : décompose en 3 à 5 petites étapes, chacune très courte.",
    4: "Cette fois, explique avec un EXEMPLE COMPLET, concret ou chiffré, résolu de bout en bout, ligne par ligne.",
}

_NOTICE_NOKEY = {
    "fr": "Aucune IA ne répond (clé absente, refusée ou quota dépassé). Voici une explication de secours.",
    "en": "No AI is answering (missing, rejected or over-quota key). Here is a backup explanation.",
    "ar": "لا يوجد ذكاء اصطناعي يستجيب (المفتاح مفقود أو مرفوض أو تجاوز الحصة). هذا شرح احتياطي.",
}
_NOTICE_OFFLINE = {
    "fr": "Mode secours (sans IA) : explication prête à l'emploi pour cette notion.",
    "en": "Backup mode (no AI): ready-made explanation for this concept.",
    "ar": "وضع الطوارئ (بدون ذكاء اصطناعي): شرح جاهز لهذا المفهوم.",
}
_NOTICE_EXTRACT = {
    "fr": "Mode secours (sans IA) : voici ce qui vient d'être dit, remis au clair. Avec une clé IA valide, "
          "tu auras une vraie explication avec exemple.",
    "en": "Backup mode (no AI): here is what was just said, made clearer. With a valid AI key you get a real "
          "explanation with an example.",
    "ar": "وضع الطوارئ (بدون ذكاء اصطناعي): هذا ما قيل للتو بصياغة أوضح. مع مفتاح ذكاء اصطناعي صالح ستحصل على "
          "شرح حقيقي مع مثال.",
}
_WIKI_LANG = {"fr": "fr", "en": "en", "ar": "ar"}
_TR_KEYS = ("point", "quote", "why_hard", "paragraph", "analogy", "example")


def wiki_image(q, lang="fr", max_bytes=120_000):
    """Image Wikipédia du terme, renvoyée en data-URI (évite les blocages CSP de YouTube/Meet). None si rien."""
    v = visual(q, lang) if q else {}
    url = (v or {}).get("image")
    if not url:
        return None
    try:
        r = requests.get(url, timeout=5, headers={"User-Agent": "NeuroStudy/1.0"})
        ctype = r.headers.get("content-type", "")
        if r.ok and ctype.startswith("image/") and len(r.content) <= max_bytes:
            return {"data": f"data:{ctype};base64,{base64.b64encode(r.content).decode()}",
                    "title": v.get("title") or q}
    except Exception:
        pass
    return None


def _lost_prompt(context, target, profile, source_title, current_time, previous, attempt=1, focus="", live=False):
    lang_rule = LANGUAGE_INSTRUCTIONS.get(target, LANGUAGE_INSTRUCTIONS["fr"])
    cfg = PROFILES.get(profile, PROFILES["standard"])
    has_t = isinstance(current_time, (int, float))
    if live:
        support = "une réunion de cours EN DIRECT (Google Meet)"
        when = f" (≈ {int(current_time) // 60} min après le début)" if has_t else ""
    else:
        support = f"une vidéo de cours « {source_title or 'sans titre'} »"
        when = f" (position dans la vidéo : {int(current_time) // 60}:{int(current_time) % 60:02d})" if has_t else ""
    angle = ANGLES[((max(int(attempt or 1), 1) - 1) % 4) + 1]
    retry = ""
    if previous:
        retry = (f"\nATTENTION : l'étudiant n'a PAS compris l'explication précédente « {previous[:400]} ». "
                 "Ne répète ni les mêmes mots, ni la même analogie, ni le même exemple.\n")
    foc = (f"L'étudiant précise qu'il est perdu sur : « {focus[:120]} ». Explique CE point précis.\n" if focus else "")
    return (
        f"Un étudiant suit {support}{when} et vient d'appuyer sur « Je suis perdu ».\n"
        "Voici la transcription récente (les lignes les plus basses sont les plus récentes ; "
        "le passage peut être en derja tunisien, arabe, français ou anglais ; "
        "en réunion, chaque ligne est « Intervenant : phrase » — ne parle que de ce qui a été DIT, jamais des boutons ou menus) :\n"
        f"\"\"\"\n{context[:3500] or '(aucune transcription disponible)'}\n\"\"\"\n{foc}{retry}\n"
        "TÂCHE :\n"
        "1. Repère LE point précis qu'il n'a probablement pas compris : l'idée la plus récente et la plus difficile "
        "(pas le sujet général).\n"
        f"2. {angle}\n"
        "3. Donne TOUJOURS un exemple très simple et concret (obligatoire, jamais vide) ET une analogie de la vie quotidienne.\n"
        "4. Choisis le meilleur support visuel : « curve » si une quantité varie (fonction, suite, corrélation), "
        "« flow » pour un processus, « comparison » pour opposer deux notions, « none » sinon.\n"
        f"{lang_rule} Profil de l'étudiant : {cfg['prompt']}\n\n"
        "Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, de cette forme (tous les textes dans la langue demandée) :\n"
        '{"point":"titre court du point (max 8 mots)",'
        '"quote":"la phrase exacte entendue concernée (max 25 mots)",'
        '"why_hard":"pourquoi ce point est difficile (1 phrase)",'
        '"prerequisites":["notion à connaître avant (max 3)"],'
        '"paragraph":"explication simple en 3 à 5 phrases courtes",'
        '"analogy":"analogie avec la vie de tous les jours (1-2 phrases)",'
        '"example":"exemple très simple et concret (1-3 phrases)",'
        '"steps":["étape 1","étape 2","étape 3"],'
        '"formula":"règle ou formule à retenir, sinon chaîne vide",'
        '"glossary":[{"term":"mot ou expression entendu(e)","meaning":"sens simple dans la langue demandée"}],'
        '"visual":{"type":"curve","title":"","x_label":"","y_label":"",'
        '"series":[{"name":"","points":[[0,1],[1,2],[2,4]]}]},'
        '"image_query":"titre d\'un article Wikipédia illustrant la notion, sinon chaîne vide",'
        '"check":{"question":"question pour vérifier la compréhension","answer":"réponse courte"}}\n'
        "Formes possibles de \"visual\" : "
        '{"type":"flow","title":"","nodes":["étape A","étape B","étape C"]} ; '
        '{"type":"comparison","title":"","left":{"title":"A","items":["..."]},"right":{"title":"B","items":["..."]}} ; '
        '{"type":"none"}. Les points d\'une courbe doivent être des nombres réels cohérents avec l\'explication.'
    )


def _clean_list(v, n, profile, maxlen=160, lang="fr"):
    return [adapt(str(x).strip()[:maxlen], profile, lang)
            for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]


def _glossary(v, profile, lang):
    out = []
    for g in (v if isinstance(v, list) else [])[:4]:
        if isinstance(g, dict) and str(g.get("term", "")).strip() and str(g.get("meaning", "")).strip():
            out.append({"term": str(g["term"]).strip()[:60], "meaning": adapt(str(g["meaning"]).strip()[:200], profile, lang)})
    return out


def translate_result(r, target, profile="standard"):
    """Traduit les textes d'une explication « Je suis perdu » (sauf formule et schéma) vers `target`.
    Retourne (champs_traduits, infos_traducteur). Sert à l'historique : on relit un point dans la langue de son choix."""
    out = {k: r.get(k, "") or "" for k in _TR_KEYS}
    out["steps"] = [str(s) for s in (r.get("steps") or [])]
    out["prerequisites"] = [str(s) for s in (r.get("prerequisites") or [])]
    chk = r.get("check") or {}
    out["check"] = {"question": chk.get("question", "") or "", "answer": chk.get("answer", "") or ""}
    out["glossary"] = [{"term": g.get("term", ""), "meaning": g.get("meaning", "")} for g in (r.get("glossary") or [])]

    slots = []                                   # (texte, fonction qui range la traduction)
    for k in _TR_KEYS:
        slots.append((out[k], lambda v, k=k: out.__setitem__(k, v)))
    for i in range(len(out["steps"])):
        slots.append((out["steps"][i], lambda v, i=i: out["steps"].__setitem__(i, v)))
    for i in range(len(out["prerequisites"])):
        slots.append((out["prerequisites"][i], lambda v, i=i: out["prerequisites"].__setitem__(i, v)))
    slots.append((out["check"]["question"], lambda v: out["check"].__setitem__("question", v)))
    slots.append((out["check"]["answer"], lambda v: out["check"].__setitem__("answer", v)))
    for g in out["glossary"]:
        slots.append((g["meaning"], lambda v, g=g: g.__setitem__("meaning", v)))

    live = [(t, s) for t, s in slots if str(t).strip()]
    res = tr.translate_batch([t for t, _ in live], target)
    for (_, setter), it in zip(live, res["items"]):
        setter(adapt(it["translation"], profile, target))
    out["simple_explanation"] = (out["paragraph"] + ("\n" + out["example"] if out["example"] else "")).strip()
    return out, res


def _ensure_example(point, target):
    """Garde-fou : l'étudiant veut TOUJOURS un exemple simple. Si le LLM l'a oublié, on le redemande (court)."""
    out = ask(f"Donne UN exemple très simple et concret (1 à 3 phrases) pour faire comprendre « {point} » à un étudiant. "
              f"{LANGUAGE_INSTRUCTIONS.get(target, '')} Réponds uniquement par l'exemple.",
              max_tokens=250, timeout=LOST_TIMEOUT, priority=True)
    return (out or "").strip()


def _fallback_result(spoken, sents, target, profile, focus, res, source_title):
    """Aucune IA n'a répondu : on le dit clairement ET on donne quand même le maximum d'aide sans IA."""
    from . import visuals
    cfg = PROFILES.get(profile, PROFILES["standard"])
    configured = configured_providers()
    why = "; ".join(f"{k} : {v}" for k, v in res["errors"].items()) or (
        "aucune clé IA configurée dans .env" if not configured else "réponse inutilisable")
    c = knowledge.find(spoken, focus)

    if c:                                         # notion reconnue → explication complète prête à l'emploi (en français)
        base = {k: c[k] for k in ("point", "why_hard", "paragraph", "analogy", "example", "formula", "steps",
                                  "prerequisites", "check")}
        base["quote"] = " ".join(sents[-1:])[:300]
        base["glossary"] = []
        f = base
        if target != "fr":
            f, _ = translate_result(base, target, profile)
            f["formula"] = base["formula"]
        else:
            f = {**base, "check": dict(base["check"])}
        notice = _NOTICE_OFFLINE.get(target, _NOTICE_OFFLINE["fr"])
        svg = visuals.render(c["visual"], show_numbers=not cfg["qualitative"])
        mode = "offline"
        r = {"point": f["point"], "quote": f.get("quote", ""), "why_hard": adapt(f["why_hard"], profile, target),
             "prerequisites": f.get("prerequisites", []), "paragraph": adapt(f["paragraph"], profile, target),
             "analogy": adapt(f["analogy"], profile, target), "example": adapt(f["example"], profile, target),
             "steps": [adapt(s, profile, target) for s in f["steps"]],
             "formula": "" if cfg["qualitative"] else f.get("formula", ""),
             "glossary": [], "visual_svg": svg, "visual_type": c["visual"]["type"] if svg else "none",
             "check": {"question": f["check"]["question"], "answer": adapt(f["check"]["answer"], profile, target)}}
    else:                                         # notion inconnue → ce qui vient d'être dit, traduit et remis au clair
        recent = " ".join(sents[-3:])[:600]
        text, prov = tr.translate_one(recent, target) if recent else ("", None)
        point = (focus or _short(sents[-1], 8) if sents else (source_title or "Passage en cours"))[:60]
        notice = _NOTICE_EXTRACT.get(target, _NOTICE_EXTRACT["fr"])
        mode = "extract"
        r = {"point": point, "quote": " ".join(sents[-2:])[:300], "why_hard": "", "prerequisites": [],
             "paragraph": adapt(text or recent, profile, target), "analogy": "", "example": "", "steps": [],
             "formula": "", "glossary": [], "visual_type": "flow",
             "visual_svg": visuals.flow_from_sentences(sents, title="Ce qui vient d'être dit"),
             "check": {"question": "", "answer": ""}}

    if not configured:
        notice = _NOTICE_NOKEY.get(target, _NOTICE_NOKEY["fr"]) + " " + notice
    r.update({"concept": r["point"], "image": "", "image_caption": "", "notice": notice, "mode": mode,
              "simple_explanation": (r["paragraph"] + ("\n" + r["example"] if r["example"] else "")).strip(),
              "provider": None, "fallback": True, "error": why[:400]})
    return r


def explain_when_lost(context, target="fr", profile="standard", source_title="", current_time=None,
                      previous=None, with_image=True, attempt=1, focus="", live=False):
    """Détecte le point non compris dans ce qui vient d'être dit et l'explique par plusieurs moyens :
    paragraphe, analogie, exemple, étapes, formule, schéma/courbe (SVG), image, glossaire, mini-question.
    Ne lève jamais d'exception : si l'IA échoue, renvoie un secours signalé (fallback=True + error + notice)."""
    from . import visuals

    target = target if target in LANGS else "fr"
    cfg = PROFILES.get(profile, PROFILES["standard"])
    ctx = (context or "").strip()
    spoken = re.sub(r"\b(Derja|Français|Anglais|Arabe)\s*:\s*", " ", ctx, flags=re.I)
    spoken = re.sub(r"[ \t]+", " ", spoken).strip()
    sents = sentences(spoken) or [s.strip() for s in re.split(r"[.؟!\n]+", spoken) if s.strip()]

    res = {"text": None, "provider": None, "errors": {}}
    d = None
    try:
        res = ask_ex(_lost_prompt(spoken, target, profile, source_title, current_time, previous, attempt, focus, live),
                     SYSTEM, json_mode=True, max_tokens=2200, timeout=LOST_TIMEOUT, priority=True)
        d = _json(res["text"])
        if res["text"] and not (d and d.get("point") and d.get("paragraph")):
            # réponse reçue mais inutilisable (JSON coupé/mal formé) → 2ᵉ essai, version compacte
            compact = (f"Passage de cours : \"\"\"{spoken[-1500:]}\"\"\"\n{LANGUAGE_INSTRUCTIONS.get(target, '')} {cfg['prompt']}\n"
                       f"{('Point demandé : ' + focus) if focus else ''}\n"
                       'Réponds UNIQUEMENT en JSON : {"point":"titre court","quote":"phrase concernée",'
                       '"paragraph":"explication simple en 3 phrases","analogy":"analogie du quotidien",'
                       '"example":"exemple très simple et concret"}')
            res2 = ask_ex(compact, SYSTEM, json_mode=True, max_tokens=900, timeout=LOST_TIMEOUT, priority=True)
            d2 = _json(res2["text"])
            if d2 and d2.get("point") and d2.get("paragraph"):
                d, res = d2, res2
    except Exception as e:                       # jamais d'écran blanc : on bascule sur le secours
        res["errors"] = {**res.get("errors", {}), "interne": str(e)[:160]}
        d = None

    if d and d.get("point") and d.get("paragraph"):
        paragraph = adapt(str(d["paragraph"]).strip(), profile, target)
        point = str(d["point"]).strip()[:90]
        example = adapt(str(d.get("example") or "").strip(), profile, target)
        if not example:
            example = adapt(_ensure_example(point, target), profile, target)
        spec = d.get("visual") if isinstance(d.get("visual"), dict) else {}
        svg = visuals.render(spec, show_numbers=not cfg["qualitative"])
        img = wiki_image(str(d.get("image_query") or "")[:80], _WIKI_LANG.get(target, "fr")) if with_image else None
        chk = d.get("check") if isinstance(d.get("check"), dict) else {}
        return {
            "point": point, "concept": point,
            "quote": str(d.get("quote") or "").strip()[:300],
            "why_hard": adapt(str(d.get("why_hard") or "").strip()[:240], profile, target),
            "prerequisites": _clean_list(d.get("prerequisites"), 3, profile, 100, target),
            "paragraph": paragraph,
            "analogy": adapt(str(d.get("analogy") or "").strip()[:400], profile, target),
            "example": example,
            "steps": _clean_list(d.get("steps"), 5, profile, 160, target),
            "formula": "" if cfg["qualitative"] else str(d.get("formula") or "").strip()[:160],
            "glossary": _glossary(d.get("glossary"), profile, target),
            "simple_explanation": (paragraph + ("\n" + example if example else "")).strip(),  # compat. ancien format
            "visual_type": str(spec.get("type") or "none") if svg else "none",
            "visual_svg": svg,
            "image": (img or {}).get("data", ""), "image_caption": (img or {}).get("title", ""),
            "check": {"question": str(chk.get("question") or "").strip()[:240],
                      "answer": adapt(str(chk.get("answer") or "").strip()[:240], profile, target)},
            "provider": res["provider"], "fallback": False, "error": "", "notice": "", "mode": "ai",
            "attempt": int(attempt or 1), "focus": focus,
        }

    r = _fallback_result(spoken, sents, target, profile, focus, res, source_title)
    r.update({"attempt": int(attempt or 1), "focus": focus})
    return r
