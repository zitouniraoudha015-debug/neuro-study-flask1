/* Neuro-Study Companion — content script (YouTube + Google Meet)
 *  - sous-titres traduits dans la langue choisie (fr/en/ar), affichés sur la vidéo
 *  - score de compréhension estimé : caméra (100 % locale) + « Je suis perdu » + retours en arrière
 *  - « Je suis perdu » : repère le point non compris à l'instant T, l'explique (texte, analogie, exemple,
 *    étapes, schéma/courbe, image, mini-question) via l'IA du serveur Flask, et l'enregistre dans l'historique
 */
(() => {
  "use strict";
  if (window.__neuroStudyLoaded) return;
  const isMeet = location.hostname.includes("meet.google.com");
  const isYouTube = location.hostname.includes("youtube.com");
  if (!isMeet && !isYouTube) return;
  window.__neuroStudyLoaded = true;

  const WEB_BASE = "http://127.0.0.1:5000";
  const WINDOW_MS = 5 * 60 * 1000; // les pénalités de compréhension s'effacent après 5 min
  const LANG_LABELS = { fr: "Français", ar: "العربية / Derja", en: "English" };

  // ------------------------------------------------------------------ état
  const prefs = { lang: "fr", profile: "standard", pause: true, subs: true, collapsed: false };
  let buffer = []; // sous-titres récents : { t (s vidéo ou null), text, wall }
  let lastCaption = "";
  let currentKey = "";
  let connected = false;
  let providers = null; // null = inconnu, [] = aucune clé IA
  let tab = "help";
  let current = null; // entrée affichée dans l'onglet Aide
  let loading = false;
  let historyItems = [];
  let historyScope = "all";
  let pausedByUs = false;
  const payloads = new Map(); // id d'entrée -> requête d'origine (pour « Expliquer autrement »)
  const lostTimes = [];
  const rewindTimes = [];
  const cam = { on: false, stream: null, ema: null, signals: [], prevLum: null, detector: null, busy: false, lowSince: 0 };
  let lastNudge = 0;
  let lastT = null;
  const timers = [];

  // ------------------------------------------------------------------ utilitaires
  const $ = (id) => document.getElementById(id);
  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));

  function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.style.cssText = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  function fmtTime(sec) {
    if (typeof sec !== "number" || !isFinite(sec)) return "";
    const s = Math.floor(sec);
    const hh = Math.floor(s / 3600);
    const mm = Math.floor((s % 3600) / 60);
    const ss = String(s % 60).padStart(2, "0");
    return hh ? `${hh}:${String(mm).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
  }

  const alive = () => {
    try {
      return Boolean(chrome.runtime && chrome.runtime.id);
    } catch (_e) {
      return false;
    }
  };

  const store = {
    get: (keys) =>
      new Promise((resolve) => {
        try {
          chrome.storage.local.get(keys, (v) => resolve(v || {}));
        } catch (_e) {
          resolve({});
        }
      }),
    set: (obj) => {
      try {
        chrome.storage.local.set(obj);
      } catch (_e) {
        /* stockage indisponible : on continue sans */
      }
    },
  };

  function callBackend(endpoint, method = "POST", body = null, timeout = 30000) {
    return new Promise((resolve) => {
      if (!alive()) return resolve(null);
      try {
        chrome.runtime.sendMessage({ type: "API_CALL", endpoint, method, body, timeout }, (res) => {
          void chrome.runtime.lastError; // évite « Unchecked runtime.lastError »
          resolve(res && res.ok ? res.data : null);
        });
      } catch (_e) {
        resolve(null);
      }
    });
  }

  function pingBackend() {
    return new Promise((resolve) => {
      if (!alive()) return resolve({ connected: false });
      try {
        chrome.runtime.sendMessage({ type: "PING_BACKEND" }, (res) => {
          void chrome.runtime.lastError;
          resolve(res || { connected: false });
        });
      } catch (_e) {
        resolve({ connected: false });
      }
    });
  }

  // SVG venant du serveur : on le re-parse et on retire tout ce qui pourrait exécuter du code.
  function safeSvg(str) {
    try {
      const doc = new DOMParser().parseFromString(String(str || ""), "image/svg+xml");
      const svg = doc.documentElement;
      if (!svg || svg.nodeName.toLowerCase() !== "svg" || doc.querySelector("parsererror")) return null;
      svg.querySelectorAll("script,foreignObject,iframe,object,embed,style").forEach((n) => n.remove());
      svg.querySelectorAll("*").forEach((n) => {
        [...n.attributes].forEach((a) => {
          if (/^on/i.test(a.name) || /javascript:/i.test(a.value)) n.removeAttribute(a.name);
        });
      });
      return document.importNode(svg, true);
    } catch (_e) {
      return null;
    }
  }

  // ------------------------------------------------------------------ vidéo / source
  const video = () => document.querySelector("video.html5-main-video") || document.querySelector("video");
  const videoTime = () => {
    const v = video();
    return isYouTube && v && isFinite(v.currentTime) ? Math.round(v.currentTime * 10) / 10 : null;
  };

  function videoId() {
    if (!isYouTube) return "";
    const u = new URL(location.href);
    return u.searchParams.get("v") || (location.pathname.match(/^\/(?:shorts|live|embed)\/([\w-]{11})/) || [])[1] || "";
  }

  function sourceInfo() {
    const titleEl = isYouTube ? document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.title") : null;
    return {
      platform: isYouTube ? "youtube" : "meet",
      title: (titleEl && titleEl.textContent.trim()) || document.title || "Session en cours",
      url: location.href,
      video_id: videoId(),
    };
  }

  function watchUrl(src, t) {
    if (src && src.video_id && src.platform === "youtube") {
      return `https://www.youtube.com/watch?v=${src.video_id}${typeof t === "number" ? `&t=${Math.floor(t)}s` : ""}`;
    }
    return (src && src.url) || "";
  }

  function seekTo(src, t) {
    const sameVideo = isYouTube && src && src.video_id && src.video_id === videoId();
    const v = video();
    if (sameVideo && v && typeof t === "number") {
      lastT = null; // notre propre déplacement ne compte pas comme « retour en arrière »
      v.currentTime = Math.max(0, t - 2);
      v.play().catch(() => {});
    } else if (src && (src.url || src.video_id)) {
      window.open(watchUrl(src, t), "_blank", "noopener");
    }
  }

  // ------------------------------------------------------------------ score de compréhension
  function recent(list) {
    const now = Date.now();
    while (list.length && now - list[0] > WINDOW_MS) list.shift();
    return list.length;
  }

  function computeScore() {
    const lost = recent(lostTimes);
    const rew = recent(rewindTimes);
    const base = cam.on && cam.ema != null ? cam.ema : 80;
    const penLost = Math.min(lost, 4) * 10;
    const penRew = Math.min(rew, 4) * 5;
    const score = clamp(Math.round(base - penLost - penRew), 0, 100);
    const tip =
      `Estimation (pas une mesure médicale)\n` +
      `Attention caméra : ${cam.on && cam.ema != null ? Math.round(cam.ema) + " %" : "caméra éteinte (80 % par défaut)"}\n` +
      `« Je suis perdu » (5 min) : −${penLost}\nRetours en arrière (5 min) : −${penRew}` +
      (cam.signals.length ? `\nSignaux : ${cam.signals.join(", ")}` : "");
    return { score, tip };
  }

  function renderScore() {
    const badge = $("ns-focus-badge");
    if (!badge) return;
    const { score, tip } = computeScore();
    badge.textContent = `Compréhension ≈ ${score} %${cam.on ? "" : " (sans caméra)"}`;
    badge.title = tip;
    badge.style.background = score >= 70 ? "#16a34a" : score >= 45 ? "#d97706" : "#dc2626";

    // Aide proactive : score bas pendant 15 s → on suggère le bouton (sans appeler l'IA tout seul)
    const now = Date.now();
    if (score < 45) cam.lowSince ||= now;
    else cam.lowSince = 0;
    const hint = $("ns-hint");
    if (cam.lowSince && now - cam.lowSince > 15000 && now - lastNudge > 180000 && !loading) {
      lastNudge = now;
      $("ns-lost-btn").classList.add("ns-pulse");
      hint.textContent = "Tu sembles décrocher. Besoin d'aide ? Clique sur « Je suis perdu ».";
      hint.hidden = false;
    }
    if (score >= 60 && !hint.hidden && now - lastNudge > 20000) clearNudge();
  }

  function clearNudge() {
    const hint = $("ns-hint");
    if (hint) hint.hidden = true;
    const btn = $("ns-lost-btn");
    if (btn) btn.classList.remove("ns-pulse");
  }

  // ------------------------------------------------------------------ courbe de concentration (caméra)
  // Un point toutes les 3 s (concentration lissée en %), tracé en fonction du temps. Points ROUGES sous le seuil de 50 %.
  // Tout est dessiné dans un <canvas> : aucune image n'est envoyée ni stockée, seulement des pourcentages.
  const LOW = 50;
  const curve = { pts: [], t0: 0, last: 0, brk: false, map: null };

  function curveSample() {
    const nowMs = Date.now();
    if (cam.ema == null || nowMs - curve.last < 3000) return;
    const v = video();
    if (isYouTube && v && v.paused) return; // vidéo en pause : pas de points
    curve.last = nowMs;
    if (!curve.t0) curve.t0 = nowMs;
    curve.pts.push({ x: (nowMs - curve.t0) / 1000, v: Math.round(cam.ema), vt: videoTime(), brk: curve.brk });
    curve.brk = false;
    if (curve.pts.length > 900) curve.pts.shift(); // ≈ 45 min
    drawCurve();
  }

  function curveReset() {
    curve.pts = [];
    curve.t0 = 0;
    curve.brk = false;
    drawCurve();
  }

  function drawCurve() {
    const c = $("ns-curve");
    const box = $("ns-curve-box");
    if (!c || !box) return;
    box.hidden = !(cam.on || curve.pts.length);
    if (box.hidden) return;
    const dpr = window.devicePixelRatio || 1;
    const W = c.clientWidth || 320;
    const H = 120;
    if (c.width !== Math.round(W * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const padL = 26, padR = 8, padT = 8, padB = 18;
    const iw = W - padL - padR, ih = H - padT - padB;
    const pts = curve.pts;
    const xmax = Math.max(60, pts.length ? pts[pts.length - 1].x : 60);
    const X = (x) => padL + (x / xmax) * iw;
    const Y = (v) => padT + (1 - v / 100) * ih;
    curve.map = { padL, iw, xmax };

    g.font = "10px system-ui, Arial";
    g.lineWidth = 1;
    g.fillStyle = "rgba(239,68,68,.09)"; // zone « concentration basse »
    g.fillRect(padL, Y(LOW), iw, Y(0) - Y(LOW));
    g.strokeStyle = "#334155";
    g.fillStyle = "#94a3b8";
    [0, 50, 100].forEach((v) => {
      g.beginPath(); g.moveTo(padL, Y(v)); g.lineTo(W - padR, Y(v)); g.stroke();
      g.fillText(String(v), 2, Y(v) + 3);
    });
    g.setLineDash([4, 3]); // seuil
    g.strokeStyle = "#ef4444";
    g.beginPath(); g.moveTo(padL, Y(LOW)); g.lineTo(W - padR, Y(LOW)); g.stroke();
    g.setLineDash([]);

    g.strokeStyle = "#2dd4bf"; // la courbe
    g.lineWidth = 2;
    g.lineJoin = "round";
    g.beginPath();
    let pen = false;
    pts.forEach((p) => {
      if (!pen || p.brk) { g.moveTo(X(p.x), Y(p.v)); pen = true; } else g.lineTo(X(p.x), Y(p.v));
    });
    g.stroke();
    g.fillStyle = "#ef4444"; // points rouges : concentration < 50 %
    pts.forEach((p) => {
      if (p.v < LOW) { g.beginPath(); g.arc(X(p.x), Y(p.v), 3.6, 0, Math.PI * 2); g.fill(); }
    });
    g.fillStyle = "#94a3b8";
    g.fillText("0:00", padL, H - 4);
    const end = fmtTime(xmax);
    g.fillText(end, W - padR - g.measureText(end).width, H - 4);

    const now = $("ns-curve-now");
    if (now) {
      const last = pts[pts.length - 1];
      now.textContent = last ? `${last.v} %` : "";
      now.style.color = last && last.v < LOW ? "#fca5a5" : "#86efac";
    }
    renderLowList();
  }

  function renderLowList() { // « Baisses » = passages consécutifs sous 50 % ; cliquables sur YouTube pour revenir dessus
    const el = $("ns-curve-low");
    if (!el) return;
    const runs = [];
    let cur = null;
    curve.pts.forEach((p) => {
      if (p.v < LOW) { if (!cur) cur = { a: p, b: p }; cur.b = p; } else if (cur) { runs.push(cur); cur = null; }
    });
    if (cur) runs.push(cur);
    el.replaceChildren(
      runs.length ? h("span", { class: "ns-low-lab" }, `Baisses (${runs.length}) :`) : null,
      ...runs.slice(-6).map((r) =>
        isYouTube && r.a.vt != null
          ? h("button", { class: "ns-chip", title: "Revenir à ce passage", type: "button",
              onclick: () => { const v = video(); if (v) v.currentTime = Math.max(0, r.a.vt - 5); } }, fmtTime(r.a.vt))
          : h("span", { class: "ns-chip ns-chip-static" }, fmtTime(r.a.vt != null ? r.a.vt : r.a.x)))
    );
  }

  function curveHover(e) { // survol : valeur et instant du point le plus proche
    const c = $("ns-curve");
    const cap = $("ns-curve-cap");
    if (!c || !cap || !curve.map || !curve.pts.length) return;
    const r = c.getBoundingClientRect();
    const x = ((e.clientX - r.left - curve.map.padL) / curve.map.iw) * curve.map.xmax;
    const p = curve.pts.reduce((a, b) => (Math.abs(b.x - x) < Math.abs(a.x - x) ? b : a));
    cap.textContent = `${fmtTime(p.vt != null ? p.vt : p.x)} → concentration ${p.v} %${p.v < LOW ? " (basse)" : ""}`;
  }

  // ------------------------------------------------------------------ caméra (100 % locale, aucune image envoyée)
  const FW = 64;
  const FH = 36;
  let canvas = null;

  function analyzeHeuristic(vid) {
    canvas ||= Object.assign(document.createElement("canvas"), { width: FW, height: FH });
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return { raw: 70, signals: [] };
    ctx.drawImage(vid, 0, 0, FW, FH);
    const px = ctx.getImageData(0, 0, FW, FH).data;
    const lum = new Uint8Array(FW * FH);
    let bright = 0;
    let skin = 0;
    let sx = 0;
    let diff = 0;
    for (let i = 0, p = 0; i < px.length; i += 4, p++) {
      const r = px[i], g = px[i + 1], b = px[i + 2];
      const y = 0.299 * r + 0.587 * g + 0.114 * b;
      lum[p] = y;
      bright += y;
      if (cam.prevLum) diff += Math.abs(y - cam.prevLum[p]);
      const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b;
      const cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
      if (y > 40 && cb > 77 && cb < 127 && cr > 133 && cr < 173) {
        skin++;
        sx += p % FW;
      }
    }
    const n = FW * FH;
    const motion = cam.prevLum ? diff / n : 0;
    cam.prevLum = lum;
    const signals = [];
    if (bright / n < 18) return { raw: 20, signals: ["caméra masquée / trop sombre"] };
    if (skin / n < 0.03) return { raw: 15, signals: ["visage non détecté"] };
    let pen = 0;
    const off = Math.abs(sx / skin / FW - 0.5) * 2;
    if (off > 0.45) { pen += 30; signals.push("tête tournée / hors cadre"); }
    if (motion > 22) { pen += 25; signals.push("forte agitation"); }
    else if (motion > 12) { pen += 10; signals.push("agitation"); }
    return { raw: clamp(100 - pen, 5, 100), signals };
  }

  async function analyzeFaceDetector(vid) {
    const faces = await cam.detector.detect(vid);
    if (!faces.length) return { raw: 10, signals: ["visage absent"] };
    const b = faces[0].boundingBox;
    const off = Math.abs((b.x + b.width / 2) / vid.videoWidth - 0.5) * 2;
    const area = (b.width * b.height) / (vid.videoWidth * vid.videoHeight);
    let pen = 0;
    const signals = [];
    if (off > 0.55) { pen += 35; signals.push("tête tournée / hors cadre"); }
    if (area < 0.04) { pen += 15; signals.push("trop loin de l'écran"); }
    return { raw: clamp(100 - pen, 5, 100), signals };
  }

  async function camTick() {
    const vid = $("ns-cam-video");
    if (!cam.on || cam.busy || !vid || vid.readyState < 2) return;
    cam.busy = true;
    try {
      let res = null;
      if (cam.detector) {
        try { res = await analyzeFaceDetector(vid); } catch (_e) { cam.detector = null; }
      }
      res ||= analyzeHeuristic(vid);
      cam.ema = cam.ema == null ? res.raw : 0.7 * cam.ema + 0.3 * res.raw; // lissage anti-bruit
      cam.signals = res.signals;
      curveSample();
      const st = $("ns-cam-status");
      if (st) st.textContent = `Caméra locale — attention ≈ ${Math.round(cam.ema)} %${res.signals.length ? " · " + res.signals.join(", ") : ""}`;
      renderScore();
    } finally {
      cam.busy = false;
    }
  }

  async function toggleCamera() {
    const box = $("ns-cam-box");
    const vid = $("ns-cam-video");
    const st = $("ns-cam-status");
    const btn = $("ns-cam-btn");
    if (cam.on) {
      if (cam.stream) cam.stream.getTracks().forEach((t) => t.stop());
      cam.stream = null;
      vid.srcObject = null;
      Object.assign(cam, { on: false, ema: null, prevLum: null, signals: [], lowSince: 0 });
      box.style.display = "none";
      btn.textContent = "Caméra";
      renderScore();
      drawCurve();
      return;
    }
    box.style.display = "block";
    st.textContent = "Ouverture de la caméra…";
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("getUserMedia indisponible");
      cam.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 320 }, height: { ideal: 180 }, facingMode: "user" },
        audio: false,
      });
      vid.srcObject = cam.stream;
      await vid.play();
      cam.on = true;
      try { cam.detector = typeof FaceDetector === "function" ? new FaceDetector({ fastMode: true, maxDetectedFaces: 1 }) : null; }
      catch (_e) { cam.detector = null; }
      btn.textContent = "Stop Cam";
      st.textContent = "Caméra active — analyse locale en cours…";
      curve.brk = true; // la courbe ne relie pas l'ancienne session à la nouvelle
      drawCurve();
    } catch (err) {
      cam.on = false;
      st.textContent = "Caméra refusée ou indisponible. Autorisez-la dans la barre d'adresse (icône caméra) puis réessayez.";
      btn.textContent = "Caméra";
      console.warn("Neuro-Study caméra :", err);
    }
  }

  // ------------------------------------------------------------------ sous-titres
  function extractLiveCaption() {
    if (isYouTube) {
      return Array.from(document.querySelectorAll(".ytp-caption-segment")).map((s) => s.textContent.trim()).filter(Boolean).join(" ").trim();
    }
    return ""; // Meet : voir pollMeet() (lecture par intervenant via meet_captions.js)
  }

  function pushCaption(raw) {
    const now = Date.now();
    const last = buffer[buffer.length - 1];
    if (last && (raw.includes(last.text) || last.text.includes(raw))) {
      if (raw.length >= last.text.length) { last.text = raw; last.wall = now; } // sous-titre qui s'allonge
    } else {
      buffer.push({ t: videoTime(), text: raw, wall: now });
    }
    buffer = buffer.filter((c) => now - c.wall < 180000).slice(-40);
  }

  let subPending = "";
  let subSince = 0;
  let subLastSent = 0;
  let subBusy = false;

  // ---- Meet : sous-titres lus uniquement dans la zone « Sous-titres », découpés par intervenant
  let meetActive = null; // null = inconnu, false = sous-titres Meet éteints, true = lus
  let meetAutoTried = false;
  const meetSince = Date.now();

  function renderMeetStatus() {
    const el = $("ns-meet-status");
    if (!el) return;
    if (!isMeet || meetActive === null) { el.hidden = true; return; }
    el.hidden = false;
    if (meetActive === false) {
      el.className = "ns-hint ns-meet-status ns-meet-off";
      el.replaceChildren(
        "Les sous-titres de Meet sont désactivés : je n'entends pas les paroles. ",
        h("button", { class: "ns-link", type: "button", onclick: () => {
          const b = window.NSMeet && NSMeet.findCaptionsButton(document);
          if (b) b.click();
          else el.textContent = "Bouton introuvable : clique sur l'icône CC de Meet (ou appuie sur « c »).";
        } }, "Activer les sous-titres"));
    } else {
      el.className = "ns-hint ns-meet-status ns-meet-on";
      el.textContent = `✓ Sous-titres Meet lus · ${buffer.length} phrase(s) captée(s)`;
    }
  }

  async function pollMeet() {
    if (!window.NSMeet) return;
    const { active, blocks } = NSMeet.readMeetCaptions(document);
    if (active !== meetActive) { meetActive = active; renderMeetStatus(); }
    if (!active) {
      if (!meetAutoTried && Date.now() - meetSince > 6000) { // une seule tentative automatique (jamais si déjà actifs)
        meetAutoTried = true;
        const b = NSMeet.findCaptionsButton(document);
        if (b) b.click();
      }
      return maybeTranslate();
    }
    if (blocks.length) {
      const now = Date.now();
      if (NSMeet.mergeBlocks(buffer, blocks, now, null)) {
        buffer = buffer.filter((c) => now - c.wall < 180000);
        renderMeetStatus();
      }
      const last = blocks[blocks.length - 1].text;
      if (last !== lastCaption) {
        lastCaption = last;
        subPending = last;
        subSince = now;
        renderCaptionRaw(last);
      }
    }
    await maybeTranslate();
  }

  async function pollCaptions() {
    if (isMeet) return pollMeet();
    const raw = extractLiveCaption();
    if (!raw || raw.length < 3 || raw === lastCaption) {
      await maybeTranslate();
      return;
    }
    lastCaption = raw;
    pushCaption(raw);
    subPending = raw;
    subSince = Date.now();
    renderCaptionRaw(raw);
    await maybeTranslate();
  }

  // ------------------------------------------------------------------ sous-titres TRADUITS (surimpression)
  // Le sous-titre s'affiche dans la langue choisie (fr / en / ar) SUR la vidéo, le texte d'origine en petit dessous.
  //  • YouTube : on récupère la transcription complète via le serveur, on la traduit par lots à l'avance et on la
  //    synchronise avec la vidéo → aucune attente, et pas besoin d'activer les sous-titres (CC) de YouTube.
  //  • Meet / vidéo sans transcription : on traduit les sous-titres en direct (CC à activer), au plus 1 requête / 3 s.
  const trKey = (lang, text) => `${lang}|${text}`;
  const trCache = new Map();
  let ytSegs = null; // [{start, text}] de la vidéo YouTube en cours
  let ytSegsFor = "";
  let ytTries = 0;
  let ytLoadAt = 0;
  let ytIdx = -1;
  let trBusy = false;
  let trRetryAt = 0;
  let trFallback = false;

  function ensureOverlay() {
    const host = (isYouTube && document.getElementById("movie_player")) || document.body;
    let el = $("ns-sub-overlay");
    if (!el) {
      el = h("div", { id: "ns-sub-overlay", class: isYouTube ? "ns-sub-yt" : "ns-sub-meet" },
        h("div", { id: "ns-sub-main", class: "ns-sub-main" }), h("div", { id: "ns-sub-orig", class: "ns-sub-orig" }));
    }
    if (el.parentElement !== host) host.appendChild(el);
    return el;
  }

  function showSubtitle(main, orig) {
    const ov = ensureOverlay();
    const on = prefs.subs && Boolean(main);
    ov.style.display = on ? "" : "none";
    document.documentElement.classList.toggle("ns-hide-native-cc", prefs.subs && Boolean(ytSegs));
    if (!on) return;
    const m = $("ns-sub-main");
    const o = $("ns-sub-orig");
    m.textContent = main;
    m.dir = prefs.lang === "ar" ? "rtl" : "ltr";
    const note = trFallback ? " · traduction de secours" : "";
    o.textContent = orig && orig !== main ? orig + note : (note ? note.slice(3) : "");
    o.dir = /[؀-ۿ]/.test(orig || "") ? "rtl" : "ltr";
    const box = $("ns-subtitle");
    if (box) { box.textContent = main; box.dir = m.dir; }
  }

  async function translateTexts(texts) {
    const lang = prefs.lang;
    const todo = [...new Set(texts)].filter((x) => x && !trCache.has(trKey(lang, x)));
    for (let i = 0; i < todo.length; i += 10) {
      const part = todo.slice(i, i + 10);
      const res = await callBackend("/api/translate_batch", "POST", { texts: part, target: lang, profile: prefs.profile }, 45000);
      if (!res || !Array.isArray(res.translations)) { trRetryAt = Date.now() + 5000; return false; }
      part.forEach((x, j) => { if (res.translations[j]) trCache.set(trKey(lang, x), res.translations[j]); });
      trFallback = Boolean(res.fallback);
    }
    return true;
  }

  async function prefetchAhead() { // traduit les ~30 prochaines phrases de la vidéo
    if (!ytSegs || trBusy || !connected || Date.now() < trRetryAt) return;
    trBusy = true;
    try {
      const from = Math.max(ytIdx, 0);
      await translateTexts(ytSegs.slice(from, from + 30).map((g) => g.text));
    } finally {
      trBusy = false;
    }
  }

  async function loadTranscript(info) {
    if (!isYouTube || !connected || !info.video_id) return;
    const retry = ytSegsFor === info.video_id && !ytSegs && ytTries < 3 && Date.now() - ytLoadAt > 20000;
    if (ytSegsFor === info.video_id && !retry) return;
    ytSegsFor = info.video_id;
    ytTries = retry ? ytTries + 1 : 1;
    ytLoadAt = Date.now();
    const res = await callBackend("/api/youtube/transcript", "POST", { url: info.url }, 40000);
    if (ytSegsFor !== info.video_id) return; // on a changé de vidéo entre-temps
    if (res && Array.isArray(res.segments) && res.segments.length) {
      ytSegs = res.segments;
      prefetchAhead();
    }
  }

  function syncSubs() { // appelée toutes les 0,4 s : affiche la phrase de la vidéo à l'instant courant
    if (!ytSegs) return;
    if (!prefs.subs) return showSubtitle("", "");
    const v = document.querySelector("video.html5-main-video") || document.querySelector("video");
    if (!v) return;
    const t = v.currentTime;
    let lo = 0, hi = ytSegs.length - 1, k = -1; // dernier segment dont le début <= t
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (ytSegs[mid].start <= t) { k = mid; lo = mid + 1; } else hi = mid - 1;
    }
    if (k < 0) return showSubtitle("", "");
    ytIdx = k;
    const seg = ytSegs[k];
    const next = ytSegs[k + 1];
    const end = next ? Math.min(next.start, seg.start + 8) : seg.start + 8;
    if (t > end) return showSubtitle("", "");
    const tr = trCache.get(trKey(prefs.lang, seg.text));
    showSubtitle(tr || seg.text, tr ? seg.text : "");
    if (!tr) prefetchAhead();
  }

  function renderCaptionRaw(raw) { // sous-titre en direct : on montre l'original tout de suite, la traduction le remplace
    if (ytSegs || !prefs.subs) return;
    const cached = trCache.get(trKey(prefs.lang, raw));
    showSubtitle(cached || raw, cached ? raw : "");
  }

  // Traduit seulement si le texte est stable depuis 1 s et au plus toutes les 3 s (quota IA gratuit !)
  async function maybeTranslate() {
    const now = Date.now();
    if (ytSegs || !prefs.subs || !connected || subBusy || !subPending) return;
    if (now - subSince < 1000 || now - subLastSent < 3000) return;
    const text = subPending;
    subPending = "";
    subLastSent = now;
    subBusy = true;
    try {
      const res = await callBackend("/api/subtitle", "POST", { text, source: "auto", target: prefs.lang, profile: prefs.profile });
      if (!res) return;
      const trans = res.translation || res.subtitle || text;
      trFallback = Boolean(res.fallback);
      trCache.set(trKey(prefs.lang, text), trans);
      showSubtitle(trans, text);
    } finally {
      subBusy = false;
    }
  }

  // ------------------------------------------------------------------ « Je suis perdu »
  function buildPayload(extra = {}) {
    const info = sourceInfo();
    const caps = buffer.slice(-30).map((c) => ({ t: c.t, text: c.text, speaker: c.speaker || "" }));
    return {
      captions: caps,
      context: caps.map((c) => (c.speaker ? c.speaker + " : " : "") + c.text).join("\n"),
      current_time: videoTime(),
      video_id: info.video_id,
      source_title: info.title,
      platform: info.platform,
      url: info.url,
      target: prefs.lang,
      profile: prefs.profile,
      ...extra,
    };
  }

  async function askLost({ entry = null } = {}) {
    if (loading) return;
    clearNudge();
    lostTimes.push(Date.now());
    renderScore();
    setTab("help");

    // Pause seulement sur YouTube. Dans Meet la séance continue (et la 1re <video> est la tuile d'un participant !).
    const v = isYouTube ? video() : null;
    if (prefs.pause && v && !v.paused) { v.pause(); pausedByUs = true; }

    let payload;
    if (entry) {
      const base = payloads.get(entry.id) || {
        current_time: entry.video_time, video_id: entry.source.video_id, source_title: entry.source.title,
        platform: entry.source.platform, url: entry.source.url, captions: [], context: "", target: prefs.lang, profile: prefs.profile,
      };
      payload = { ...base, target: prefs.lang, profile: prefs.profile, previous: entry.result.paragraph, replace_id: entry.id };
    } else {
      const fi = $("ns-focus-input");
      const focus = fi ? fi.value.trim().slice(0, 120) : "";
      payload = buildPayload(focus ? { focus } : {});
      if (fi) fi.value = "";
    }
    if (isMeet) payload.live = true;

    loading = true;
    renderHelp();
    const t0 = Date.now();
    const data = await callBackend("/api/lost", "POST", payload, 120000);
    loading = false;

    if (data && data.needs_input) {
      current = { error: data.error };
      renderHelp();
      return;
    }
    if (!data) {
      current = { error: connected ? "Le serveur a mis trop de temps à répondre ou a renvoyé une erreur." : "Serveur Flask injoignable. Lancez `python app.py` (http://127.0.0.1:5000) puis réessayez." };
      renderHelp();
      return;
    }
    const newEntry = {
      id: data.id,
      created_at: data.created_at,
      source: { platform: payload.platform, title: payload.source_title, url: payload.url, video_id: payload.video_id },
      video_time: data.video_time ?? payload.current_time ?? null,
      target: payload.target,
      understood: false,
      result: data,
      ms: Date.now() - t0,
    };
    payloads.set(newEntry.id, { ...payload, previous: undefined, replace_id: undefined });
    current = newEntry;
    renderHelp();
    refreshHistory();
  }

  // ------------------------------------------------------------------ rendu d'une explication
  function section(title, ...content) {
    return h("div", { class: "ns-sec" }, h("div", { class: "ns-sec-title" }, title), ...content);
  }

  function renderResultCard(entry, { compact = false } = {}) {
    const r = entry.result;
    const dir = entry.target === "ar" ? "rtl" : "ltr";
    const kids = [];

    kids.push(h("div", { class: "ns-concept-tag" }, r.point || r.concept || "Point non compris"));
    const meta = [];
    if (typeof entry.video_time === "number") {
      meta.push(h("button", { class: "ns-chip", title: "Revenir à ce moment", onclick: () => seekTo(entry.source, entry.video_time) }, `⏱ ${fmtTime(entry.video_time)}`));
    }
    meta.push(h("span", { class: "ns-chip ns-chip-plain" }, r.fallback ? "IA indisponible" : `IA : ${r.provider || "?"}`));
    kids.push(h("div", { class: "ns-meta" }, meta));

    if (r.fallback) {
      kids.push(h("div", { class: "ns-warn" }, "L'explication détaillée n'a pas pu être générée.", r.error ? h("div", { class: "ns-warn-detail" }, r.error) : null));
    }
    if (r.quote) kids.push(h("blockquote", { class: "ns-quote", dir }, `« ${r.quote} »`));
    if (r.why_hard) kids.push(h("div", { class: "ns-why", dir }, `💡 ${r.why_hard}`));
    if (r.prerequisites && r.prerequisites.length) kids.push(h("div", { class: "ns-prereq", dir }, "À connaître avant : " + r.prerequisites.join(" · ")));

    if (r.paragraph) kids.push(section("Explication simple", h("div", { class: "ns-simple-text", dir }, r.paragraph)));
    if (r.analogy) kids.push(section("Analogie", h("div", { class: "ns-simple-text", dir }, r.analogy)));
    if (r.example) kids.push(section("Exemple", h("div", { class: "ns-simple-text", dir }, r.example)));
    if (r.steps && r.steps.length) kids.push(section("Étapes", h("ol", { class: "ns-steps", dir }, r.steps.map((s) => h("li", {}, s)))));
    if (r.formula) kids.push(section("À retenir", h("code", { class: "ns-formula" }, r.formula)));

    const svg = r.visual_svg ? safeSvg(r.visual_svg) : null;
    if (svg) kids.push(section(r.visual_type === "curve" ? "Courbe" : "Schéma", h("div", { class: "ns-visual-box" }, svg)));
    if (r.image) {
      kids.push(section("Image", h("img", { class: "ns-img", src: r.image, alt: r.image_caption || "", onerror: (e) => e.target.parentElement.remove() }), r.image_caption ? h("div", { class: "ns-cap" }, r.image_caption) : null));
    }
    if (r.check && r.check.question) {
      const ans = h("div", { class: "ns-answer", hidden: true }, r.check.answer || "");
      kids.push(section("Vérifie que tu as compris",
        h("div", { class: "ns-simple-text", dir }, r.check.question),
        h("button", { class: "ns-link", onclick: (e) => { ans.hidden = !ans.hidden; e.target.textContent = ans.hidden ? "Voir la réponse" : "Masquer la réponse"; } }, "Voir la réponse"),
        ans));
    }

    if (!compact) {
      const v = video();
      kids.push(h("div", { class: "ns-actions" },
        h("button", { class: "ns-btn ns-ok", onclick: () => markUnderstood(entry, true) }, entry.understood ? "✓ Compris" : "✓ J'ai compris"),
        h("button", { class: "ns-btn", onclick: () => askLost({ entry }) }, "↻ Expliquer autrement"),
        v ? h("button", { class: "ns-btn", onclick: () => { v.play().catch(() => {}); pausedByUs = false; } }, "▶ Reprendre") : null));
    }
    return h("div", { class: "ns-result" }, kids);
  }

  function renderHelp() {
    const pane = $("ns-tab-help");
    if (!pane) return;
    pane.replaceChildren();
    if (loading) {
      const t = videoTime();
      pane.append(h("div", { class: "ns-loading" },
        h("div", { class: "ns-spinner" }),
        h("div", {}, `Analyse de ce qui vient d'être dit${typeof t === "number" ? " (vers " + fmtTime(t) + ")" : ""}…`),
        h("div", { class: "ns-cap" }, "Repérage du point difficile, puis texte, schéma et exemple.")));
      return;
    }
    if (!current) {
      pane.append(h("div", { class: "ns-empty" }, isMeet
        ? "Réunion en direct : je lis les sous-titres de Meet (ils doivent être activés) et je garde les dernières phrases de chaque intervenant. Appuie sur « Je suis perdu » : j'explique ce qui vient d'être dit, avec un exemple."
        : "Quand tu décroches, appuie sur « Je suis perdu » : je repère le point de la vidéo que tu n'as pas compris et je te l'explique (texte, schéma, courbe, image)."));
      return;
    }
    if (current.error) {
      pane.append(h("div", { class: "ns-warn" }, current.error));
      return;
    }
    pane.append(renderResultCard(current));
  }

  // ------------------------------------------------------------------ historique
  async function refreshHistory() {
    let items = null;
    const res = await callBackend("/api/history", "GET");
    if (res && Array.isArray(res.items)) {
      items = res.items;
      store.set({ ns_history: items.slice(0, 60) }); // copie locale, lisible même si Flask est éteint
    } else {
      items = ((await store.get("ns_history")).ns_history) || [];
    }
    historyItems = items;
    renderHistory();
  }

  async function markUnderstood(entry, value) {
    entry.understood = value;
    await callBackend(`/api/history/${entry.id}/understood`, "POST", { understood: value });
    renderHelp();
    refreshHistory();
  }

  async function deleteEntry(id) {
    await callBackend(`/api/history/${id}`, "DELETE");
    if (current && current.id === id) current = null;
    refreshHistory();
    renderHelp();
  }

  function entriesInScope() {
    if (historyScope === "all") return historyItems;
    const vid = videoId();
    return historyItems.filter((e) => (vid ? e.source && e.source.video_id === vid : e.source && e.source.url === location.href));
  }

  function toMarkdown(items) {
    const L = ["# Points non compris — Neuro-Study", ""];
    for (const e of items) {
      const r = e.result;
      L.push(`## ${r.point}`);
      L.push(`*${(e.created_at || "").slice(0, 16).replace("T", " ")} · ${e.source.title || ""}${typeof e.video_time === "number" ? " · à " + fmtTime(e.video_time) : ""}${e.understood ? " · ✓ compris" : ""}*`);
      if (e.source.video_id || e.source.url) L.push(`[Ouvrir la vidéo](${watchUrl(e.source, e.video_time)})`);
      L.push("");
      if (r.quote) L.push(`> « ${r.quote} »`, "");
      if (r.paragraph) L.push(r.paragraph, "");
      if (r.analogy) L.push(`**Analogie :** ${r.analogy}`, "");
      if (r.example) L.push(`**Exemple :** ${r.example}`, "");
      if (r.steps && r.steps.length) L.push(...r.steps.map((s, i) => `${i + 1}. ${s}`), "");
      if (r.formula) L.push(`**À retenir :** \`${r.formula}\``, "");
      if (r.check && r.check.question) L.push(`**Question :** ${r.check.question} — *${r.check.answer}*`, "");
      L.push("---", "");
    }
    return L.join("\n");
  }

  function exportMarkdown() {
    const items = entriesInScope();
    if (!items.length) return;
    const url = URL.createObjectURL(new Blob([toMarkdown(items)], { type: "text/markdown;charset=utf-8" }));
    const a = h("a", { href: url, download: `neuro-study-historique-${new Date().toISOString().slice(0, 10)}.md` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function renderHistory() {
    const cnt = $("ns-hist-count");
    if (cnt) cnt.textContent = String(historyItems.length);
    const pane = $("ns-tab-history");
    if (!pane) return;
    const items = entriesInScope();
    pane.replaceChildren();

    const scope = h("select", { class: "ns-select-mini", title: "Filtre" },
      h("option", { value: "all" }, "Toutes les vidéos"), h("option", { value: "video" }, "Cette vidéo"));
    scope.value = historyScope;
    scope.addEventListener("change", () => { historyScope = scope.value; renderHistory(); });
    pane.append(h("div", { class: "ns-hist-bar" }, scope,
      h("button", { class: "ns-btn", onclick: exportMarkdown, disabled: !items.length }, "⬇ Exporter"),
      h("a", { class: "ns-btn", href: `${WEB_BASE}/history`, target: "_blank", rel: "noopener" }, "Page complète")));

    if (!items.length) {
      pane.append(h("div", { class: "ns-empty" }, "Aucun point enregistré pour l'instant."));
      return;
    }
    for (const e of items) {
      const body = h("div", { class: "ns-hist-body", hidden: true });
      const head = h("button", { class: "ns-hist-head", onclick: () => {
        body.hidden = !body.hidden;
        if (!body.hidden && !body.firstChild) {
          body.append(renderResultCard(e, { compact: true }),
            h("div", { class: "ns-actions" },
              h("button", { class: "ns-btn", onclick: () => seekTo(e.source, e.video_time) }, "⏱ Aller à ce moment"),
              h("button", { class: "ns-btn ns-ok", onclick: () => markUnderstood(e, !e.understood) }, e.understood ? "↩ À revoir" : "✓ Compris"),
              h("button", { class: "ns-btn ns-danger", onclick: () => deleteEntry(e.id) }, "Supprimer")));
        }
      } },
        h("span", { class: "ns-hist-dot" + (e.understood ? " ns-done" : "") }),
        h("span", { class: "ns-hist-title" }, e.result.point),
        h("span", { class: "ns-hist-sub" }, `${typeof e.video_time === "number" ? fmtTime(e.video_time) + " · " : ""}${(e.source.title || "").slice(0, 28)}`));
      pane.append(h("div", { class: "ns-hist-item" }, head, body));
    }
    pane.append(h("button", { class: "ns-link ns-danger-link", onclick: async () => {
      if (confirm("Effacer tout l'historique ?")) { await callBackend("/api/history/clear", "POST", {}); current = null; refreshHistory(); renderHelp(); }
    } }, "Tout effacer"));
  }

  function setTab(name) {
    tab = name;
    document.querySelectorAll("#neuro-study-sidebar .ns-tab").forEach((b) => b.classList.toggle("ns-active", b.dataset.tab === name));
    $("ns-tab-help").hidden = name !== "help";
    $("ns-tab-history").hidden = name !== "history";
    if (name === "history") refreshHistory();
  }

  // ------------------------------------------------------------------ interface
  function ensureSidebar() {
    if ($("neuro-study-sidebar")) return;
    const sidebar = h("div", { id: "neuro-study-sidebar" });
    sidebar.innerHTML = `
      <div class="ns-header">
        <span class="ns-title">Neuro-Study</span>
        <span id="ns-conn-badge" class="ns-conn-pill ns-off">Flask éteint</span>
        <button id="ns-min" class="ns-icon-btn" title="Réduire / agrandir">–</button>
      </div>
      <div id="ns-body">
        <div class="ns-subbar">
          <span id="ns-source-label" class="ns-source">Source : --</span>
          <span id="ns-focus-badge" class="ns-focus-pill">Compréhension : --</span>
        </div>
        <button id="ns-lost-btn" class="ns-lost-btn">Je suis perdu</button>
        <input id="ns-focus-input" class="ns-focus-input" type="text" maxlength="120" autocomplete="off"
               placeholder="Sur quoi es-tu perdu(e) ? (facultatif, ex. : écart-type)">
        <div id="ns-hint" class="ns-hint" hidden></div>
        <div id="ns-meet-status" class="ns-hint ns-meet-status" hidden></div>
        <div id="ns-curve-box" class="ns-curve-box" hidden>
          <div class="ns-curve-head"><span>Concentration (caméra)</span><b id="ns-curve-now"></b></div>
          <canvas id="ns-curve" class="ns-curve"></canvas>
          <div id="ns-curve-cap" class="ns-cap">Points rouges = concentration sous 50 %.</div>
          <div id="ns-curve-low" class="ns-low"></div>
        </div>
        <div class="ns-tabs">
          <button class="ns-tab ns-active" data-tab="help">Aide</button>
          <button class="ns-tab" data-tab="history">Historique <span id="ns-hist-count" class="ns-count">0</span></button>
        </div>
        <div id="ns-tab-help" class="ns-pane"></div>
        <div id="ns-tab-history" class="ns-pane" hidden></div>
        <details class="ns-settings">
          <summary>Réglages, caméra et sous-titres</summary>
          <div class="ns-controls">
            <select id="ns-lang" title="Langue des explications et sous-titres">
              <option value="fr">Français</option><option value="ar">العربية / Derja</option><option value="en">English</option>
            </select>
            <select id="ns-profile" title="Profil d'apprentissage">
              <option value="standard">Standard</option><option value="tdah">TDAH</option><option value="dyslexie">Dyslexie</option>
              <option value="dyscalculie">Dyscalculie</option><option value="autisme">Autisme</option>
            </select>
            <button id="ns-cam-btn" type="button" class="ns-cam-btn">Caméra</button>
          </div>
          <div id="ns-cam-box" class="ns-cam-box" style="display:none">
            <video id="ns-cam-video" autoplay playsinline muted></video>
            <div id="ns-cam-status" class="ns-cap">Caméra prête</div>
          </div>
          <label class="ns-check"><input type="checkbox" id="ns-pause"> Mettre la vidéo en pause quand je suis perdu</label>
          <label class="ns-check"><input type="checkbox" id="ns-subs"> Afficher les sous-titres traduits sur la vidéo</label>
          <div class="ns-box">
            <div class="ns-label">Sous-titre dans la langue choisie :</div>
            <div id="ns-subtitle" class="ns-subtitle">YouTube : les sous-titres traduits s'affichent sur la vidéo. Meet : activez les sous-titres (CC) de la réunion.</div>
          </div>
        </details>
      </div>`;
    document.body.appendChild(sidebar);

    $("ns-lang").addEventListener("change", (e) => { prefs.lang = e.target.value; savePrefs(); lastCaption = ""; trFallback = false; trRetryAt = 0; syncSubs(); prefetchAhead(); });
    $("ns-profile").addEventListener("change", (e) => { prefs.profile = e.target.value; savePrefs(); lastCaption = ""; });
    $("ns-pause").addEventListener("change", (e) => { prefs.pause = e.target.checked; savePrefs(); });
    $("ns-subs").addEventListener("change", (e) => { prefs.subs = e.target.checked; savePrefs(); if (!prefs.subs) showSubtitle("", ""); else syncSubs(); });
    $("ns-cam-btn").addEventListener("click", toggleCamera);
    $("ns-curve").addEventListener("mousemove", curveHover);
    $("ns-lost-btn").addEventListener("click", () => askLost());
    $("ns-focus-input").addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") askLost(); });
    $("ns-focus-input").addEventListener("keyup", (e) => e.stopPropagation());
    $("ns-focus-input").addEventListener("keypress", (e) => e.stopPropagation());
    $("ns-min").addEventListener("click", () => { prefs.collapsed = !prefs.collapsed; savePrefs(); applyCollapsed(); });
    sidebar.querySelectorAll(".ns-tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
    applyPrefsToUi();
    renderHelp();
    renderHistory();
    renderScore();
    renderMeetStatus();
  }

  function applyCollapsed() {
    $("ns-body").style.display = prefs.collapsed ? "none" : "";
    $("ns-min").textContent = prefs.collapsed ? "+" : "–";
  }

  function applyPrefsToUi() {
    $("ns-lang").value = prefs.lang;
    $("ns-profile").value = prefs.profile;
    $("ns-pause").checked = prefs.pause;
    $("ns-subs").checked = prefs.subs;
    applyCollapsed();
  }

  const savePrefs = () => store.set({ ns_prefs: { ...prefs } });

  // ------------------------------------------------------------------ boucles
  function renderConnection() {
    const badge = $("ns-conn-badge");
    if (!badge) return;
    let text = connected ? "Connecté" : "Flask éteint";
    let cls = connected ? "ns-on" : "ns-off";
    if (connected && providers && !providers.length) { text = "Connecté · aucune clé IA"; cls = "ns-warn-pill"; }
    else if (connected && providers && providers.length) text = `Connecté · IA ${providers.filter((p) => p !== "ollama")[0] || providers[0]}`;
    badge.textContent = text;
    badge.className = `ns-conn-pill ${cls}`;
    badge.title = connected ? "" : "Lancez le serveur : python app.py";
  }

  async function syncBackend() {
    if (!alive()) return stopAll();
    ensureSidebar();
    const info = sourceInfo();
    const key = info.video_id || info.title;
    if (key !== currentKey) { // nouvelle vidéo : on repart d'un contexte propre
      currentKey = key;
      buffer = [];
      lastCaption = "";
      subPending = "";
      meetAutoTried = false;
      ytSegs = null; ytSegsFor = ""; ytIdx = -1; ytTries = 0;
      showSubtitle("", "");
      curveReset();
    }
    const src = $("ns-source-label");
    if (src) src.textContent = `${info.platform.toUpperCase()} : ${info.title.slice(0, 34)}`;

    const hb = await callBackend("/api/extension/heartbeat", "POST", {
      platform: info.platform, title: info.title, url: info.url, last_caption: lastCaption,
      profile: prefs.profile, target: prefs.lang, camera_active: cam.on,
      attention_score: cam.on && cam.ema != null ? Math.round(cam.ema) : null,
    });
    const was = connected;
    connected = Boolean(hb && hb.ok);
    if (connected !== was || providers === null) {
      const p = await pingBackend();
      providers = p.connected ? p.providers || [] : null;
      if (connected && !was) refreshHistory();
    }
    renderConnection();
    renderScore();
    loadTranscript(info);
  }

  function stopAll() {
    timers.forEach(clearInterval);
    if (cam.stream) cam.stream.getTracks().forEach((t) => t.stop());
    const sb = $("neuro-study-sidebar");
    if (sb) sb.remove();
    const ov = $("ns-sub-overlay");
    if (ov) ov.remove();
    document.documentElement.classList.remove("ns-hide-native-cc");
  }

  function trackRewinds() {
    document.addEventListener("timeupdate", (e) => {
      if (e.target && e.target.tagName === "VIDEO" && !e.target.seeking) lastT = e.target.currentTime;
    }, true);
    document.addEventListener("seeking", (e) => {
      if (!e.target || e.target.tagName !== "VIDEO") return;
      if (lastT != null && e.target.currentTime < lastT - 3) { rewindTimes.push(Date.now()); renderScore(); }
    }, true);
  }

  async function init() {
    const saved = (await store.get("ns_prefs")).ns_prefs;
    if (saved) Object.assign(prefs, saved);
    ensureSidebar();
    trackRewinds();
    refreshHistory();
    syncBackend();
    timers.push(setInterval(syncBackend, 5000));
    timers.push(setInterval(pollCaptions, 1500));
    timers.push(setInterval(syncSubs, 400));
    timers.push(setInterval(prefetchAhead, 4000));
    timers.push(setInterval(camTick, 1000));
    timers.push(setInterval(renderScore, 3000));
    window.addEventListener("yt-navigate-finish", () => setTimeout(syncBackend, 500));
  }

  init();
})();
