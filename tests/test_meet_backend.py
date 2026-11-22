import os
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["LLM_PROVIDER"] = "gemini"; os.environ["GEMINI_API_KEY"] = ""
from services.captions import clean_line, clean_captions
import app as A

# 1. nettoyage : exactement le bruit vu dans la capture
assert clean_line("Désactiver le micro (Ctrl+d) Annoncer toutes les réactions") == ""
assert clean_line("settings arrow_downward Aller en bas") == ""
assert clean_line("Vous arrow_downward Aller en bas") == ""
assert clean_line("Hello, everyone. We are gonna talk about the conditioner.") .startswith("Hello")
assert clean_line("Open the settings page") == "Open the settings page"
caps = [{"t": None, "speaker": "Vous", "text": "Everyone."}, {"t": None, "speaker": "Bouazizi May", "text": "Fish."},
        {"t": None, "speaker": "Vous", "text": "Hello, everyone. We need her value."},
        {"t": None, "speaker": "Vous", "text": "Hello, everyone. We need her value."},
        {"text": "arrow_downward Aller en bas"}]
out = clean_captions(caps)
assert len(out) == 3, out

# 2. contexte envoyé à l'IA : paroles + intervenants, zéro bruit
ctx = A._lost_context({"captions": caps, "context": "Désactiver le micro (Ctrl+d) Annoncer toutes les réactions"})
print(ctx)
assert "Vous : Everyone." in ctx and "Bouazizi May : Fish." in ctx
assert "micro" not in ctx and "arrow_downward" not in ctx

# 3. /api/lost : l'IA reçoit bien les paroles (on espionne l'appel)
seen = {}
def fake(**kw):
    seen.update(kw); return {"point": "x", "paragraph": "y", "quote": "", "provider": "test", "fallback": False,
                             "concept": "x", "example": "e", "analogy": "a", "steps": [], "formula": "", "check": {"question": "", "answer": ""}}
A.ai.explain_when_lost = fake
c = A.app.test_client()
r = c.post("/api/lost", json={"platform": "meet", "live": True, "captions": caps, "target": "fr", "source_title": "Meet"})
assert r.status_code == 200 and "We need her value" in seen["context"] and seen["live"] is True, (r.status_code, seen)
# 4. Meet sans aucun sous-titre → message clair, pas d'invention
r = c.post("/api/lost", json={"platform": "meet", "live": True, "captions": [{"text": "arrow_downward Aller en bas"}],
                              "context": "Désactiver le micro (Ctrl+d)", "target": "fr"})
assert r.get_json().get("needs_input"), r.get_json()
print("TOUS LES TESTS BACKEND OK")
