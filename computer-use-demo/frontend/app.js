/** Computer Use demo: chat + remote desktop in the browser. */
(function () {
  const API_BASE = "";

  const VNC_IDLE_HINT = "Start a session to see the remote desktop here.";

  const VNC_IFRAME_LOAD_TIMEOUT_MS = 45000;

  const el = {
    createForm: document.getElementById("create-session-form"),
    apiKey: document.getElementById("api-key"),
    baseUrlPreset: document.getElementById("base-url-preset"),
    customBaseUrlWrap: document.getElementById("custom-base-url-wrap"),
    baseUrlCustom: document.getElementById("base-url-custom"),
    btnNew: document.getElementById("btn-new"),
    btnNewChat: document.getElementById("btn-new-chat"),
    sessionList: document.getElementById("session-list"),
    sessionLabel: document.getElementById("session-label"),
    chatLog: document.getElementById("chat-log"),
    chatForm: document.getElementById("chat-form"),
    chatInput: document.getElementById("chat-input"),
    btnSend: document.getElementById("btn-send"),
    vncFrame: document.getElementById("vnc-frame"),
    vncPlaceholder: document.getElementById("vnc-placeholder"),
    vncPanelBar: document.getElementById("vnc-panel-bar"),
    vncOpenTab: document.getElementById("vnc-open-tab"),
    vncReloadEmbed: document.getElementById("vnc-reload-embed"),
    vncHttpUrl: document.getElementById("vnc-http-url"),
  };

  /** @type {number | null} */
  let sessionId = null;
  /** @type {WebSocket | null} */
  let socket = null;
  /** @type {string | null} */
  let lastVncHttpUrl = null;

  function sleep(ms) {
    return new Promise((resolve) => {
      setTimeout(resolve, ms);
    });
  }

  /**
   * @param {HTMLIFrameElement} frame
   * @param {number} timeoutMs
   * @returns {Promise<void>}
   */
  function waitForIframeLoad(frame, timeoutMs) {
    return new Promise((resolve, reject) => {
      const onLoad = () => {
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(() => {
        frame.removeEventListener("load", onLoad);
        reject(new Error("iframe load timeout"));
      }, timeoutMs);
      frame.addEventListener("load", onLoad, { once: true });
    });
  }

  function setVncUrlToolbar(httpUrl) {
    lastVncHttpUrl = httpUrl;
    if (!httpUrl) {
      el.vncPanelBar.hidden = true;
      el.vncOpenTab.disabled = true;
      el.vncReloadEmbed.disabled = true;
      el.vncHttpUrl.textContent = "";
      el.vncHttpUrl.title = "";
      return;
    }
    el.vncPanelBar.hidden = false;
    el.vncOpenTab.disabled = false;
    el.vncReloadEmbed.disabled = false;
    el.vncHttpUrl.textContent = httpUrl;
    el.vncHttpUrl.title = httpUrl;
  }

  function showVncPlaceholder(message) {
    el.vncFrame.src = "";
    el.vncFrame.hidden = true;
    el.vncPlaceholder.hidden = false;
    el.vncPlaceholder.textContent = message;
    setVncUrlToolbar(null);
  }

  function appendProgress(text) {
    const div = document.createElement("div");
    div.className = "msg progress";
    div.textContent = text;
    el.chatLog.appendChild(div);
    el.chatLog.scrollTop = el.chatLog.scrollHeight;
  }

  function roleLabel(role) {
    if (role === "user") return "You";
    if (role === "assistant") return "Assistant";
    return role;
  }

  function appendMessage(role, content) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const roleEl = document.createElement("div");
    roleEl.className = "role";
    roleEl.textContent = roleLabel(role);
    const body = document.createElement("div");
    body.className = "msg-body";
    body.textContent = content;
    div.appendChild(roleEl);
    div.appendChild(body);
    el.chatLog.appendChild(div);
    el.chatLog.scrollTop = el.chatLog.scrollHeight;
  }

  /**
   * Renders a persisted or live message using the same rules as the stream:
   * `progress` assistant rows use the café activity style (matches WebSocket progress).
   * @param {{ role: string, content: string, message_kind?: string }} m
   */
  function appendMessageFromRecord(m) {
    const kind = m.message_kind != null ? String(m.message_kind) : "chat";
    if (kind === "progress" && m.role === "assistant") {
      appendProgress(m.content != null ? String(m.content) : "");
      return;
    }
    appendMessage(m.role || "unknown", m.content != null ? String(m.content) : "");
  }

  /** Accepts plain text; if pasted legacy JSON chat payload, uses the inner text only. */
  function normalizeOutgoingChat(raw) {
    const text = raw.trim();
    if (!text) return null;
    if (text.startsWith("{")) {
      try {
        const o = JSON.parse(text);
        if (
          o &&
          typeof o === "object" &&
          o.type === "chat" &&
          typeof o.content === "string"
        ) {
          const inner = o.content.trim();
          return inner || null;
        }
      } catch {
        /* treat as literal message */
      }
    }
    return text;
  }

  function closeSocket() {
    if (socket) {
      socket.close();
      socket = null;
    }
  }

  function formatSessionLabel(meta) {
    if (!meta) return "No active session";
    const ep = meta.api_endpoint === "packyapi" ? "PackyAPI" : "Anthropic API";
    return `Session #${meta.id} · ${meta.status} · ${ep}`;
  }

  function connectWebSocket() {
    if (sessionId == null) return;
    closeSocket();
    const boundSessionId = sessionId;
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
      if (data.type === "vnc_ready") {
        const u = data.http_url != null ? String(data.http_url) : "";
        if (u) void attachVncIframe(u);
        return;
      }
      if (data.type === "vnc_timeout") {
        const line =
          data.content != null
            ? String(data.content)
            : "The desktop took too long to appear.";
        appendProgress(line);
        el.vncPlaceholder.hidden = false;
        el.vncPlaceholder.textContent = `${line} Try “Open in new tab” or “Reload”.`;
        return;
      }
      if (data.type === "progress") {
        const line =
          data.content != null
            ? String(data.content)
            : data.message != null
              ? String(data.message)
              : "…";
        appendProgress(line);
        return;
      }
      if (data.type === "message" && data.message) {
        appendMessageFromRecord(data.message);
        return;
      }
    });

    socket.addEventListener("close", () => {
      el.chatInput.disabled = true;
      el.btnSend.disabled = true;
      if (boundSessionId === sessionId) {
        appendProgress("Disconnected.");
      }
    });

    socket.addEventListener("error", () => {
      appendProgress("Connection lost. Refresh the page and try again.");
    });
  }

  async function loadHistory() {
    if (sessionId == null) return;
    const r = await fetch(`${API_BASE}/api/sessions/${sessionId}/history`);
    if (!r.ok) return;
    const messages = await r.json();
    el.chatLog.innerHTML = "";
    for (const m of messages) {
      appendMessageFromRecord(m);
    }
  }

  async function reloadVncEmbed() {
    if (!lastVncHttpUrl) return;
    el.vncPlaceholder.hidden = false;
    el.vncPlaceholder.textContent = "Reconnecting…";
    try {
      el.vncFrame.src = "";
      await sleep(80);
      const loadPromise = waitForIframeLoad(el.vncFrame, VNC_IFRAME_LOAD_TIMEOUT_MS);
      el.vncFrame.src = lastVncHttpUrl;
      await loadPromise;
      el.vncPlaceholder.hidden = true;
    } catch {
      el.vncPlaceholder.textContent =
        "Reload timed out. Try “Open in new tab”.";
    }
  }

  async function prepareVncEmbed() {
    if (sessionId == null) return;
    const r = await fetch(`${API_BASE}/api/sessions/${sessionId}/vnc`);
    if (!r.ok) {
      showVncPlaceholder(
        r.status === 404
          ? "Remote desktop isn’t available for this session."
          : "Couldn’t load the desktop view.",
      );
      return;
    }
    const info = await r.json();
    const httpUrl = info.http_url != null ? String(info.http_url) : "";
    if (!httpUrl) {
      showVncPlaceholder("Desktop link unavailable.");
      return;
    }
    setVncUrlToolbar(httpUrl);
    el.vncFrame.src = "";
    el.vncFrame.hidden = true;
    el.vncPlaceholder.hidden = false;
    el.vncPlaceholder.textContent = "Preparing the desktop…";
  }

  async function attachVncIframe(httpUrl) {
    const url = httpUrl != null ? String(httpUrl) : "";
    if (!url) return;
    setVncUrlToolbar(url);
    el.vncPlaceholder.hidden = false;
    el.vncPlaceholder.textContent = "Loading desktop…";
    el.vncFrame.hidden = false;
    try {
      const loadPromise = waitForIframeLoad(el.vncFrame, VNC_IFRAME_LOAD_TIMEOUT_MS);
      el.vncFrame.src = url;
      await loadPromise;
      el.vncPlaceholder.hidden = true;
    } catch {
      el.vncPlaceholder.hidden = false;
      el.vncPlaceholder.textContent =
        "The desktop view didn’t load in time. Try “Reload” or “Open in new tab”.";
    }
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

  function buildCreateSessionPayload() {
    const key = el.apiKey.value.trim();
    if (!key) {
      return { payload: {}, error: "Enter your Anthropic API key." };
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
          error: "Enter an HTTPS URL (for example https://www.packyapi.com).",
        };
      }
      if (!bu.startsWith("https://")) {
        return {
          payload: {},
          error: "The URL must start with https://",
        };
      }
      payload.api_endpoint = "global";
      payload.base_url = bu;
    }
    return { payload };
  }

  /**
   * @typedef {{ id: number; status: string; created_at: string; api_endpoint: string | null; docker_container_id: string | null }} SessionRow
   */

  async function fetchSessionList() {
    const r = await fetch(`${API_BASE}/api/sessions`);
    if (!r.ok) return [];
    return /** @type {SessionRow[]} */ (await r.json());
  }

  function formatSessionTime(iso) {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  }

  async function renderSessionList() {
    const sessions = await fetchSessionList();
    el.sessionList.innerHTML = "";
    for (const s of sessions) {
      const li = document.createElement("li");
      li.className = "session-item" + (s.id === sessionId ? " active" : "");
      li.dataset.sessionId = String(s.id);

      const mainBtn = document.createElement("button");
      mainBtn.type = "button";
      mainBtn.className = "session-item-main";
      const title = document.createElement("span");
      title.className = "session-item-title";
      title.textContent = `Session #${s.id}`;
      const meta = document.createElement("span");
      meta.className = "session-item-meta";
      meta.textContent = `${s.status} · ${formatSessionTime(s.created_at)}`;
      mainBtn.appendChild(title);
      mainBtn.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "session-item-actions";

      if (s.status === "stopped") {
        const resumeBtn = document.createElement("button");
        resumeBtn.type = "button";
        resumeBtn.className = "session-item-resume";
        resumeBtn.textContent = "Resume";
        resumeBtn.title = "Start the same Docker desktop again (history preserved)";
        resumeBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          void resumeSession(s.id);
        });
        actions.appendChild(resumeBtn);
      } else {
        const stopBtn = document.createElement("button");
        stopBtn.type = "button";
        stopBtn.className = "session-item-stop";
        stopBtn.textContent = "Stop";
        stopBtn.title = "Pause the remote desktop (you can resume later)";
        stopBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          void stopSession(s.id);
        });
        actions.appendChild(stopBtn);
      }

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "session-item-remove";
      removeBtn.textContent = "Remove";
      removeBtn.title = "Delete session and chat history";
      removeBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        void removeSession(s.id);
      });
      actions.appendChild(removeBtn);

      mainBtn.addEventListener("click", () => {
        void openSession(s.id);
      });

      li.appendChild(mainBtn);
      li.appendChild(actions);
      el.sessionList.appendChild(li);
    }
  }

  function startNewChatDraft() {
    closeSocket();
    sessionId = null;
    el.chatLog.innerHTML = "";
    el.sessionLabel.textContent = "No active session";
    el.chatInput.disabled = true;
    el.btnSend.disabled = true;
    showVncPlaceholder(VNC_IDLE_HINT);
    void renderSessionList();
    el.createForm.scrollIntoView({ behavior: "smooth", block: "start" });
    setTimeout(() => {
      el.apiKey.focus();
    }, 200);
  }

  async function openSession(id) {
    const numId = Number(id);
    if (numId === sessionId && socket && socket.readyState === WebSocket.OPEN) {
      return;
    }
    el.chatInput.disabled = true;
    el.btnSend.disabled = true;
    closeSocket();
    sessionId = numId;
    try {
      const r = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
      if (!r.ok) {
        appendProgress("Could not open this session.");
        sessionId = null;
        await renderSessionList();
        return;
      }
      /** @type {SessionRow} */
      const data = await r.json();
      el.sessionLabel.textContent = formatSessionLabel(data);
      el.chatLog.innerHTML = "";
      await loadHistory();
      if (data.status === "stopped") {
        el.chatInput.disabled = true;
        el.btnSend.disabled = true;
        showVncPlaceholder(
          "Session stopped — click Resume in the sidebar to start the desktop and chat again.",
        );
        await renderSessionList();
        return;
      }
      await prepareVncEmbed();
      connectWebSocket();
    } catch {
      appendProgress("Could not open this session.");
      sessionId = null;
    }
    await renderSessionList();
  }

  async function stopSession(id) {
    const ok = window.confirm(
      "Pause the remote desktop? The session and chat stay; you can Resume later.",
    );
    if (!ok) return;
    const r = await fetch(`${API_BASE}/api/sessions/${id}/stop`, {
      method: "POST",
    });
    if (!r.ok) {
      appendProgress("Could not stop the session.");
      return;
    }
    if (sessionId === id) {
      closeSocket();
      el.chatInput.disabled = true;
      el.btnSend.disabled = true;
      showVncPlaceholder(
        "Session stopped — click Resume in the sidebar to start the desktop again.",
      );
    }
    await renderSessionList();
  }

  async function resumeSession(id) {
    const r = await fetch(`${API_BASE}/api/sessions/${id}/resume`, {
      method: "POST",
    });
    if (!r.ok) {
      let line = "Could not resume the session.";
      try {
        const err = await r.json();
        if (typeof err.detail === "string") {
          line = err.detail;
        }
      } catch {
        /* keep default */
      }
      appendProgress(line);
      return;
    }
    if (sessionId === id) {
      await openSession(id);
    } else {
      await renderSessionList();
    }
  }

  async function removeSession(id) {
    const ok = window.confirm(
      "Remove this session permanently? Chat history will be deleted and any running desktop will be stopped.",
    );
    if (!ok) return;
    const r = await fetch(`${API_BASE}/api/sessions/${id}`, { method: "DELETE" });
    if (r.status !== 204) {
      appendProgress("Could not remove the session.");
      return;
    }
    if (sessionId === id) {
      startNewChatDraft();
    } else {
      await renderSessionList();
    }
  }

  async function createSession() {
    el.btnNew.disabled = true;
    closeSocket();
    el.chatLog.innerHTML = "";
    el.chatInput.disabled = true;
    el.btnSend.disabled = true;
    showVncPlaceholder("Starting…");

    const built = buildCreateSessionPayload();
    if (built.error) {
      appendProgress(built.error);
      el.btnNew.disabled = false;
      showVncPlaceholder(VNC_IDLE_HINT);
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
        let line = "Couldn’t start the session. Please try again.";
        try {
          const err = await r.json();
          if (typeof err.detail === "string") {
            line = err.detail;
          } else if (Array.isArray(err.detail) && err.detail[0]?.msg) {
            line = String(err.detail[0].msg);
          }
        } catch {
          /* keep default */
        }
        appendProgress(line);
        showVncPlaceholder(VNC_IDLE_HINT);
        return;
      }
      /** @type {SessionRow} */
      const data = await r.json();
      sessionId = data.id;
      el.sessionLabel.textContent = formatSessionLabel(data);
      await loadHistory();
      await prepareVncEmbed();
      connectWebSocket();
      await renderSessionList();
    } catch {
      appendProgress("Network error. Check your connection and try again.");
      showVncPlaceholder(VNC_IDLE_HINT);
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

  el.btnNewChat.addEventListener("click", () => {
    startNewChatDraft();
  });

  el.vncOpenTab.addEventListener("click", () => {
    if (!lastVncHttpUrl) return;
    window.open(lastVncHttpUrl, "_blank", "noopener,noreferrer");
  });

  el.vncReloadEmbed.addEventListener("click", () => {
    void reloadVncEmbed();
  });

  el.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const content = normalizeOutgoingChat(el.chatInput.value);
    if (!content || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "chat", content }));
    el.chatInput.value = "";
    el.chatInput.focus();
  });

  el.chatInput.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    if (el.chatInput.disabled) return;
    e.preventDefault();
    el.chatForm.requestSubmit();
  });

  void renderSessionList();
})();
