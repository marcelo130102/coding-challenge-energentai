/**
 * Demo UI: REST + WebSocket against the same origin as this page (FastAPI).
 */
(function () {
  const API_BASE = "";

  const el = {
    createForm: document.getElementById("create-session-form"),
    apiKey: document.getElementById("api-key"),
    baseUrlPreset: document.getElementById("base-url-preset"),
    customBaseUrlWrap: document.getElementById("custom-base-url-wrap"),
    baseUrlCustom: document.getElementById("base-url-custom"),
    btnNew: document.getElementById("btn-new"),
    sessionLabel: document.getElementById("session-label"),
    chatLog: document.getElementById("chat-log"),
    chatForm: document.getElementById("chat-form"),
    chatInput: document.getElementById("chat-input"),
    btnSend: document.getElementById("btn-send"),
    vncFrame: document.getElementById("vnc-frame"),
    vncPlaceholder: document.getElementById("vnc-placeholder"),
  };

  /** @type {number | null} */
  let sessionId = null;
  /** @type {WebSocket | null} */
  let socket = null;

  function appendProgress(text) {
    const div = document.createElement("div");
    div.className = "msg progress";
    div.textContent = text;
    el.chatLog.appendChild(div);
    el.chatLog.scrollTop = el.chatLog.scrollHeight;
  }

  function appendMessage(role, content) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const roleEl = document.createElement("div");
    roleEl.className = "role";
    roleEl.textContent = role;
    const body = document.createElement("div");
    body.textContent = content;
    div.appendChild(roleEl);
    div.appendChild(body);
    el.chatLog.appendChild(div);
    el.chatLog.scrollTop = el.chatLog.scrollHeight;
  }

  function closeSocket() {
    if (socket) {
      socket.close();
      socket = null;
    }
  }

  function connectWebSocket() {
    if (sessionId == null) return;
    closeSocket();
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/api/sessions/${sessionId}/ws`;
    socket = new WebSocket(url);

    socket.addEventListener("open", () => {
      el.chatInput.disabled = false;
      el.btnSend.disabled = false;
    });

    socket.addEventListener("message", (ev) => {
      let data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        appendProgress(String(ev.data));
        return;
      }
      if (data.type === "progress") {
        const line =
          data.content != null
            ? String(data.content)
            : data.message != null
              ? String(data.message)
              : JSON.stringify(data);
        appendProgress(line);
        return;
      }
      if (data.type === "message" && data.message) {
        const m = data.message;
        appendMessage(m.role || "unknown", m.content || "");
        return;
      }
    });

    socket.addEventListener("close", () => {
      el.chatInput.disabled = true;
      el.btnSend.disabled = true;
      appendProgress("(WebSocket closed)");
    });

    socket.addEventListener("error", () => {
      appendProgress("(WebSocket error — is the API running?)");
    });
  }

  async function loadHistory() {
    if (sessionId == null) return;
    const r = await fetch(`${API_BASE}/api/sessions/${sessionId}/history`);
    if (!r.ok) return;
    const messages = await r.json();
    el.chatLog.innerHTML = "";
    for (const m of messages) {
      appendMessage(m.role, m.content);
    }
  }

  async function loadVncIframe() {
    if (sessionId == null) return;
    const r = await fetch(`${API_BASE}/api/sessions/${sessionId}/vnc`);
    if (!r.ok) {
      el.vncFrame.hidden = true;
      el.vncPlaceholder.hidden = false;
      el.vncPlaceholder.textContent =
        r.status === 404
          ? "No VNC endpoint for this session (needs vnc_port). Use Docker orchestration or create session with vnc_port when orchestration is off."
          : "Could not load VNC info.";
      return;
    }
    const info = await r.json();
    el.vncPlaceholder.hidden = true;
    el.vncFrame.hidden = false;
    el.vncFrame.src = info.http_url;
  }

  function syncBaseUrlCustomVisibility() {
    const isCustom = el.baseUrlPreset.value === "custom";
    el.customBaseUrlWrap.hidden = !isCustom;
    if (isCustom) {
      el.baseUrlCustom.required = true;
    } else {
      el.baseUrlCustom.required = false;
      el.baseUrlCustom.value = "";
    }
  }

  /**
   * @returns {{ payload: Record<string, unknown>, error?: string }}
   */
  function buildCreateSessionPayload() {
    const key = el.apiKey.value.trim();
    if (!key) {
      return { payload: {}, error: "Introduce tu API key de Anthropic." };
    }
    const preset = el.baseUrlPreset.value;
    /** @type {Record<string, unknown>} */
    const payload = {
      status: "active",
      api_key: key,
    };
    if (preset === "global") {
      payload.api_endpoint = "global";
    } else if (preset === "packyapi") {
      payload.api_endpoint = "packyapi";
    } else if (preset === "custom") {
      const bu = el.baseUrlCustom.value.trim();
      if (!bu) {
        return {
          payload: {},
          error: "Introduce una base URL HTTPS (p. ej. https://www.packyapi.com).",
        };
      }
      if (!bu.startsWith("https://")) {
        return {
          payload: {},
          error: "La base URL debe empezar por https://",
        };
      }
      payload.api_endpoint = "global";
      payload.base_url = bu;
    }
    return { payload };
  }

  async function createSession() {
    el.btnNew.disabled = true;
    closeSocket();
    el.chatLog.innerHTML = "";
    el.chatInput.disabled = true;
    el.btnSend.disabled = true;
    el.vncFrame.src = "";
    el.vncFrame.hidden = true;
    el.vncPlaceholder.hidden = false;
    el.vncPlaceholder.textContent = "Loading…";

    const built = buildCreateSessionPayload();
    if (built.error) {
      appendProgress(built.error);
      el.btnNew.disabled = false;
      el.vncPlaceholder.textContent =
        "Create a session with VNC (Docker orchestration) or assign vnc_port to see the desktop here.";
      return;
    }
    const payload = built.payload;

    try {
      const r = await fetch(`${API_BASE}/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        appendProgress(`Create session failed: ${r.status} ${JSON.stringify(err)}`);
        return;
      }
      const data = await r.json();
      sessionId = data.id;
      el.sessionLabel.textContent = `Session #${sessionId} · ${data.status} · endpoint: ${data.api_endpoint ?? "?"}`;
      await loadHistory();
      await loadVncIframe();
      connectWebSocket();
    } catch (e) {
      appendProgress(`Network error: ${e}`);
    } finally {
      el.btnNew.disabled = false;
    }
  }

  el.baseUrlPreset.addEventListener("change", syncBaseUrlCustomVisibility);
  syncBaseUrlCustomVisibility();

  el.createForm.addEventListener("submit", (e) => {
    e.preventDefault();
    void createSession();
  });

  el.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = el.chatInput.value.trim();
    if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "chat", content: text }));
    el.chatInput.value = "";
  });
})();
