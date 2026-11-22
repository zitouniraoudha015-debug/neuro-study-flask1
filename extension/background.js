// Relais réseau : le content script ne parle jamais directement à Flask (évite CORS / contenu mixte).
const API_BASE = "http://127.0.0.1:5000";

async function pingBackend() {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(4000) });
    if (!res.ok) return { connected: false };
    const json = await res.json();
    return { connected: Boolean(json && json.ok), llm: Boolean(json && json.llm), providers: (json && json.providers) || [] };
  } catch (_err) {
    return { connected: false };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "PING_BACKEND") {
    pingBackend().then(sendResponse);
    return true;
  }

  if (msg.type === "API_CALL") {
    const method = msg.method || "POST";
    fetch(`${API_BASE}${msg.endpoint}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: msg.body && method !== "GET" ? JSON.stringify(msg.body) : undefined,
      signal: AbortSignal.timeout(msg.timeout || 30000), // « Je suis perdu » demande 60 s (l'IA peut être lente)
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        sendResponse({ ok: res.ok, data });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err && err.message) }));
    return true;
  }
});
