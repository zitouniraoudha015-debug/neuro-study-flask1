"""Rendu SVG sûr à partir d'une SPÉCIFICATION JSON fournie par l'IA.

L'IA ne renvoie jamais de SVG/HTML brut (risque d'injection) : elle décrit un schéma
(courbe, enchaînement, comparaison) et c'est ce module qui dessine, avec tout le texte échappé.
Types : curve | flow | comparison.  Retourne "" si la spécification est inutilisable.
"""
import html
import re

BG, GRID, AXIS, TXT, MUTED = "#0b1220", "#1e293b", "#64748b", "#e2e8f0", "#94a3b8"
PALETTE = ["#38bdf8", "#22c55e", "#f59e0b", "#f472b6"]
BOX = ["#1d4ed8", "#0f766e", "#b45309", "#7c3aed", "#be185d"]
_AR = re.compile(r"[؀-ۿ]")


def _e(s):
    return html.escape(str(s), quote=True)


def wrap(text, width, max_lines):
    """Coupe un texte en lignes de `width` caractères, max `max_lines` lignes (… si tronqué)."""
    words, lines, cur = str(text or "").split(), [], ""
    for w in words:
        if len(w) > width:
            w = w[: width - 1] + "…"
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;…") + "…"
    return lines or [""]


def _t(x, y, text, size=10, fill=TXT, anchor="start", weight=None):
    """<text> échappé ; gère l'arabe (sens de lecture droite → gauche)."""
    rtl = bool(_AR.search(str(text)))
    attrs = f'x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" font-family="system-ui,sans-serif"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if rtl:
        attrs += ' direction="rtl" unicode-bidi="plaintext"'
        anchor = {"start": "end", "end": "start"}.get(anchor, anchor)
    return f'<text {attrs} text-anchor="{anchor}">{_e(text)}</text>'


def _fmt(v):
    return f"{v:.0f}" if abs(v - round(v)) < 1e-6 else f"{v:.2f}".rstrip("0").rstrip(".")


def _svg(h, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 {h}" role="img" '
        f'style="width:100%;height:auto;display:block;border-radius:10px;background:{BG}">'
        f'<rect width="360" height="{h}" rx="10" fill="{BG}"/>{body}</svg>'
    )


def _title(v):
    return _t(12, 18, str(v.get("title") or "")[:48], 11.5, TXT, weight="700") if v.get("title") else ""


# ---------------------------------------------------------------- courbe
def _curve(v, show_numbers=True):
    series = []
    for s in (v.get("series") or [])[:3]:
        pts = []
        for p in (s.get("points") or [])[:14]:
            try:
                pts.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError, IndexError):
                continue
        if len(pts) >= 2:
            series.append((str(s.get("name") or "")[:24], pts))
    if not series:
        return ""

    xs = [p[0] for _, pts in series for p in pts]
    ys = [p[1] for _, pts in series for p in pts]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    if xmax == xmin:
        xmax = xmin + 1
    if ymax == ymin:
        ymax, ymin = ymax + 1, ymin - 1
    y0, y1 = ymin, ymax                      # vraies bornes (pour les graduations)
    pad = (ymax - ymin) * 0.08
    ymin, ymax = ymin - pad, ymax + pad

    L, R, T, B = 48, 344, 40, 124
    sx = lambda x: L + (x - xmin) / (xmax - xmin) * (R - L)
    sy = lambda y: B - (y - ymin) / (ymax - ymin) * (B - T)

    o = [_title(v)]
    if v.get("y_label"):
        o.append(_t(10, 32, str(v["y_label"])[:30], 9.5, MUTED))
    for i in range(4):  # grille
        gy = T + i * (B - T) / 3
        o.append(f'<line x1="{L}" y1="{gy:.1f}" x2="{R}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
    o.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{B}" stroke="{AXIS}" stroke-width="1.6"/>')
    o.append(f'<line x1="{L}" y1="{B}" x2="{R}" y2="{B}" stroke="{AXIS}" stroke-width="1.6"/>')
    if show_numbers:
        o.append(_t(L - 5, sy(y0) + 3, _fmt(y0), 8.5, MUTED, "end"))
        o.append(_t(L - 5, sy(y1) + 3, _fmt(y1), 8.5, MUTED, "end"))
        o.append(_t(L, B + 13, _fmt(xmin), 8.5, MUTED, "middle"))
        o.append(_t(R, B + 13, _fmt(xmax), 8.5, MUTED, "middle"))
    if v.get("x_label"):
        o.append(_t((L + R) / 2, 152, str(v["x_label"])[:40], 9.5, MUTED, "middle"))

    for i, (name, pts) in enumerate(series):
        c = PALETTE[i % len(PALETTE)]
        poly = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
        dash = ' stroke-dasharray="5,3"' if i == 1 else ""
        o.append(f'<polyline points="{poly}" fill="none" stroke="{c}" stroke-width="2.6"{dash} stroke-linejoin="round"/>')
        for x, y in pts:
            o.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3" fill="{c}"/>')
    named = [(n, PALETTE[i % len(PALETTE)]) for i, (n, _) in enumerate(series) if n]
    lx = 12
    for n, c in named:
        o.append(f'<circle cx="{lx + 4}" cy="165" r="4" fill="{c}"/>')
        o.append(_t(lx + 12, 168.5, n, 9.5, TXT))
        lx += 22 + len(n) * 5.6
    return _svg(174, "".join(o))


# ---------------------------------------------------------------- enchaînement
def _flow(v, **_):
    nodes = [str(n).strip() for n in (v.get("nodes") or []) if str(n).strip()][:5]
    if len(nodes) < 2:
        return ""
    top = 30 if v.get("title") else 12
    o = [_title(v), '<defs><marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
         f'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{PALETTE[0]}"/></marker></defs>']
    n = len(nodes)

    if n <= 3:  # horizontal
        gap = 22
        bw = (336 - (n - 1) * gap) / n
        cpl = max(8, int(bw / 5.8))
        wrapped = [wrap(t, cpl, 4) for t in nodes]
        bh = 26 + 13 * max(len(w) for w in wrapped)
        for i, lines in enumerate(wrapped):
            x = 12 + i * (bw + gap)
            o.append(f'<rect x="{x:.1f}" y="{top}" width="{bw:.1f}" height="{bh}" rx="9" fill="{BOX[i % 5]}"/>')
            o.append(f'<circle cx="{x + 12:.1f}" cy="{top + 12}" r="8" fill="#0b1220" fill-opacity=".45"/>')
            o.append(_t(x + 12, top + 15.5, str(i + 1), 9.5, "#fff", "middle", "700"))
            for k, ln in enumerate(lines):
                o.append(_t(x + bw / 2, top + 30 + k * 13, ln, 10.5, "#fff", "middle"))
            if i < n - 1:
                ym = top + bh / 2
                o.append(f'<line x1="{x + bw + 2:.1f}" y1="{ym}" x2="{x + bw + gap - 3:.1f}" y2="{ym}" '
                         f'stroke="{PALETTE[0]}" stroke-width="2" marker-end="url(#ar)"/>')
        return _svg(int(top + bh + 14), "".join(o))

    # vertical
    y, rowh, gap = top, 34, 14
    for i, t in enumerate(nodes):
        lines = wrap(t, 52, 2)
        h = 18 + 12.5 * len(lines)
        o.append(f'<rect x="12" y="{y}" width="336" height="{h:.0f}" rx="9" fill="{BOX[i % 5]}"/>')
        o.append(f'<circle cx="28" cy="{y + h / 2:.1f}" r="9" fill="#0b1220" fill-opacity=".45"/>')
        o.append(_t(28, y + h / 2 + 3.5, str(i + 1), 10, "#fff", "middle", "700"))
        for k, ln in enumerate(lines):
            o.append(_t(46, y + 15 + k * 12.5, ln, 10.5, "#fff"))
        if i < n - 1:
            o.append(f'<line x1="180" y1="{y + h:.1f}" x2="180" y2="{y + h + gap - 2:.1f}" '
                     f'stroke="{PALETTE[0]}" stroke-width="2" marker-end="url(#ar)"/>')
        y += h + gap
    return _svg(int(y - gap + 14), "".join(o))


# ---------------------------------------------------------------- comparaison
def _comparison(v, **_):
    cols = []
    for k in ("left", "right"):
        c = v.get(k) or {}
        items = [str(i).strip() for i in (c.get("items") or []) if str(i).strip()][:4]
        if str(c.get("title") or "").strip() or items:
            cols.append((str(c.get("title") or "")[:24], items))
    if len(cols) != 2:
        return ""
    top = 30 if v.get("title") else 12
    o = [_title(v)]
    wrapped = [[wrap(i, 24, 3) for i in items] for _, items in cols]
    body_h = max(sum(len(l) * 12 + 6 for l in w) for w in wrapped)
    H = 30 + body_h + 10
    for ci, (title, _) in enumerate(cols):
        x = 12 + ci * 174
        o.append(f'<rect x="{x}" y="{top}" width="162" height="{H}" rx="9" fill="{GRID}"/>')
        o.append(f'<rect x="{x}" y="{top}" width="162" height="22" rx="9" fill="{BOX[ci * 2]}"/>')
        o.append(_t(x + 81, top + 15, title, 11, "#fff", "middle", "700"))
        y = top + 38
        for lines in wrapped[ci]:
            o.append(f'<circle cx="{x + 11}" cy="{y - 3}" r="2.4" fill="{PALETTE[ci]}"/>')
            for ln in lines:
                o.append(_t(x + 19, y, ln, 10, TXT))
                y += 12
            y += 6
    return _svg(int(top + H + 10), "".join(o))


RENDERERS = {"curve": _curve, "flow": _flow, "comparison": _comparison}


def render(spec, show_numbers=True):
    """spec = {"type": "curve|flow|comparison", ...} → chaîne SVG, ou "" si invalide."""
    if not isinstance(spec, dict):
        return ""
    fn = RENDERERS.get(str(spec.get("type", "")).strip().lower())
    if not fn:
        return ""
    try:
        return fn(spec, show_numbers=show_numbers) if fn is _curve else fn(spec)
    except Exception:
        return ""


def flow_from_sentences(sentences, title="", limit=4):
    """Repli sans IA : transforme les dernières phrases entendues en enchaînement d'étapes."""
    nodes = [" ".join(s.split()[:10]) for s in sentences if len(s.split()) >= 2][-limit:]
    return render({"type": "flow", "title": title, "nodes": nodes}) if len(nodes) >= 2 else ""
