"""Traduction des sous-titres et des explications vers la langue choisie (fr / en / ar).

Chaîne de secours, de la meilleure qualité à la plus basique — la traduction ne s'arrête donc jamais :
  1. LLM par LOTS (une seule requête pour ~10 phrases : rapide et économe en quota, comprend le derja)
  2. Traducteurs gratuits sans clé (Google « gtx », puis MyMemory) — utiles quand aucune clé IA ne marche
  3. Petit dictionnaire derja → français
Les résultats sont mis en cache (même phrase, même langue = aucun nouvel appel).
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

LANGS = {"fr": "français", "en": "anglais", "ar": "arabe"}
_AR = re.compile(r"[؀-ۿ]")

_cache = {}                      # (cible, consigne, texte) -> (traduction, fournisseur)
_lock = threading.Lock()
_free_down = {}                  # traducteur gratuit -> instant jusqu'auquel on l'évite après une erreur
FREE_PAUSE = 45

# ---- Détection de langue (très légère, suffisante pour ne PAS retraduire ce qui est déjà dans la bonne langue) ----
_FR = set("le la les un une des et est sont que qui dans pour pas sur avec nous vous ce cette il elle ils on au aux du de "
          "mais donc car comme plus par ou où se sa son ses leur leurs je tu ne en à été être avoir fait très aussi "
          "alors lorsque quand ainsi cela chaque tout tous toute entre sans sous voici maintenant première seconde".split())
_EN = set("the a an and is are of to in that this it for on with we you they not be as at by or if so was were have has "
          "from what when which will can our your their there here now first then".split())
_DERJA = set("chnowa chnia barcha yesser mouch moch lyoum lyom bech nechrhou nechrah fhemtou fhemt fhemna mouchkla ya3ni "
             "yaani kifech kifash 3lech aleh taw tawa behi haja hiya houwa mta3 mte3 wost wost el ml fi w ki kif "
             "dima 3andek 3andi nheb famma fama 9olt nal9a na3mlou na3mel tla3 tnez wa7da o5ra a9des mbaajdin "
             "ahna enti inti ena el5ater bahi sahit sa7it yezzi ya7ki n7eb t7eb 7aja".split())
_DERJA_SIGNS = re.compile(r"\b[a-z]*[a-z][3579][a-z0-9]*\b|\b[3579][a-z]+\b")   # chiffres-lettres : 3=ع 7=ح 9=ق 5=خ


def detect_lang(text):
    """'ar' (écriture arabe), 'aeb' (derja en lettres latines), 'fr', 'en' ou 'und' (indéterminé)."""
    t = (text or "").strip()
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return "und"
    if sum(1 for c in letters if _AR.match(c)) / len(letters) > 0.35:
        return "ar"
    words = re.findall(r"[a-zàâäçéèêëîïôöûùüÿœ0-9']+", t.lower())
    fr = sum(w in _FR for w in words)
    en = sum(w in _EN for w in words)
    de = sum(w in _DERJA for w in words) + len(_DERJA_SIGNS.findall(t.lower()))
    if de >= 2 or (de >= 1 and fr + en <= 1):
        return "aeb"
    if fr == en == 0:
        return "und"
    return "fr" if fr >= en else "en"


def same_language(text, target):
    d = detect_lang(text)
    return d == target


# ---- Traducteurs gratuits sans clé ----
def _split(text, size=450):
    """Coupe un long texte en morceaux ≤ size caractères, à la fin des phrases si possible."""
    parts, cur = [], ""
    for s in re.split(r"(?<=[.!?؟])\s+", text.strip()):
        if len(cur) + len(s) + 1 <= size:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                parts.append(cur)
            while len(s) > size:
                parts.append(s[:size])
                s = s[size:]
            cur = s
    if cur:
        parts.append(cur)
    return parts or [text[:size]]


def _google(text, target):
    r = requests.get("https://translate.googleapis.com/translate_a/single",
                     params={"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}")
    data = r.json()
    out = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0])
    if not out.strip():
        raise RuntimeError("réponse vide")
    return out


def _mymemory(text, target):
    src = "ar" if (_AR.search(text) or detect_lang(text) == "aeb") else ("en" if detect_lang(text) == "en" else "fr")
    if src == target:
        src = "en" if target != "en" else "fr"
    r = requests.get("https://api.mymemory.translated.net/get",
                     params={"q": text[:480], "langpair": f"{src}|{target}"}, timeout=6)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}")
    out = ((r.json().get("responseData") or {}).get("translatedText") or "").strip()
    if not out or "QUERY LENGTH LIMIT" in out.upper() or "MYMEMORY WARNING" in out.upper():
        raise RuntimeError("réponse inutilisable")
    return out


FREE = {"google": _google, "mymemory": _mymemory}


def free_translate(text, target):
    """Traduit sans clé. Retourne (texte, fournisseur) ou (None, None)."""
    for name, fn in FREE.items():
        if _free_down.get(name, 0) > time.time():
            continue
        try:
            out = " ".join(fn(chunk, target) for chunk in _split(text))
            if out.strip():
                return out.strip(), name
        except Exception:
            _free_down[name] = time.time() + FREE_PAUSE
    return None, None


# ---- LLM par lots ----
def _llm_prompt(items, target, hint=""):
    lang = LANGS.get(target, "français")
    style = {"ar": "arabe standard simple et correct (écriture arabe)",
             "en": "anglais naturel et correct",
             "fr": "français naturel et correct"}.get(target, lang)
    return (
        "Tu es traducteur de sous-titres de cours pour des étudiants. Chaque élément vient d'une transcription "
        "automatique : il peut être en derja tunisien (arabe dialectal, parfois écrit en lettres latines : 3=ع, 7=ح, "
        "9=ق, 5=خ), en arabe, en français ou en anglais, souvent mélangés.\n"
        f"Traduis CHAQUE élément en {style}. Conserve les termes techniques (maths, informatique, sciences) et les "
        f"noms propres. Si la langue cible est le français ou l'anglais, ne laisse AUCUN mot en derja ou en arabe. "
        f"Si un élément est déjà dans la langue cible, renvoie-le (légèrement corrigé). {hint}\n"
        f'Réponds UNIQUEMENT par un objet JSON {{"t": [...]}} contenant exactement {len(items)} chaînes, '
        "dans le même ordre, sans aucun commentaire.\n"
        f"Éléments : {json.dumps(items, ensure_ascii=False)}"
    )


def _llm_batch(items, target, hint=""):
    """items : liste de textes → (liste de traductions | None, fournisseur, erreurs)."""
    from . import ai_service as ai
    res = ai.ask_ex(_llm_prompt(items, target, hint), json_mode=True,
                    max_tokens=min(4000, 300 + 160 * len(items)), timeout=ai.TIMEOUT + 8)
    data = ai._json(res["text"])
    out = data.get("t") if isinstance(data, dict) else None
    if isinstance(out, list) and len(out) == len(items) and all(isinstance(x, str) for x in out):
        return [x.strip() for x in out], res["provider"], res["errors"]
    return None, res["provider"], res["errors"]


def _dict_translate(text, target):
    if target != "fr":
        return None
    from . import ai_service as ai
    out = text
    for k, v in ai.DERJA.items():
        out = re.sub(rf"\b{re.escape(k)}\b", v, out, flags=re.I)
    return out if out != text else None


# ---- API publique ----
def translate_batch(texts, target="fr", hint=""):
    """Traduit une liste de textes. Retourne
    {"items": [{"text","translation","provider","same"}], "provider": str|None, "fallback": bool, "errors": {...}}.
    provider : "llm:<nom>", "google", "mymemory", "dictionnaire", "inchangé" ou "déjà dans la langue"."""
    target = target if target in LANGS else "fr"
    texts = [str(t or "").strip() for t in texts]
    results = [None] * len(texts)
    errors = {}

    # 1) vide / déjà dans la bonne langue / cache
    todo = []
    for i, t in enumerate(texts):
        if not t:
            results[i] = ("", "déjà dans la langue")
        elif same_language(t, target):
            results[i] = (t, "déjà dans la langue")
        else:
            with _lock:
                hit = _cache.get((target, hint, t))
            if hit:
                results[i] = hit
            else:
                todo.append(i)

    # 2) LLM par lots (≤ 10 phrases ou ≤ 2200 caractères par requête)
    if todo:
        batches, cur, size = [], [], 0
        for i in todo:
            if cur and (len(cur) >= 10 or size + len(texts[i]) > 2200):
                batches.append(cur)
                cur, size = [], 0
            cur.append(i)
            size += len(texts[i])
        if cur:
            batches.append(cur)
        for b in batches:
            out, prov, errs = _llm_batch([texts[i] for i in b], target, hint)
            errors.update(errs)
            if out:
                for i, tr in zip(b, out):
                    results[i] = (tr, f"llm:{prov}")

    # 3) traducteurs gratuits, en parallèle, pour ce que le LLM n'a pas pu faire
    left = [i for i in todo if results[i] is None]
    if left:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, (tr, prov) in zip(left, ex.map(lambda j: free_translate(texts[j], target), left)):
                if tr:
                    results[i] = (tr, prov)

    # 4) dictionnaire, sinon texte d'origine
    for i in todo:
        if results[i] is None:
            d = _dict_translate(texts[i], target)
            results[i] = (d, "dictionnaire") if d else (texts[i], "inchangé")

    with _lock:
        for i in todo:
            tr, prov = results[i]
            if prov not in ("inchangé",):
                _cache[(target, hint, texts[i])] = (tr, prov)
        while len(_cache) > 4000:
            _cache.pop(next(iter(_cache)))

    items = [{"text": texts[i], "translation": results[i][0], "provider": results[i][1],
              "same": results[i][1] == "déjà dans la langue"} for i in range(len(texts))]
    used = [it["provider"] for it in items if not it["same"]]
    bad = {"dictionnaire", "inchangé"}
    return {"items": items, "provider": next((p for p in used if p not in bad), used[0] if used else None),
            "fallback": any(p in bad for p in used), "errors": errors}


def translate_one(text, target="fr", hint=""):
    r = translate_batch([text], target, hint)
    return r["items"][0]["translation"], r["items"][0]["provider"]
