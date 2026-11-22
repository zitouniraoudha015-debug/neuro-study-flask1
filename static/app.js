(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ACCOUNTS_KEY = "ns-accounts";
  const SESSION_KEY = "ns-session";
  const COURSE_HISTORY_KEY = "ns-course-history";
  const PROFILE_KEY = "ns-profile";
  const STYLE_KEY = "ns-style";
  const ILLUSTRATION_KEY = "ns-illustrations";

  const S = {
    profile: "standard",
    style: "visuel",
    cfg: {},
    styles: {},
    account: null,
    guest: false,
    sections: [],
    lessons: {},
    chunkIndex: 0,
    micOn: false,
    camOn: false,
    rec: null,
    yt: null,
    demoSteps: [],
    demoIndex: 0,
    demoTimer: null,
    chart: null,
    buf: [],
    audio: { utterance: null, state: "stopped", volume: 0.85, segments: [], segmentIndex: 0 },
  };

  const profileMeta = {
    standard: { icon: "S", label: "Apprentissage équilibré" },
    tdah: { icon: "T", label: "Concentration guidée" },
    dyslexie: { icon: "D", label: "Lecture confortable" },
    dyscalculie: { icon: "N", label: "Nombres simplifiés" },
    autisme: { icon: "A", label: "Étapes prévisibles" },
  };

  let toastTimer;
  function toast(message) {
    const box = $("#toast");
    box.textContent = message;
    box.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("show"), 3600);
  }

  async function api(url, body = null, method = "POST") {
    const options = { method, headers: {} };
    if (body) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    try {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Une erreur est survenue.");
      return data;
    } catch (error) {
      throw error;
    }
  }

  function readJson(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; }
  }
  function writeJson(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  }

  function toBase64(bytes) {
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    return btoa(binary);
  }
  function fromBase64(value) {
    const binary = atob(value);
    return Uint8Array.from(binary, (c) => c.charCodeAt(0));
  }
  async function derivePassword(password, saltBase64) {
    const salt = saltBase64 ? fromBase64(saltBase64) : crypto.getRandomValues(new Uint8Array(16));
    const keyMaterial = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(password),
      "PBKDF2",
      false,
      ["deriveBits"]
    );
    const bits = await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt, iterations: 100000, hash: "SHA-256" },
      keyMaterial,
      256
    );
    return { hash: toBase64(new Uint8Array(bits)), salt: toBase64(salt) };
  }

  function getAccounts() { return readJson(ACCOUNTS_KEY, []); }
  function saveAccounts(accounts) { writeJson(ACCOUNTS_KEY, accounts); }

  function setAuthMode(login) {
    $("#signup-form").hidden = login;
    $("#login-form").hidden = !login;
    $("#auth-mode-label").textContent = login ? "Pas encore de compte ?" : "Vous avez déjà un compte ?";
    $("#auth-switch").textContent = login ? "Créer un compte" : "Se connecter";
  }
  $("#auth-switch").addEventListener("click", () => setAuthMode($("#login-form").hidden));

  function profileCard(profileId, selectedProfile) {
    const p = S.cfg[profileId];
    const meta = profileMeta[profileId] || profileMeta.standard;
    if (!p) return "";
    return `<button type="button" class="profile-card ${profileId === selectedProfile ? "selected" : ""}" data-profile="${profileId}" role="radio" aria-checked="${profileId === selectedProfile}">
      <span class="profile-symbol">${meta.icon}</span><span class="check">✓</span>
      <strong>${esc(p.label)}</strong><small>${esc(p.description || p.diff.help)}</small>
    </button>`;
  }

  function renderProfileCards(container, selectedProfile) {
    const target = $(container);
    if (!target) return;
    target.innerHTML = ["standard", "tdah", "dyslexie", "dyscalculie", "autisme"].map((id) => profileCard(id, selectedProfile)).join("");
  }

  function styleCard(id, selectedStyle) {
    const s = S.styles[id];
    if (!s) return "";
    return `<button type="button" class="style-card ${id === selectedStyle ? "selected" : ""}" data-style="${id}" role="radio" aria-checked="${id === selectedStyle}">
      <strong>${esc(s.label)}</strong><small>${esc(s.desc)}</small>
    </button>`;
  }
  function renderStyleCards(selectedStyle) {
    $("#settings-style-cards").innerHTML = ["visuel", "auditif", "lecture", "pratique"].map((id) => styleCard(id, selectedStyle)).join("");
  }

  async function loadConfig() {
    try {
      const data = await api("/api/profiles", null, "GET");
      S.cfg = data.profiles;
      S.styles = data.styles;
    } catch {
      S.cfg = {};
      S.styles = {};
    }
  }

  $("#signup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = $("#signup-username").value.trim();
    const password = $("#signup-password").value;
    const confirm = $("#signup-confirm").value;
    const profile = $("#profile-cards .profile-card.selected")?.dataset.profile || "standard";
    const style = $("#signup-style").value;
    const error = $("#signup-error");
    error.textContent = "";
    if (username.length < 3) { error.textContent = "Le nom d’utilisateur doit contenir au moins 3 caractères."; return; }
    if (password.length < 6) { error.textContent = "Le mot de passe doit contenir au moins 6 caractères."; return; }
    if (password !== confirm) { error.textContent = "Les mots de passe ne correspondent pas."; return; }
    const accounts = getAccounts();
    if (accounts.some((account) => account.username.toLowerCase() === username.toLowerCase())) {
      error.textContent = "Ce nom d’utilisateur existe déjà sur cet appareil.";
      return;
    }
    try {
      const derived = await derivePassword(password);
      const account = { username, profile, style, salt: derived.salt, passwordHash: derived.hash, createdAt: new Date().toISOString() };
      accounts.push(account);
      saveAccounts(accounts);
      localStorage.setItem(SESSION_KEY, JSON.stringify({ username }));
      enterApp(account, false);
      toast("Votre espace est prêt.");
    } catch {
      error.textContent = "Impossible de créer le compte sur ce navigateur.";
    }
  });

  $("#login-form").onsubmit = async (event) => {
    event.preventDefault();
    const username = $("#login-username").value.trim();
    const password = $("#login-password").value;
    const error = $("#login-error");
    error.textContent = "";
    if (!username || !password) { error.textContent = "Veuillez saisir votre nom d’utilisateur et votre mot de passe."; return; }
    const account = getAccounts().find((item) => item.username.toLowerCase() === username.toLowerCase());
    if (!account) { error.textContent = "Compte introuvable sur cet appareil."; return; }
    try {
      const derived = await derivePassword(password, account.salt);
      if (derived.hash !== account.passwordHash) { error.textContent = "Mot de passe incorrect."; return; }
      localStorage.setItem(SESSION_KEY, JSON.stringify({ username: account.username }));
      enterApp(account, false);
    } catch {
      error.textContent = "Connexion impossible sur ce navigateur.";
    }
  };

  function enterGuest() {
    enterApp({ username: "Étudiante invitée", profile: "standard", style: "visuel" }, true);
  }
  $("#guest-entry").addEventListener("click", enterGuest);
  $("#login-guest").addEventListener("click", enterGuest);

  function enterApp(account, guest) {
    S.account = account;
    S.guest = guest;
    S.profile = guest ? "standard" : (account.profile || localStorage.getItem(PROFILE_KEY) || "standard");
    S.style = guest ? "visuel" : (account.style || localStorage.getItem(STYLE_KEY) || "visuel");
    localStorage.setItem(PROFILE_KEY, S.profile);
    localStorage.setItem(STYLE_KEY, S.style);
    $("#auth-view").hidden = true;
    $("#app-view").hidden = false;
    $("#auth-view").style.display = "none";
    $("#app-view").style.display = "block";
    document.body.classList.add("app-session");
    document.body.classList.remove("auth-session");
    applyProfile(S.profile);
    applyStyle(S.style);
    updateAccountUI();
    renderRecent();
    showView("dashboard");
  }

  $("#logout-button").addEventListener("click", () => {
    localStorage.removeItem(SESSION_KEY);
    S.account = null;
    S.guest = false;
    $("#app-view").hidden = true;
    $("#auth-view").hidden = false;
    $("#app-view").style.display = "none";
    $("#auth-view").style.display = "";
    document.body.classList.remove("app-session");
    document.body.classList.add("auth-session");
    setAuthMode(false);
  });

  $("#delete-account").addEventListener("click", () => {
    if (!S.account || S.guest) { toast("Aucun compte enregistré à supprimer."); return; }
    if (!confirm("Supprimer définitivement votre compte de cet appareil ?")) return;
    const accounts = getAccounts().filter((item) => item.username.toLowerCase() !== S.account.username.toLowerCase());
    saveAccounts(accounts);
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(PROFILE_KEY);
    localStorage.removeItem(STYLE_KEY);
    S.account = null;
    $("#app-view").hidden = true;
    $("#auth-view").hidden = false;
    $("#app-view").style.display = "none";
    $("#auth-view").style.display = "";
    document.body.classList.remove("app-session");
    document.body.classList.add("auth-session");
    setAuthMode(false);
    toast("Votre compte a été supprimé.");
  });

  function updateAccountUI() {
    const name = S.account?.username || "Étudiante invitée";
    $("#nav-username").textContent = name;
    $("#nav-avatar").textContent = name.charAt(0).toUpperCase();
    $("#nav-profile").textContent = `Profil ${S.cfg[S.profile]?.label || "Standard"}`;
    $("#welcome-title").textContent = `Bonjour ${name} 👋`;
  }

  function applyProfile(profile) {
    S.profile = ["standard", "tdah", "dyslexie", "dyscalculie", "autisme"].includes(profile) ? profile : "standard";
    document.body.dataset.profile = S.profile;
    const data = S.cfg[S.profile];
    const meta = profileMeta[S.profile];
    $("#profile-pill").textContent = data?.label || "Standard";
    $("#selected-profile-name").textContent = data?.label || "Standard";
    $("#selected-profile-label").textContent = meta.label;
    $("#selected-profile-help").textContent = data?.description || data?.diff?.help || "Apprentissage clair et équilibré.";
    $("#profile-icon").textContent = meta.icon;
    $("#nav-profile").textContent = `Profil ${data?.label || "Standard"}`;
    renderProfileCards("#profile-cards", S.profile);
    renderProfileCards("#settings-profile-cards", S.profile);
    if (S.profile === "dyslexie") {
      let savedSize = 19;
      try { savedSize = Number(localStorage.getItem("ns-dyslexia-text-size")) || 19; } catch {}
      const sizeControl = $("#dyslexia-text-size");
      if (sizeControl) sizeControl.value = String(savedSize);
      const chunk = $("#reader-chunk");
      if (chunk) chunk.style.fontSize = `${savedSize}px`;
    }
  }

  function applyStyle(style) {
    S.style = style;
    const data = S.styles[style];
    $("#selected-style-name").textContent = data?.label || "Visuel";
    $("#selected-style-help").textContent = data?.desc || "";
    $("#style-orb").textContent = (data?.label || "Visuel").charAt(0);
    renderStyleCards(style);
  }

  function savePreferences() {
    localStorage.setItem(PROFILE_KEY, S.profile);
    localStorage.setItem(STYLE_KEY, S.style);
    if (S.account && !S.guest) {
      const accounts = getAccounts();
      const index = accounts.findIndex((item) => item.username.toLowerCase() === S.account.username.toLowerCase());
      if (index >= 0) {
        accounts[index].profile = S.profile;
        accounts[index].style = S.style;
        saveAccounts(accounts);
        S.account = accounts[index];
      }
    }
  }

  $("#profile-cards").addEventListener("click", (event) => {
    const card = event.target.closest(".profile-card");
    if (!card) return;
    $$("#profile-cards .profile-card").forEach((item) => item.classList.remove("selected"));
    card.classList.add("selected");
  });
  $("#settings-profile-cards").addEventListener("click", (event) => {
    const card = event.target.closest(".profile-card");
    if (!card) return;
    applyProfile(card.dataset.profile);
    savePreferences();
  });
  $("#settings-style-cards").addEventListener("click", (event) => {
    const card = event.target.closest(".style-card");
    if (!card) return;
    applyStyle(card.dataset.style);
    savePreferences();
  });

  function showView(view) {
    if (view !== "reader") stopSpeech();
    $$(".app-view-section").forEach((section) => { section.hidden = section.id !== `view-${view}`; });
    $$(".side-nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
    const titles = { dashboard: "Bonjour", reader: "Mes cours", live: "Cours en direct", tools: "Outils d’apprentissage", review: "Bilan", demo: "Mode démo", settings: "Préférences" };
    $("#page-title").textContent = S.guest && view === "dashboard" ? "Bonjour 👋" : titles[view];
    $(".sidebar")?.classList.remove("open");
  }
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-view]");
    if (target) { event.preventDefault(); showView(target.dataset.view); }
  });
  $("#menu-button").addEventListener("click", () => $(".sidebar").classList.toggle("open"));

  function renderRecent() {
    const history = readJson(COURSE_HISTORY_KEY, []);
    const box = $("#recent-list");
    if (!history.length) {
      box.innerHTML = `<div class="recent-item"><div class="recent-icon">▤</div><div><strong>Aucun cours étudié</strong><small>Votre prochain cours apparaîtra ici.</small></div><button type="button" data-view="reader">Ouvrir →</button></div>`;
      return;
    }
    box.innerHTML = history.slice(0, 3).map((item) => `<div class="recent-item"><div class="recent-icon">▤</div><div><strong>${esc(item.title)}</strong><small>${esc(item.date)} · ${item.progress || 0} %</small></div><button type="button" data-reopen="${esc(item.id)}">Ouvrir →</button></div>`).join("");
  }

  function saveCourseHistory(title, progress) {
    const history = readJson(COURSE_HISTORY_KEY, []);
    const id = "course-" + Date.now();
    history.unshift({ id, title, progress, date: new Date().toLocaleDateString("fr-FR", { day: "numeric", month: "short" }) });
    writeJson(COURSE_HISTORY_KEY, history.slice(0, 8));
  }

  async function loadPdf(file) {
    showView("reader");
    $("#reader-empty").hidden = true;
    $("#reader-loading").hidden = false;
    $("#reader-content").hidden = true;
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("profile", S.profile);
      const response = await fetch("/api/pdf", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Lecture du PDF impossible.");
      openSections(data.sections, file.name.replace(/\.(pdf|txt)$/i, ""));
    } catch (error) {
      $("#reader-loading").hidden = true;
      $("#reader-empty").hidden = false;
      toast(error.message);
    }
  }

  async function loadDemoCourse() {
    showView("reader");
    $("#reader-empty").hidden = true;
    $("#reader-loading").hidden = false;
    $("#reader-content").hidden = true;
    try {
      const data = await api("/api/pdf/demo?profile=" + S.profile, null, "GET");
      openSections(data.sections, "La photosynthèse");
    } catch (error) {
      $("#reader-loading").hidden = true;
      $("#reader-empty").hidden = false;
      toast(error.message);
    }
  }

  function openSections(sections, title) {
    stopSpeech();
    S.sections = sections || [];
    S.lessons = {};
    S.chunkIndex = 0;
    $("#course-name").textContent = title;
    $("#reader-loading").hidden = true;
    $("#reader-empty").hidden = true;
    $("#reader-content").hidden = false;
    $("#course-outline").innerHTML = S.sections.map((section, index) =>
      `<button type="button" class="outline-item ${index === 0 ? "active" : ""}" data-index="${index}"><span class="outline-number">${index + 1}</span><span><strong>${esc(section.title)}</strong><small>${esc(section.summary)}</small></span></button>`
    ).join("");
    saveCourseHistory(title, 0);
    renderRecent();
    renderChunk();
  }

  function splitSentences(text) {
    return String(text || "").split(/(?<=[.!?])\s+/).filter(Boolean);
  }

  async function prepareLesson(section) {
    if (S.lessons[section.id]) return S.lessons[section.id];
    const lesson = await api("/api/lesson", { text: section.text, title: section.title, profile: S.profile, style: S.style });
    S.lessons[section.id] = lesson;
    return lesson;
  }

  async function renderChunk() {
    stopSpeech();
    const section = S.sections[S.chunkIndex];
    if (!section) return;
    $$("#course-outline .outline-item").forEach((item) => {
      const index = Number(item.dataset.index);
      item.classList.toggle("active", index === S.chunkIndex);
      item.classList.toggle("completed", index < S.chunkIndex);
      item.setAttribute("aria-current", index === S.chunkIndex ? "step" : "false");
    });
    $("#reader-progress-text").textContent = `Notion ${S.chunkIndex + 1} sur ${S.sections.length}`;
    $("#reader-progress").style.width = `${((S.chunkIndex + 1) / S.sections.length) * 100}%`;
    $("#reader-prev").disabled = S.chunkIndex === 0;
    $("#reader-next").textContent = S.chunkIndex === S.sections.length - 1 ? "Terminer" : "Notion suivante →";
    const chunk = $("#reader-chunk");
    chunk.innerHTML = `<span class="section-label">${esc(section.kind === "definition" ? "Définition" : section.kind === "liste" ? "Liste" : "Notion")}</span>${S.profile === "tdah" ? '<p class="learning-objective"><strong>Objectif :</strong> Comprendre cette notion et choisir l’action suivante.</p>' : ""}${S.profile === "autisme" ? `<p class="learning-objective"><strong>Étape ${S.chunkIndex + 1} sur ${S.sections.length} :</strong> Lisez cette notion, puis utilisez « Notion suivante ».</p>` : ""}<h2>${esc(section.title)}</h2><p class="lead">${esc(section.summary)}</p><div class="keyword-list">${section.keywords.map((word) => `<span>${esc(word)}</span>`).join("")}</div><div class="chunk-explanation"><div class="lesson-loading">Préparation de l’explication…</div></div><div class="audio-controls" role="group" aria-label="Contrôles audio de cette notion">
      <button type="button" class="audio-play primary-button" data-audio="play" aria-label="Lire cette notion">▶ Lire</button>
      <button type="button" class="audio-pause secondary-button" data-audio="pause" aria-label="Mettre la lecture en pause" disabled>Pause</button>
      <label class="volume-control">Volume <input type="range" data-audio="volume" min="0" max="1" step="0.05" value="${S.audio.volume}" aria-label="Volume de la lecture"><output data-audio-output>${Math.round(S.audio.volume * 100)} %</output></label>
      <span class="audio-state" data-audio-state>Audio arrêté</span>
    </div><div class="illustration-panel"><button class="secondary-button" type="button" data-illustration>Générer une illustration</button><div class="illustration-result"></div></div>`;
    try {
      const lesson = await prepareLesson(section);
      const explanation = chunk.querySelector(".chunk-explanation");
      explanation.innerHTML = "";
      if (lesson.idea) {
        const intro = document.createElement("p");
        intro.textContent = lesson.idea;
        explanation.appendChild(intro);
      }
      if (lesson.explain) {
        const body = document.createElement("p");
        body.textContent = lesson.explain;
        explanation.appendChild(body);
      }
      if (lesson.example) {
        const example = document.createElement("p");
        example.innerHTML = `<strong>Exemple :</strong> ${esc(lesson.example)}`;
        explanation.appendChild(example);
      }
      if (lesson.steps?.length) {
        const steps = document.createElement("div");
        steps.className = "chunk-steps";
        steps.innerHTML = `<strong>${S.profile === "dyscalculie" ? "Calcul expliqué, étape par étape" : "Étapes à suivre"}</strong><ol>${lesson.steps.map((step) => `<li>${esc(step)}</li>`).join("")}</ol>`;
        explanation.appendChild(steps);
      }
      if (lesson.check_q) {
        const check = document.createElement("details");
        check.innerHTML = `<summary>Vérifier ma compréhension</summary><p>${esc(lesson.check_q)}</p><p><strong>Réponse :</strong> ${esc(lesson.check_a)}</p>`;
        chunk.appendChild(check);
      }
    } catch {
      const explanation = chunk.querySelector(".chunk-explanation");
      explanation.textContent = section.text;
    }
  }

  $("#course-outline").addEventListener("click", (event) => {
    const item = event.target.closest(".outline-item");
    if (!item) return;
    S.chunkIndex = Number(item.dataset.index);
    renderChunk();
  });
  $("#reader-prev").addEventListener("click", () => { if (S.chunkIndex > 0) { S.chunkIndex--; renderChunk(); } });
  $("#reader-next").addEventListener("click", () => {
    if (S.chunkIndex < S.sections.length - 1) { S.chunkIndex++; renderChunk(); }
    else toast("Cours terminé. Vous pouvez choisir une autre notion.");
  });
  $("#reader-browse").addEventListener("click", () => $("#reader-file").click());
  $("#dashboard-browse").addEventListener("click", () => $("#dashboard-file").click());
  $("#dashboard-file").addEventListener("change", (event) => event.target.files[0] && loadPdf(event.target.files[0]));
  $("#reader-file").addEventListener("change", (event) => event.target.files[0] && loadPdf(event.target.files[0]));
  $("#dashboard-demo").addEventListener("click", loadDemoCourse);
  $("#reader-demo").addEventListener("click", loadDemoCourse);

  const drop = $("#dashboard-drop");
  ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove("dragover"); }));
  drop.addEventListener("drop", (event) => event.dataTransfer.files[0] && loadPdf(event.dataTransfer.files[0]));

  $("#reader-chunk").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-illustration]");
    if (!button) return;
    const section = S.sections[S.chunkIndex];
    const resultBox = button.parentElement.querySelector(".illustration-result");
    const cache = readJson(ILLUSTRATION_KEY, {});
    const key = `${section.title}|${section.summary}`;
    if (cache[key]) {
      showIllustration(resultBox, cache[key]);
      return;
    }
    button.disabled = true;
    button.textContent = "Recherche de l’illustration…";
    resultBox.innerHTML = `<div class="illustration-loading">Recherche d’une image pédagogique fiable…</div>`;
    try {
      const data = await api("/api/illustration", { title: section.title, context: section.summary });
      if (!data.image) throw new Error("Aucune illustration pertinente trouvée.");
      cache[key] = data;
      writeJson(ILLUSTRATION_KEY, cache);
      showIllustration(resultBox, data);
    } catch (error) {
      resultBox.innerHTML = `<div class="illustration-error">${esc(error.message)}</div>`;
    } finally {
      button.disabled = false;
      button.textContent = "Générer une autre illustration";
    }
  });

  function showIllustration(container, data) {
    container.innerHTML = "";
    const image = document.createElement("img");
    image.className = "illustration-image";
    image.src = data.image;
    image.alt = `Illustration pédagogique : ${data.title}`;
    const caption = document.createElement("p");
    caption.className = "illustration-caption";
    caption.textContent = `${data.title} · ${data.source}${data.caption ? " — " + data.caption : ""}`;
    container.append(image, caption);
  }

  function stopSpeech() {
    if (!("speechSynthesis" in window)) return;
    S.audio.utterance = null;
    S.audio.state = "stopped";
    S.audio.segments = [];
    S.audio.segmentIndex = 0;
    speechSynthesis.cancel();
    const state = $("#audio-status");
    if (state) state.textContent = "Audio arrêté";
  }

  function updateChunkAudioState(state) {
    S.audio.state = state;
    const chunk = $("#reader-chunk");
    const status = chunk?.querySelector("[data-audio-state]");
    const toolbarStatus = $("#audio-status");
    const play = chunk?.querySelector('[data-audio="play"]');
    const pause = chunk?.querySelector('[data-audio="pause"]');
    const labels = { stopped: "Audio arrêté", playing: "Lecture en cours", paused: "Lecture en pause" };
    if (status) status.textContent = labels[state];
    if (toolbarStatus) toolbarStatus.textContent = labels[state];
    if (play) {
      play.textContent = state === "paused" ? "▶ Reprendre" : state === "playing" ? "Lecture…" : "▶ Lire";
      play.disabled = state === "playing";
    }
    if (pause) {
      pause.disabled = state !== "playing";
      pause.textContent = "Pause";
    }
  }

  function playChunkAudio() {
    if (!("speechSynthesis" in window)) { toast("Synthèse vocale indisponible sur ce navigateur."); return; }
    const section = S.sections[S.chunkIndex];
    if (!section) return;
    if (S.audio.state === "paused") {
      if (S.audio.utterance) {
        if (typeof speechSynthesis.resume !== "function") {
          toast("Ce navigateur ne permet pas de reprendre cette lecture.");
          return;
        }
        speechSynthesis.resume();
      } else if (S.audio.segments.length) {
        speakSegment();
      } else {
        toast("Commencez d'abord la lecture.");
        return;
      }
      updateChunkAudioState("playing");
      return;
    }
    speechSynthesis.cancel();
    const lesson = S.lessons[section.id];
    const text = [lesson?.idea, lesson?.explain, lesson?.example, lesson?.steps?.length ? lesson.steps.join(". ") : ""]
      .filter(Boolean).join(". ") || section.text;
    S.audio.segments = text.match(/[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$/g)?.map((segment) => segment.trim()).filter(Boolean) || [text];
    S.audio.segmentIndex = 0;
    speakSegment();
    updateChunkAudioState("playing");
  }

  function speakSegment() {
    if (!S.audio.segments.length || S.audio.segmentIndex >= S.audio.segments.length) {
      S.audio.utterance = null;
      updateChunkAudioState("stopped");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(S.audio.segments[S.audio.segmentIndex]);
    utterance.lang = "fr-FR";
    utterance.rate = S.profile === "dyslexie" ? 0.85 : 0.95;
    utterance.volume = S.audio.volume;
    utterance.onstart = () => updateChunkAudioState("playing");
    utterance.onend = () => {
      if (S.audio.utterance !== utterance) return;
      if (S.audio.state !== "playing") return;
      S.audio.segmentIndex++;
      speakSegment();
    };
    utterance.onerror = (event) => {
      if (event.error === "interrupted" || event.error === "canceled") return;
      S.audio.utterance = null;
      updateChunkAudioState("stopped");
      toast("La lecture audio n'a pas pu démarrer.");
    };
    S.audio.utterance = utterance;
    speechSynthesis.speak(utterance);
  }

  $("#reader-chunk").addEventListener("click", (event) => {
    const action = event.target.closest("[data-audio]");
    if (!action) return;
    if (action.dataset.audio === "play") playChunkAudio();
    if (action.dataset.audio === "pause" && S.audio.state === "playing") {
      if (typeof speechSynthesis.pause === "function") {
        speechSynthesis.pause();
        updateChunkAudioState("paused");
      } else {
        toast("Ce navigateur ne permet pas de mettre cette lecture en pause.");
      }
    }
  });
  $("#reader-chunk").addEventListener("input", (event) => {
    if (event.target.dataset.audio !== "volume") return;
    S.audio.volume = Number(event.target.value);
    const output = event.target.parentElement.querySelector("[data-audio-output]");
    if (output) output.textContent = `${Math.round(S.audio.volume * 100)} %`;
    if (S.audio.utterance) {
      try { S.audio.utterance.volume = S.audio.volume; } catch {}
    }
  });

  function initChart() {
    if (!window.Chart) return;
    S.chart = new Chart($("#curve"), {
      type: "line",
      data: { labels: [], datasets: [{ label: "Attention", data: [], borderColor: "#176b5b", tension: 0.3 }] },
      options: { animation: false, scales: { y: { min: 0, max: 100 } }, plugins: { legend: { display: false } } }
    });
  }

  async function toggleMic() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { toast("Web Speech API indisponible : utilisez Chrome ou Edge."); return; }
    if (S.micOn) {
      S.micOn = false;
      S.rec?.stop();
      $("#mic-button").textContent = "Démarrer le micro";
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = "fr-FR";
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.onresult = async (event) => {
      const text = event.results[event.resultIndex][0].transcript;
      S.buf.push(text);
      try {
        await api("/api/subtitle", { text, target: "fr", profile: S.profile });
      } catch {}
    };
    recognition.onerror = (event) => toast(`Micro : ${event.error}`);
    recognition.onend = () => { if (S.micOn) { try { recognition.start(); } catch {} } };
    S.rec = recognition;
    S.micOn = true;
    recognition.start();
    $("#mic-button").textContent = "Arrêter le micro";
  }
  $("#mic-button").addEventListener("click", toggleMic);

  $("#catch-button").addEventListener("click", async () => {
    const context = S.buf.slice(-6).join(" ");
    if (!context) { toast("Aucun sous-titre récent à résumer."); return; }
    $("#live-help").textContent = "Préparation du résumé…";
    try {
      const data = await api("/api/catchup", { context, profile: S.profile });
      $("#live-help").textContent = data.text;
    } catch (error) { $("#live-help").textContent = error.message; }
  });
  $("#lost-button").addEventListener("click", async () => {
    $("#live-help").textContent = "Analyse de la notion bloquée…";
    try {
      const data = await api("/api/lost", { captions: S.buf.map((text) => ({ text })), profile: S.profile, target: "fr" });
      $("#live-help").innerHTML = `<strong>Notion bloquée : ${esc(data.point || data.concept)}</strong><p>${esc(data.simple_explanation || data.paragraph)}</p>${data.visual_svg || ""}`;
    } catch (error) { $("#live-help").textContent = error.message; }
  });
  $("#pulse-button").addEventListener("click", async () => {
    const data = await api("/api/micropulse", { text: S.buf.slice(-4).join(" ") });
    $("#live-help").innerHTML = `<strong>Micro-Pulse</strong><p>${esc(data.phrase)}</p><p>${esc(data.question)}</p>`;
  });

  $("#cam-button").addEventListener("click", async (event) => {
    if (!window.CameraTracker) { toast("Caméra locale indisponible."); return; }
    if (S.camOn) {
      CameraTracker.stop();
      S.camOn = false;
      $("#cam-video").hidden = true;
      event.target.textContent = "Activer la caméra";
      return;
    }
    try {
      await CameraTracker.start($("#cam-video"), (sample) => {
        if (S.chart) {
          S.chart.data.labels.push(new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }));
          S.chart.data.datasets[0].data.push(sample.attention);
          S.chart.update("none");
        }
      });
      S.camOn = true;
      $("#cam-video").hidden = false;
      event.target.textContent = "Caméra activée";
    } catch {
      toast("Autorisez la caméra ou utilisez « Je suis perdu ».");
    }
  });

  $("#yt-load").addEventListener("click", async () => {
    const url = $("#yt-url").value.trim();
    if (!url) { toast("Collez un lien YouTube."); return; }
    try {
      const response = await fetch("/api/youtube/transcript", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 422) $("#yt-paste-box").hidden = false;
        throw new Error(data.error || "Vidéo introuvable.");
      }
      loadYouTubePlayer(data);
    } catch (error) { toast(error.message); }
  });
  $("#yt-paste-box").previousElementSibling?.addEventListener("click", () => {});
  $("#yt-paste-ok").addEventListener("click", async () => {
    const url = $("#yt-url").value.trim();
    const text = $("#yt-paste").value.trim();
    if (!url || !text) { toast("Il faut le lien et la transcription."); return; }
    const response = await fetch("/api/youtube/transcript", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, text }) });
    const data = await response.json();
    if (!response.ok) { toast(data.error || "Chargement impossible."); return; }
    loadYouTubePlayer(data);
  });

  async function loadYouTubePlayer(data) {
    await new Promise((resolve) => {
      if (window.YT?.Player) resolve();
      window.onYouTubeIframeAPIReady = resolve;
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(script);
    });
    $("#yt-wrap").hidden = false;
    $("#yt-wrap").innerHTML = '<div id="yt-player"></div>';
    S.yt = { segs: data.segments, index: -1, player: new YT.Player("yt-player", { videoId: data.video_id, playerVars: { rel: 0, playsinline: 1 } }) };
    toast(`${data.segments.length} segments chargés.`);
  }
  setInterval(() => {
    if (!S.yt?.player?.getPlayerState || S.yt.player.getPlayerState() !== 1) return;
    const time = S.yt.player.getCurrentTime();
    let index = S.yt.index;
    while (index + 1 < S.yt.segs.length && S.yt.segs[index + 1].start <= time) index++;
    if (index > S.yt.index) {
      for (let i = S.yt.index + 1; i <= index; i++) {
        const text = S.yt.segs[i].text;
        S.buf.push(text);
      }
      S.yt.index = index;
    }
  }, 700);

  $("#task-button").addEventListener("click", async () => {
    const task = $("#task-input").value.trim();
    if (!task) { toast("Collez une consigne."); return; }
    const data = await api("/api/checklist", { task, profile: S.profile });
    $("#task-output").innerHTML = data.steps.map((step) => `<li><label><input type="checkbox"> ${esc(step)}</label></li>`).join("");
  });
  $("#gap-button").addEventListener("click", async () => {
    const text = $("#gap-input").value.trim();
    if (!text) { toast("Collez un passage du cours."); return; }
    const data = await api("/api/gaps", { text, profile: S.profile });
    $("#gap-output").innerHTML = data.gaps.map((gap) => `<div class="card-panel"><strong>${esc(gap.prereq)}</strong><p>${esc(gap.explain)}</p></div>`).join("");
  });

  async function loadReview() {
    const data = await api("/api/session/summary", null, "GET");
    $("#review-output").innerHTML = `<article class="card-panel"><strong>Séance</strong><p>Attention moyenne : ${data.avg_attention ?? "–"} % · ${data.lost_count} moment(s) « perdu »</p></article>` +
      (data.marks?.length ? data.marks.map((mark) => `<article class="card-panel"><strong>${esc(mark.label || "Notion")}</strong><p>Moment noté pendant la séance.</p></article>`).join("") : `<article class="card-panel"><p>Aucun moment marqué pour l'instant.</p></article>`);
  }
  $("#review-load").addEventListener("click", loadReview);

  async function demoLoad() {
    if (!S.demoSteps.length) S.demoSteps = (await api("/api/demo", null, "GET")).steps || [];
  }
  function demoPause() { clearInterval(S.demoTimer); }
  async function demoNext() {
    await demoLoad();
    const step = S.demoSteps[S.demoIndex];
    if (!step) { demoPause(); toast("Démo terminée."); return; }
    showView("live");
    S.buf.push(step.subtitle || step.text);
    S.demoIndex++;
  }
  $("#demo-play").addEventListener("click", async () => { await demoLoad(); demoPause(); await demoNext(); S.demoTimer = setInterval(demoNext, 3500); });
  $("#demo-pause").addEventListener("click", demoPause);
  $("#demo-next").addEventListener("click", demoNext);
  $("#demo-reset").addEventListener("click", () => { demoPause(); S.demoIndex = 0; S.demoSteps = []; S.buf = []; api("/api/session/reset", {}); });

  $("#header-settings").addEventListener("click", () => showView("settings"));

  async function restore() {
    await loadConfig();
    renderProfileCards("#profile-cards", "standard");
    renderProfileCards("#settings-profile-cards", S.profile);
    $("#header-date").textContent = new Date().toLocaleDateTimeString
      ? new Date().toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })
      : new Date().toLocaleDateString("fr-FR");
    const session = readJson(SESSION_KEY, null);
    if (session) {
      const account = getAccounts().find((item) => item.username === session.username);
      if (account) { enterApp(account, false); return; }
    }
    setAuthMode(false);
  }

  $("#dyslexia-text-size")?.addEventListener("input", (event) => {
    const size = Number(event.target.value);
    const chunk = $("#reader-chunk");
    if (chunk) chunk.style.fontSize = `${size}px`;
    try { localStorage.setItem("ns-dyslexia-text-size", String(size)); } catch {}
  });

  initChart();
  restore();
})();
