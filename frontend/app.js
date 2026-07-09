const API_BASE = "http://localhost:8000";
const THREAD_ID = "thread-" + Math.random().toString(36).slice(2, 10);

const el = (id) => document.getElementById(id);
const authScreen = el("auth-screen");
const chatScreen = el("chat-screen");
const messageLog = el("message-log");
const authForm = el("auth-form");
const authError = el("auth-error");
const composer = el("composer");
const chatInput = el("chat-input");

let pendingTicketEl = null;

function getToken() {
  return localStorage.getItem("token");
}

function setToken(token) {
  localStorage.setItem("token", token);
}

function clearToken() {
  localStorage.removeItem("token");
}

// ---------- Auth ----------

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
  onAuthed(data.access_token);
}

async function login(email, password) {
  const body = new URLSearchParams({ username: email, password });
  const data = await authRequest("/auth/login", body, true);
  onAuthed(data.access_token);
}

function onAuthed(token) {
  setToken(token);
  authScreen.hidden = true;
  chatScreen.hidden = false;
  el("thread-id-display").textContent = THREAD_ID;
  chatInput.focus();
}

function logout() {
  clearToken();
  chatScreen.hidden = true;
  authScreen.hidden = false;
  messageLog.innerHTML = "";
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

// ---------- Message rendering ----------

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

function showTyping() {
  return appendFromTemplate("tpl-typing");
}

function appendTicket(prompt) {
  const node = appendFromTemplate("tpl-ticket");
  node.querySelector(".ticket-prompt").textContent = prompt;
  node.querySelectorAll("[data-decision]").forEach((btn) => {
    btn.addEventListener("click", () => resolveTicket(node, btn.dataset.decision));
  });
  pendingTicketEl = node;
  return node;
}

function resolveTicketUI(node, decision) {
  node.classList.add("ticket--resolved");
  node.querySelector(".ticket-flag").textContent =
    decision === "yes" ? "◆ APPROVED" : "◆ DECLINED";
  node.querySelectorAll("button").forEach((b) => (b.disabled = true));
}

// ---------- Chat ----------

async function chatRequest(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify(body),
  });

  if (res.status === 401) {
    appendSystemMessage("Session expired — please log in again.");
    setTimeout(logout, 1200);
    return null;
  }
  if (res.status === 429) {
    appendSystemMessage("Rate or usage limit reached — try again shortly.");
    return null;
  }
  return res.json();
}

function handleChatResponse(data) {
  if (!data) return;
  if (data.status === "pending_approval") {
    appendTicket(data.prompt);
    return;
  }
  appendAgentMessage(data.reply);
}

composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  appendUserMessage(message);
  chatInput.value = "";
  chatInput.focus();

  const typingNode = showTyping();
  const data = await chatRequest("/chat", { message, thread_id: THREAD_ID });
  typingNode.remove();
  handleChatResponse(data);
});

async function resolveTicket(node, decision) {
  resolveTicketUI(node, decision);
  const typingNode = showTyping();
  const data = await chatRequest("/chat/resume", { thread_id: THREAD_ID, decision });
  typingNode.remove();
  handleChatResponse(data);
}

// ---------- Boot ----------

if (getToken()) {
  onAuthed(getToken());
}
