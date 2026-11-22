/* Neuro-Study — lecture fiable des sous-titres Google Meet.
 *
 * Pourquoi ce fichier : l'ancienne version ramassait TOUT le texte « aria-live » de la page, donc les infobulles
 * (« Désactiver le micro (Ctrl+d) »), les annonces de réactions, les boutons (« arrow_downward Aller en bas »)
 * et même notre propre surimpression. L'IA recevait ce bruit au lieu des paroles.
 *
 * Ici on ne lit QUE la zone de sous-titres de Meet, en ignorant boutons, icônes et notre interface,
 * puis on découpe par intervenant. Les fonctions pures (groupRuns, mergeBlocks, isNoise…) sont testées avec node.
 */
(function (root) {
  "use strict";

  // Texte d'interface Meet (FR / EN / AR) qui n'est jamais une parole.
  const NOISE_PHRASES = [
    /aller en bas/i, /jump to (the )?bottom/i, /انتقل إلى الأسفل/,
    /d[ée]sactiver le micro/i, /activer le micro/i, /turn (off|on) (the )?microphone/i,
    /annoncer toutes les r[ée]actions/i, /announce all reactions/i,
    /d[ée]sactiver la cam[ée]ra/i, /activer la cam[ée]ra/i, /turn (off|on) (the )?camera/i,
    /param[èe]tres des sous-titres/i, /caption settings/i, /sous-titres? (activ|d[ée]sactiv)/i,
    /quitter l'appel/i, /leave call/i, /lever la main/i, /raise hand/i,
    /pr[ée]senter maintenant/i, /present now/i,
  ];
  // Ligatures des icônes Material (« arrow_downward », « more_vert », « closed_caption_off »…) : minuscules + « _ ».
  const ICON_LIGATURE = /^[a-z]+(?:_[a-z0-9]+)+$/;
  const ICON_WORDS = new Set(["settings", "close", "mic", "videocam", "more_vert", "expand_more", "expand_less"]);

  const squash = (s) => String(s || "").replace(/\s+/g, " ").trim();

  function isNoise(text) {
    const t = squash(text);
    if (!t) return true;
    if (ICON_LIGATURE.test(t)) return true;
    if (NOISE_PHRASES.some((re) => re.test(t))) return true;
    return false;
  }

  // Retire les mots-icônes collés dans une ligne (« Vous arrow_downward Aller en bas » → « Vous »).
  function stripIcons(text) {
    return squash(String(text || "").split(/\s+/).filter((w) => !ICON_LIGATURE.test(w)).join(" "));
  }

  /* runs : [{ text, size (px), junk (bool) }] dans l'ordre d'affichage.
   * Dans Meet, le nom de l'intervenant est en PLUS PETIT que sa phrase → on s'en sert pour découper en blocs. */
  function groupRuns(runs) {
    const clean = [];
    for (const r of runs || []) {
      if (!r || r.junk) continue;
      const text = stripIcons(r.text);
      if (!text || isNoise(text)) continue;
      clean.push({ text, size: Number(r.size) || 0 });
    }
    if (!clean.length) return [];
    const maxSize = Math.max(...clean.map((r) => r.size));
    const hasSizes = clean.some((r) => r.size > 0 && r.size < maxSize - 2);
    const isName = (r) => hasSizes && r.size < maxSize - 2 && r.text.length <= 40;
    const blocks = [];
    let cur = null;
    for (const r of clean) {
      if (isName(r)) {
        if (r.text.length === 1) continue; // initiale d'avatar (« B ») : ce n'est pas un nom
        cur = { speaker: r.text, text: "" };
        blocks.push(cur);
      } else {
        if (!cur) { cur = { speaker: "", text: "" }; blocks.push(cur); }
        cur.text = squash(cur.text + " " + r.text);
      }
    }
    return blocks.filter((b) => b.text);
  }

  const norm = (s) => squash(s).toLowerCase().replace(/[.,!?;:…"'«»]/g, "");

  // Deux textes décrivent-ils la même phrase en cours (qui s'allonge ou se corrige) ?
  function sameUtterance(a, b) {
    const x = norm(a), y = norm(b);
    if (!x || !y) return false;
    if (x.includes(y) || y.includes(x)) return true;
    const n = Math.min(18, x.length, y.length);
    return n >= 8 && x.slice(0, n) === y.slice(0, n);
  }

  /* Fusionne les blocs lus à l'écran dans la transcription cumulée (les blocs de Meet disparaissent après quelques
   * secondes de silence ; leur texte s'allonge tant que la personne parle). Retourne true si quelque chose a changé. */
  function mergeBlocks(transcript, blocks, now, t, max = 60) {
    let changed = false;
    for (const b of blocks) {
      let hit = null;
      for (let i = transcript.length - 1; i >= Math.max(0, transcript.length - 8); i--) {
        const e = transcript[i];
        if (e.speaker === b.speaker && sameUtterance(e.text, b.text)) { hit = e; break; }
      }
      if (hit) {
        if (norm(hit.text) !== norm(b.text) && b.text.length >= hit.text.length - 12) { hit.text = b.text; hit.wall = now; changed = true; }
      } else {
        transcript.push({ t: t == null ? null : t, speaker: b.speaker, text: b.text, wall: now });
        changed = true;
      }
    }
    while (transcript.length > max) transcript.shift();
    return changed;
  }

  /* ----- partie DOM (non testée par node) ----- */
  const CAPTION_LABEL = /caption|sous-titre|subtitle|legenda|untertitel|subt[ií]tulo|sottotitol|ترجمة|ترجمات|نصوص/i;
  const OWN_UI = "#neuro-study-sidebar, #ns-sub-overlay";
  const JUNK_PARENT = 'button, [role="button"], [aria-hidden="true"], i, svg, .google-symbols, .google-material-icons, .material-icons, .material-symbols-outlined, [class*="icon" i]';

  function findRegion(doc) {
    const regions = Array.from(doc.querySelectorAll('[role="region"][aria-label], [aria-label][jsname]'))
      .filter((e) => CAPTION_LABEL.test(e.getAttribute("aria-label") || "") && !e.closest(OWN_UI));
    if (!regions.length) return null;
    return regions.sort((a, b) => (b.innerText || "").length - (a.innerText || "").length)[0];
  }

  function readRuns(region) {
    const runs = [];
    const w = region.ownerDocument.createTreeWalker(region, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const text = n.nodeValue;
      if (!text || !text.trim()) continue;
      const el = n.parentElement;
      if (!el) continue;
      const junk = Boolean(el.closest(OWN_UI) || el.closest(JUNK_PARENT));
      let size = 0;
      try { size = parseFloat(region.ownerDocument.defaultView.getComputedStyle(el).fontSize) || 0; } catch (_e) { /* taille inconnue */ }
      runs.push({ text, size, junk });
    }
    return runs;
  }

  // Retourne { active: bool, blocks: [{speaker,text}] }. active=false → les sous-titres Meet ne sont pas affichés.
  function readMeetCaptions(doc) {
    const region = findRegion(doc || document);
    if (!region) return { active: false, blocks: [] };
    return { active: true, blocks: groupRuns(readRuns(region)) };
  }

  // Bouton « Activer les sous-titres » de Meet (on ne clique JAMAIS s'il est déjà actif : libellé « Désactiver »).
  function findCaptionsButton(doc) {
    const on = /(activer|turn on|enable|تفعيل|تشغيل).*(sous-titre|caption|ترجمة)/i;
    return Array.from((doc || document).querySelectorAll("button[aria-label]")).find((b) => on.test(b.getAttribute("aria-label") || "")) || null;
  }

  const api = { isNoise, stripIcons, groupRuns, sameUtterance, mergeBlocks, readMeetCaptions, findCaptionsButton };
  root.NSMeet = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : globalThis);
