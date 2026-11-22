"""Stockage léger en mémoire (thread-safe) + export JSON."""
import json, threading, time
from collections import Counter


class SessionStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.points, self.transcript, self.meta = [], [], {}

    def reset(self):
        with self.lock:
            self.points, self.transcript, self.meta = [], [], {}

    def add_point(self, t, attention, label="", lost=False):
        with self.lock:
            self.points.append({"t": t, "attention": round(float(attention), 1), "label": label, "lost": bool(lost), "ts": time.time()})
            self.points = self.points[-2000:]

    def add_transcript(self, t, text):
        with self.lock:
            self.transcript.append({"t": t, "text": text})
            self.transcript = self.transcript[-2000:]

    def summary(self):
        with self.lock:
            lost = [p for p in self.points if p["lost"]]
            top = Counter(p["label"] for p in lost if p["label"]).most_common(8)
            avg = round(sum(p["attention"] for p in self.points) / len(self.points), 1) if self.points else None
            return {"meta": self.meta, "marks": [{"t": p["t"], "label": p["label"]} for p in lost], "points": len(self.points), "avg_attention": avg, "lost_count": len(lost),
                    "to_review": [{"notion": n, "times": c, "at": [p["t"] for p in lost if p["label"] == n]} for n, c in top]}

    def comprehension(self, seconds=300):
        """Score 0-100 : attention moyenne (caméra) des `seconds` dernières secondes, moins 8 pts par « Je suis perdu »."""
        cut = time.time() - seconds
        with self.lock:
            att = [p["attention"] for p in self.points if not p["lost"] and p.get("ts", 0) >= cut]
            lost = sum(1 for p in self.points if p["lost"] and p.get("ts", 0) >= cut)
        base = sum(att) / len(att) if att else 80.0
        return max(0, min(100, round(base - min(lost, 5) * 8)))

    def set_meta(self, **kw):
        with self.lock:
            self.meta.update({k: str(v)[:200] for k, v in kw.items()})

    def near(self, t, window=90):
        with self.lock:
            return " ".join(x["text"] for x in self.transcript if t - window <= x["t"] <= t + 10)

    def full_text(self):
        with self.lock:
            return " ".join(x["text"] for x in self.transcript)

    def dump(self, path="session_dump.json"):
        with self.lock, open(path, "w", encoding="utf-8") as f:
            json.dump({"points": self.points, "transcript": self.transcript}, f, ensure_ascii=False, indent=1)


store = SessionStore()
