const API_BASE = "https://production-chatbot-production.up.railway.app";

let CURRENT_THREAD_ID = null;

const el = (id) => document.getElementById(id);
const authScreen = el("auth-screen");
const appShell = el("app-shell");
const sidebar = el("sidebar");
const messageLog = el("message-log");
const authForm = el("auth-form");
const authError = el("auth-error");
const composer = el("composer");
const chatInput = el("chat-input");
const currentThreadTitle = el("current-thread-title");
const pinnedList = el("pinned-list");
const recentList = el("recent-list");

function showScreen(name) {
  authScreen.classList.toggle("active", name === "auth");
  appShell.classList.toggle("active", name === "app");
}

function getToken() {
  return localStorage.getItem("token");
}
function getRefreshToken() {
  return localStorage.getItem("refresh_token");
}
function setTokens(accessToken, refreshToken) {
  localStorage.setItem("token", accessToken);
  if (refreshToken) localStorage.setItem("refresh_token", refreshToken);
}
function clearTokens() {
  localStorage.removeItem("token");
  localStorage.removeItem("refresh_token");
}

async function authRequest(path, body, isForm) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: isForm
      ? { "Content-Type": "application/x-www-form-urlencoded" }
      : { "Content-Type": "application/json" },
    body: isForm ? body : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail ? formatDetail(data.detail) : `Request failed (${res.status})`);
  }
  return data;
}

function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
  return JSON.stringify(detail);
}

async function register(email, password) {
  const data = await authRequest("/auth/register", { email, password }, false);
  if (data.status === "verification_sent") {
    authError.textContent = "Check your email to verify your account, then log in.";
    return;
  }
  await onAuthed(data.access_token, data.refresh_token);
}

async function login(email, password) {
  const body = new URLSearchParams({ username: email, password });
  const data = await authRequest("/auth/login", body, true);
  await onAuthed(data.access_token, data.refresh_token);
}

async function tryRefresh() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

async function onAuthed(accessToken, refreshToken) {
  setTokens(accessToken, refreshToken);
  showScreen("app");
  chatInput.focus();

  const threads = await loadThreads();
  if (threads.length > 0) {
    await selectThread(threads[0].thread_id);
  } else {
    await createNewThread();
  }
}

async function logout() {
  const refreshToken = getRefreshToken();
  if (refreshToken) {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
    }
  }
  clearTokens();
  CURRENT_THREAD_ID = null;
  messageLog.innerHTML = "";
  pinnedList.innerHTML = "";
  recentList.innerHTML = "";
  showScreen("auth");
  authForm.reset();
}

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  authError.textContent = "";
  const email = el("email").value.trim();
  const password = el("password").value;
  try {
    await login(email, password);
  } catch (err) {
    authError.textContent = err.message;
  }
});

el("register-btn").addEventListener("click", async () => {
  authError.textContent = "";
  const email = el("email").value.trim();
  const password = el("password").value;
  if (!email || !password) {
    authError.textContent = "Enter an email and password first.";
    return;
  }
  try {
    await register(email, password);
  } catch (err) {
    authError.textContent = err.message;
  }
});

el("logout-btn").addEventListener("click", logout);

async function authedFetch(path, options = {}, isRetry = false) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${getToken()}`,
    },
  });

  if (res.status === 401 && !isRetry) {
    if (await tryRefresh()) {
      return authedFetch(path, options, true);
    }
    appendSystemMessage("Session expired — please log in again.");
    setTimeout(logout, 1200);
    return null;
  }
  return res;
}

async function loadThreads() {
  const res = await authedFetch("/chat/threads");
  if (!res || !res.ok) return [];
  const data = await res.json();
  renderThreadList(data.threads);
  return data.threads;
}

function renderThreadList(threads) {
  const pinned = threads.filter((t) => t.pinned);
  const recent = threads.filter((t) => !t.pinned);
  renderThreadGroup(pinnedList, pinned);
  renderThreadGroup(recentList, recent);
}

function renderThreadGroup(container, threads) {
  container.innerHTML = "";
  threads.forEach((t) => {
    const tpl = document.getElementById("tpl-thread-item");
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.classList.toggle("thread-item--active", t.thread_id === CURRENT_THREAD_ID);
    node.querySelector(".thread-title").textContent = t.title || "New chat";
    node.querySelector(".pin-btn").textContent = t.pinned ? "★" : "☆";

    node.addEventListener("click", (e) => {
      if (e.target.closest(".pin-btn")) return;
      selectThread(t.thread_id);
      closeMobileSidebar();
    });
    node.querySelector(".pin-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      togglePin(t.thread_id, !t.pinned);
    });

    container.appendChild(node);
  });
}

async function createNewThread() {
  const res = await authedFetch("/chat/threads", { method: "POST" });
  if (!res || !res.ok) return;
  const data = await res.json();
  CURRENT_THREAD_ID = data.thread_id;
  currentThreadTitle.textContent = "New chat";
  messageLog.innerHTML = "";
  await loadThreads();
  chatInput.focus();
}

async function selectThread(threadId) {
  CURRENT_THREAD_ID = threadId;
  const res = await authedFetch(`/chat/threads/${threadId}/messages`);
  messageLog.innerHTML = "";
  if (res && res.ok) {
    const data = await res.json();
    data.messages.forEach((m) => {
      if (m.role === "user") appendUserMessage(m.content);
      else appendAgentMessage(m.content);
    });
  }
  const threads = await loadThreads();
  const active = threads.find((t) => t.thread_id === threadId);
  currentThreadTitle.textContent = active ? active.title : "New chat";
}

async function togglePin(threadId, pinned) {
  await authedFetch(`/chat/threads/${threadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pinned }),
  });
  await loadThreads();
}

el("new-chat-btn").addEventListener("click", () => {
  createNewThread();
  closeMobileSidebar();
});

el("sidebar-open-btn").addEventListener("click", () => sidebar.classList.add("open"));
el("sidebar-close-btn").addEventListener("click", () => sidebar.classList.remove("open"));
function closeMobileSidebar() {
  sidebar.classList.remove("open");
}

function appendFromTemplate(templateId) {
  const tpl = document.getElementById(templateId);
  const node = tpl.content.firstElementChild.cloneNode(true);
  messageLog.appendChild(node);
  messageLog.scrollTop = messageLog.scrollHeight;
  return node;
}

function appendUserMessage(text) {
  const node = appendFromTemplate("tpl-message-user");
  node.querySelector(".msg-bubble").textContent = text;
}

function appendAgentMessage(text) {
  const node = appendFromTemplate("tpl-message-agent");
  node.querySelector(".msg-bubble").textContent = text;
}

function appendSystemMessage(text) {
  const node = appendFromTemplate("tpl-message-system");
  node.querySelector(".msg-bubble").textContent = text;
}

function appendStreamingAgentMessage() {
  const node = appendFromTemplate("tpl-message-agent");
  node.querySelector(".msg-bubble").classList.add("msg-bubble--streaming");
  return node;
}

function showTyping() {
  return appendFromTemplate("tpl-typing");
}

function appendTicket(prompt) {
  const node = appendFromTemplate("tpl-ticket");
  node.querySelector(".ticket-prompt").textContent = prompt;
  node.querySelectorAll("[data-decision]").forEach((btn) => {
    btn.addEventListener("click", () => resolveTicket(node, btn.dataset.decision, prompt));
  });
  return node;
}

function resolveTicketUI(node, decision) {
  node.classList.add("ticket--resolved");
  node.querySelector(".ticket-flag").textContent =
    decision === "yes" ? "◆ APPROVED" : "◆ DECLINED";
  node.querySelectorAll("button").forEach((b) => (b.disabled = true));
}

async function streamChatMessage(message, threadId, handlers) {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ message, thread_id: threadId }),
  });

  if (res.status === 401) {
    if (await tryRefresh()) {
      return streamChatMessage(message, threadId, handlers);
    }
    handlers.onError("Session expired — please log in again.");
    setTimeout(logout, 1200);
    return;
  }
  if (res.status === 423) {
    handlers.onError("Account temporarily locked due to failed login attempts.");
    return;
  }
  if (res.status === 429) {
    handlers.onError("Rate or usage limit reached — try again shortly.");
    return;
  }
  if (!res.ok || !res.body) {
    handlers.onError("Something went wrong. Please try again.");
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      let eventType = "message";
      let dataLine = "";
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        if (line.startsWith("data:")) dataLine = line.slice(5).trim();
      }

      let data = {};
      try {
        data = JSON.parse(dataLine);
      } catch {
      }

      if (eventType === "token") handlers.onToken(data.content);
      else if (eventType === "interrupt") handlers.onInterrupt(data.prompt);
      else if (eventType === "done") handlers.onDone();
      else if (eventType === "error") handlers.onError(data.message);
    }
  }
}

composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message || !CURRENT_THREAD_ID) return;

  appendUserMessage(message);
  chatInput.value = "";
  chatInput.focus();

  const agentNode = appendStreamingAgentMessage();
  const bubble = agentNode.querySelector(".msg-bubble");
  let fullText = "";
  let gotAnyToken = false;

  await streamChatMessage(message, CURRENT_THREAD_ID, {
    onToken: (chunk) => {
      gotAnyToken = true;
      fullText += chunk;
      bubble.textContent = fullText;
      messageLog.scrollTop = messageLog.scrollHeight;
    },
    onInterrupt: (prompt) => {
      agentNode.remove();
      appendTicket(prompt);
    },
    onDone: () => {
      bubble.classList.remove("msg-bubble--streaming");
      loadThreads();
    },
    onError: (msg) => {
      bubble.classList.remove("msg-bubble--streaming");
      if (!gotAnyToken) bubble.textContent = msg;
    },
  });
});

async function resolveTicket(node, decision, prompt) {
  resolveTicketUI(node, decision);
  const typingNode = showTyping();

  const res = await authedFetch("/chat/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: CURRENT_THREAD_ID, decision, prompt }),
  });

  typingNode.remove();

  if (!res) return;
  if (res.status === 429) {
    appendSystemMessage("Rate or usage limit reached — try again shortly.");
    return;
  }
  if (!res.ok) {
    appendSystemMessage("Something went wrong finishing that request.");
    return;
  }

  const data = await res.json();
  appendAgentMessage(data.reply);
  loadThreads();
}

if (getToken()) {
  onAuthed(getToken(), getRefreshToken());
} else {
  showScreen("auth");
}