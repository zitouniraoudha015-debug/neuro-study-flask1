"""Nettoyage des sous-titres reçus de l'extension (défense en profondeur côté serveur).

Meet mélange dans sa page des textes d'interface (« Désactiver le micro (Ctrl+d) », « arrow_downward Aller en bas »…).
L'extension les filtre déjà ; ici on garantit que, même avec une ancienne version de l'extension, ce bruit n'arrive
jamais jusqu'à l'IA, et qu'une même phrase répétée n'est envoyée qu'une fois.
"""
import re

_ICON = re.compile(r"^[a-z]+(?:_[a-z0-9]+)+$")
_NOISE = [re.compile(p, re.I) for p in (
    r"aller en bas", r"jump to (the )?bottom", r"انتقل إلى الأسفل",
    r"d[ée]sactiver le micro", r"activer le micro", r"turn (off|on) (the )?microphone",
    r"annoncer toutes les r[ée]actions", r"announce all reactions",
    r"d[ée]sactiver la cam[ée]ra", r"activer la cam[ée]ra", r"turn (off|on) (the )?camera",
    r"param[èe]tres des sous-titres", r"caption settings", r"quitter l'appel", r"leave call",
    r"lever la main", r"raise hand", r"pr[ée]senter maintenant", r"present now",
)]


def clean_line(text) -> str:
    """Retire les mots-icônes (arrow_downward…) et renvoie '' si la ligne n'est que du texte d'interface."""
    words = [w for w in re.sub(r"\s+", " ", str(text or "")).strip().split(" ") if not _ICON.match(w)]
    t = " ".join(words).strip()
    if not t or any(p.search(t) for p in _NOISE):
        return ""
    return t


def clean_captions(caps, limit=30):
    """caps : liste de {t, text, speaker?}. Retourne les lignes propres, sans doublon consécutif."""
    out, seen = [], None
    for c in (caps or [])[-limit:]:
        if not isinstance(c, dict):
            continue
        text = clean_line(c.get("text", ""))
        if not text:
            continue
        speaker = clean_line(c.get("speaker", ""))[:40]
        key = (speaker, text.lower())
        if key == seen:
            continue
        seen = key
        out.append({"t": c.get("t"), "speaker": speaker, "text": text[:300]})
    return out
