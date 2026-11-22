"""Historique persistant des « points non compris » et de leurs explications (fichier JSON local).

Chaque entrée = un clic sur « Je suis perdu » : la vidéo, l'instant, le point repéré, l'explication
complète (texte, schéma SVG, image, mini-question) et un statut « compris / à revoir ».
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone

MAX_ENTRIES = 200


class HistoryStore:
    def __init__(self, path=None):
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        self.path = path or os.path.join(base, "history.json")
        self.lock = threading.Lock()
        self.items = self._load()

    # -- persistance ---------------------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False)
        os.replace(tmp, self.path)          # écriture atomique : pas de fichier à moitié écrit

    # -- API -----------------------------------------------------------------------------------
    def add(self, source, video_time, result, target="fr", profile="standard", versions=None, live=False, focus=""):
        entry = {
            "id": uuid.uuid4().hex[:12],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": {k: str((source or {}).get(k) or "")[:300] for k in ("platform", "title", "url", "video_id")},
            "video_time": video_time if isinstance(video_time, (int, float)) else None,
            "target": target,
            "profile": profile,
            "understood": False,
            "live": bool(live),                       # point marqué pendant une réunion en direct (Meet)
            "focus": str(focus or "")[:120],          # terme précisé par l'étudiant, s'il y en a un
            "versions": list(versions or []),         # anciennes explications (chaque « Expliquer autrement »)
            "translations": {},                       # langue -> champs traduits (rempli à la demande)
            "result": result,
        }
        with self.lock:
            self.items.insert(0, entry)
            self.items = self.items[:MAX_ENTRIES]
            self._save()
        return entry

    def list(self, limit=MAX_ENTRIES):
        with self.lock:
            return list(self.items[:limit])

    def get(self, entry_id):
        with self.lock:
            return next((e for e in self.items if e["id"] == entry_id), None)

    def set_understood(self, entry_id, value):
        with self.lock:
            for e in self.items:
                if e["id"] == entry_id:
                    e["understood"] = bool(value)
                    self._save()
                    return e
        return None

    def set_translation(self, entry_id, lang, fields):
        with self.lock:
            for e in self.items:
                if e["id"] == entry_id:
                    e.setdefault("translations", {})[lang] = fields
                    self._save()
                    return e
        return None

    def delete(self, entry_id):
        with self.lock:
            n = len(self.items)
            self.items = [e for e in self.items if e["id"] != entry_id]
            if len(self.items) != n:
                self._save()
            return len(self.items) != n

    def clear(self):
        with self.lock:
            self.items = []
            self._save()


history = HistoryStore()
