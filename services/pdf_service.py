"""Extraction PDF/texte propre + découpage PAR NOTION (titre, définition, paragraphe complet).

Principe : on ne coupe JAMAIS au milieu d'une phrase ni d'une puce. Un bloc = une notion :
  - un nouveau titre commence un nouveau bloc ;
  - une définition (« X est… », « On appelle X… », « Définition : … ») commence un nouveau bloc ;
  - un paragraphe trop long est coupé entre deux phrases (ou deux puces) entières.
"""
import re
from collections import Counter

STOP = set("""le la les un une des de du et en à au aux ce ces cette est sont pour par sur dans avec qui que quoi
ne pas plus ou où se sa son ses leur leurs il elle ils elles on nous vous je tu mais donc or ni car comme être
avoir fait faire peut très aussi entre sans sous ainsi lors alors cela celui celle dont chaque tout tous toute
the of and to in is for with that this are was from""".split())
GENERIC = set("""exemple exemples notion notions permet permettent peut peuvent doit doivent plusieurs différents différentes
également afin selon lorsque cependant tandis quelque quelques souvent toujours ceci chose choses façon manière
type types partie parties comme ainsi donc ensuite puis montre montrent signifie indique indiquent""".split())
WORD = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-]{3,}")
ACR = re.compile(r"\b[A-Z]{3,}\b|\b[A-Z][a-z]+[A-Z]\w*\b")
MIN_WORDS = 18                                           # en dessous : trop court pour être une notion seule

LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "\u00a0": " ", "\u200b": "", "\u00ad": ""}
BULLET = re.compile(r"^\s*(?:[•▪■●◦‣▸►➢\-–—*\ue000-\uf8ff]\s+|o\s+(?=\S))")
PAGENUM = re.compile(r"^\s*(?:page\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?\s*$", re.I)
HEAD_NUM = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?|[IVXLC]+[.)]|[A-Z][.)])\s+\S")
HEAD_WORD = re.compile(r"^(?:chapitre|partie|section|titre|module|séance|introduction|conclusion)\b", re.I)
LABEL = re.compile(r"^(définition|propriété|théorème|remarque|exemple|exercice|à retenir|attention|rappel|formule|règle|astuce)\b\s*\d*\s*[:.\-–]?\s*", re.I)
ABBR = {"ex", "etc", "cf", "fig", "env", "vs", "p", "pp", "m", "mme", "dr", "pr", "sec", "min", "max", "approx", "av", "apr"}


# ------------------------------------------------------------------ outils texte
def keywords(text, n=5):
    c = Counter(w.lower() for w in WORD.findall(text) if w.lower() not in STOP)
    return [w for w, _ in sorted(c.items(), key=lambda kv: (-kv[1], -len(kv[0])))[:n]]


def sentences(text):
    """Phrases entières (ne coupe pas après « ex. », « etc. », « Fig. »…) ; chaque puce reste une unité."""
    out = []
    for para in re.split(r"\n{2,}", text):
        buf = ""
        for p in re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ý«\"“(•\d])|\n(?=•\s)", para):
            buf = f"{buf} {p}".strip() if buf else p.strip()
            last = buf.rsplit(None, 1)[-1].rstrip(".").lower() if buf else ""
            if last in ABBR:
                continue
            out.append(buf); buf = ""
        if buf:
            out.append(buf)
    return [s for s in out if s]


def _clip(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def _norm(s):
    for a, b in LIG.items():
        s = s.replace(a, b)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)


# ------------------------------------------------------------------ nettoyage / reconstruction des paragraphes
def is_heading(line, prev_ended):
    l = line.strip()
    if not l or len(l) > 110 or l.startswith("•"):
        return False
    if l.startswith("#"):
        return True
    words = l.split()
    if re.search(r"[.!?;,]$", l) or (LABEL.match(l) and l.endswith(":")):
        return False
    if (HEAD_NUM.match(l) and len(words) <= 25) or (HEAD_WORD.match(l) and len(words) <= 12):
        return True
    if len(words) > 12:
        return False
    if sum(c.isalpha() for c in l) >= 4 and l.upper() == l:
        return True
    return prev_ended and len(words) <= 9 and l[0].isupper() and not l.endswith(":")


def _junk_keys(pages):
    """En-têtes / pieds de page : lignes (chiffres ignorés) répétées sur la moitié des pages."""
    if len(pages) < 3:
        return set()
    c = Counter()
    for lines in pages:
        ne = [l.strip() for l in lines if l.strip()]
        for l in set(ne[:2] + ne[-2:]):
            c[re.sub(r"\d+", "#", _norm(l).lower())] += 1
    return {k for k, v in c.items() if v >= max(3, 0.5 * len(pages))}


def _page_blocks(lines, junk):
    lines = [_norm(l).rstrip() for l in lines]
    maxlen = max((len(l) for l in lines if l.strip()), default=0)
    blocks, cur, prev_len, last_head = [], "", 0, False
    ended = lambda s: (not s) or bool(re.search(r"[.!?:»)]$", s))

    def flush():
        nonlocal cur
        if cur.strip():
            blocks.append(("p", cur.strip()))
        cur = ""

    for raw in lines:
        line = raw.strip()
        if not line:
            flush(); last_head = False; continue
        if PAGENUM.match(line) or re.sub(r"\d+", "#", line.lower()) in junk:
            continue
        is_b = bool(BULLET.match(raw))
        if last_head and not is_b and line[:1].islower() and len(line.split()) <= 10 and blocks and blocks[-1][0] == "h":
            blocks[-1] = ("h", blocks[-1][1] + " " + line); continue          # titre sur deux lignes
        if is_b:
            flush(); cur = "• " + BULLET.sub("", raw, count=1).strip(); prev_len = len(line); last_head = False; continue
        if is_heading(line, ended(cur)):
            flush(); blocks.append(("h", re.sub(r"^#+\s*", "", line))); last_head = True; prev_len = len(line); continue
        last_head = False
        if LABEL.match(line) and ended(cur):
            flush(); cur = line
        elif cur and re.search(r"[A-Za-zÀ-ÿ]-$", cur) and line[:1].islower():
            cur = cur[:-1] + line                                             # mot coupé en fin de ligne
        elif cur and ended(cur) and not cur.startswith("•") and line[:1].isupper() and prev_len < 0.72 * maxlen:
            flush(); cur = line                                               # fin de paragraphe (ligne courte)
        else:
            cur = f"{cur} {line}".strip()
        prev_len = len(line)
    flush()
    return blocks


def clean_blocks(pages):
    junk, blocks = _junk_keys(pages), []
    for lines in pages:
        pb = _page_blocks(lines, junk)
        if blocks and pb and blocks[-1][0] == "p" and pb[0][0] == "p" and pb[0][1][:1].islower() \
                and not re.search(r"[.!?:»)]$", blocks[-1][1]):
            blocks[-1] = ("p", blocks[-1][1] + " " + pb[0][1]); pb = pb[1:]    # paragraphe à cheval sur deux pages
        blocks += pb
    out = []
    for k, t in blocks:                                                        # les puces restent avec leur introduction
        if out and k == "p" and t.startswith("• ") and out[-1][0] == "p" and \
                (out[-1][1].endswith(":") or out[-1][1].split("\n")[-1].startswith("• ")):
            out[-1] = ("p", out[-1][1] + "\n" + t)
        else:
            out.append((k, t))
    return out


def extract_text(file_storage):
    name = (file_storage.filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        pages = [(p.extract_text() or "").split("\n") for p in PdfReader(file_storage.stream).pages]
    else:
        pages = [file_storage.read().decode("utf-8", errors="ignore").splitlines()]
    return "\n\n".join(("# " + t) if k == "h" else t for k, t in clean_blocks(pages))


# ------------------------------------------------------------------ définitions et mots-clés
_ART = r"(?:(?:une|un|les|le|la|des|de la|du)\s+|l['’]|d['’])?"
_VERBS = r"(?:est|sont|désigne|désignent|signifie|correspond à|se définit comme|se définit par|représente|consiste en|consiste à|mesure|indique|permet de)"
DEF_A = re.compile(rf"^{_ART}(?P<t>[A-Za-zÀ-ÿ0-9][\wÀ-ÿ'’\-/ ]{{1,45}}?)\s+{_VERBS}\b", re.I)
DEF_B = re.compile(rf"^on (?:appelle|nomme)\s+{_ART}(?P<t>[^,.;:()]{{2,40}}?)\s+(?:toute?|tout|un|une|le|la|l['’]|les|des|lorsque|quand|ce qui|celui|celle)\b", re.I)
DEF_COLON = re.compile(r"^(?:•\s*)?(?P<t>[^:•.]{2,40}?)\s*:\s+\S")
_PRON = {"il", "elle", "ils", "elles", "ce", "cela", "ceci", "c", "on", "nous", "vous", "cette", "ces", "celui", "celle", "par", "qui", "que"}


def _term_ok(t):
    w = t.lower().split()
    return bool(w) and len(w) <= 5 and w[0] not in _PRON and not re.search(r"\b(que|qui|dont|où|si|lorsque)\b", t.lower()) and "," not in t


def find_definition(text):
    """(terme, phrase, forte) pour la première phrase d'un bloc ; ("", "", False) sinon."""
    ss = sentences(text.strip())
    if not ss:
        return "", "", False
    s = re.sub(r"^•\s*", "", ss[0])
    label = LABEL.match(s)
    if label and label.group(1).lower() == "définition":
        rest = s[label.end():]
        m = DEF_A.match(rest) or DEF_COLON.match(rest)
        return ((m.group("t").strip() if m else ""), ss[0], True)
    if label:                                                                   # exemple, remarque… : pas une notion
        return "", "", False
    for rx, strong in ((DEF_B, True), (DEF_A, True)):
        m = rx.match(s)
        if m and _term_ok(m.group("t")):
            return m.group("t").strip(), ss[0], strong
    m = DEF_COLON.match(ss[0])
    if m and _term_ok(m.group("t")) and len(m.group("t").split()) <= 4:
        return m.group("t").strip(), ss[0], False
    return "", "", False


def key_terms(text, term="", n=4):
    """Termes importants : le terme défini, expressions répétées (« corrélation négative »), mots fréquents."""
    out = [term.lower()] if term else []
    for a in dict.fromkeys(ACR.findall(text)):                                  # sigles et noms propres techniques (TDAH, MediaPipe…)
        if len(out) < 2 and a.lower() not in out:
            out.append(a.lower())
    words = [w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-]*", text)]   # tous les mots : « montre DES valeurs » ≠ « montre valeurs »
    bad = STOP | GENERIC
    big = Counter(f"{a} {b}" for a, b in zip(words, words[1:]) if a not in bad and b not in bad and len(a) >= 4 and len(b) >= 4)
    for g, v in big.most_common(3):
        if v >= 2 and not any(g in o or o in g for o in out):
            out.append(g)
    c = Counter(w for w in words if w not in bad and len(w) >= 5)
    for w, v in sorted(c.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        if len(out) >= n:
            break
        if (v >= 2 or not out) and not any(w in o for o in out):
            out.append(w)
    return out[:n]


# ------------------------------------------------------------------ découpage par notion
def _split_long(t, soft, hard):
    """Un paragraphe plus long que `hard` est coupé entre deux phrases (ou puces) entières, jamais au milieu."""
    if len(t.split()) <= hard:
        return [t]
    bullets = bool(re.search(r"(^|\n)• ", t))
    units = [u.strip() for u in t.split("\n") if u.strip()] if bullets else sentences(t)
    groups, cur, w = [], [], 0
    for u in units:
        uw = len(u.split())
        if cur and w + uw > soft and not cur[-1].rstrip().endswith(":"):      # une intro « … : » reste avec sa suite
            groups.append(cur); cur, w = [], 0
        cur.append(u); w += uw
    if cur:
        groups.append(cur)
    if len(groups) > 1 and sum(len(u.split()) for u in groups[-1]) < MIN_WORDS:
        groups[-2] += groups.pop()
    return [("\n" if bullets else " ").join(g) for g in groups]


def _title_from(text):
    """Titre court : le terme d'une liste « Terme : … », sinon le début de la première phrase."""
    leads = [m.group("t").strip() for ln in text.split("\n") if ln.startswith("• ")
             for m in [DEF_COLON.match(ln)] if m and _term_ok(m.group("t")) and len(m.group("t").split()) <= 4]
    if len(leads) >= 2:
        return ", ".join(leads[:3]) + ("…" if len(leads) > 3 else "")
    s = re.sub(r"^•\s*", "", sentences(text)[0] if text.strip() else "")
    s = LABEL.sub("", s) or s
    head = re.split(r"\s*:\s*", s, maxsplit=1)[0]                      # « Intro : détail » → « Intro »
    return _clip(head if 2 <= len(head.split()) <= 12 else s, 60)


def _marked(text):
    """Texte brut sans marqueurs « # » (ex. .txt, cours d'exemple) : on le nettoie comme un PDF."""
    return "\n\n".join(("# " + t) if k == "h" else t for k, t in clean_blocks([text.splitlines()]))


def to_sections(text, max_words=70):
    if not re.search(r"(?m)^# ", text):
        text = _marked(text)
    blocks = []
    for b in re.split(r"\n\s*\n", text.strip()):
        b = b.strip()
        if b:
            blocks.append(("h", b[2:].strip()) if b.startswith("# ") else ("p", b))
    soft, hard = max(25, int(max_words)), max(25, int(max_words)) * 2
    chunks, heading, cur = [], "", None

    def flush():
        nonlocal cur
        if cur and cur["paras"]:
            chunks.append(cur)
        cur = None

    for kind, t in blocks:
        if kind == "h":
            flush(); heading = t; continue
        for piece in _split_long(t, soft, hard):
            w = len(piece.split())
            strong = find_definition(piece)[2]
            if cur and (strong or (cur["words"] + w > soft and cur["words"] >= MIN_WORDS)):
                flush()
            if not cur:
                cur = {"heading": heading, "paras": [], "words": 0}
            cur["paras"].append(piece); cur["words"] += w
    flush()

    merged = []                                                                # un bloc minuscule rejoint le précédent
    for c in chunks:
        if merged and c["words"] < MIN_WORDS and merged[-1]["heading"] == c["heading"] and merged[-1]["words"] + c["words"] <= hard:
            merged[-1]["paras"] += c["paras"]; merged[-1]["words"] += c["words"]
        else:
            merged.append(c)

    out, seen = [], Counter()
    for i, c in enumerate(merged):
        body = "\n\n".join(c["paras"])
        term, _, strong = find_definition(body)
        seen[c["heading"]] += 1
        if c["heading"] and seen[c["heading"]] == 1:
            title = c["heading"]
        elif term and strong:
            title = "Définition : " + term
        else:
            title = _title_from(body)
        first = re.sub(r"^•\s*", "", sentences(body)[0]) if body.strip() else ""
        out.append({"id": i, "title": _clip(title, 120), "text": body, "term": term, "heading": c["heading"],
                    "kind": "definition" if (term and strong) else ("liste" if "• " in body else "notion"),
                    "keywords": key_terms(body, term, 4), "summary": _clip(first, 240)})
    return out
