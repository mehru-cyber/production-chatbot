const API_BASE = "http://localhost:8000";
const THREADS_KEY = "sa_threads"; // [{id, title, pinned, updatedAt}]

const el = (id) => document.getElementById(id);
const authScreen = el("auth-screen");
const appShell = el("app-shell");
const authForm = el("auth-form");
const authError = el("auth-error");
const messageLog = el("message-log");
const composer = el("composer");
const chatInput = el("chat-input");
const sidebar = el("sidebar");
const currentThreadTitle = el("current-thread-title");
const pinnedList = el("pinned-list");
const recentList = el("recent-list");

let currentThreadId = null;

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
  appShell.hidden = false;
  renderThreadList();
  startNewChat();
}

function logout() {
  clearToken();
  appShell.hidden = true;
  authScreen.hidden = false;
  messageLog.innerHTML = "";
  authForm.reset();
  currentThreadId = null;
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

// ---------- Thread list (sidebar) ----------

function loadThreads() {
  try {
    return JSON.parse(localStorage.getItem(THREADS_KEY)) || [];
  } catch {
    return [];
  }
}

function saveThreads(threads) {
  localStorage.setItem(THREADS_KEY, JSON.stringify(threads));
}

function upsertThread(id, patch) {
  const threads = loadThreads();
  const idx = threads.findIndex((t) => t.id === id);
  if (idx === -1) {
    threads.push({ id, title: "New chat", pinned: false, updatedAt: Date.now(), ...patch });
  } else {
    threads[idx] = { ...threads[idx], ...patch, updatedAt: Date.now() };
  }
  saveThreads(threads);
  renderThreadList();
}

function togglePin(id) {
  const threads = loadThreads();
  const t = threads.find((t) => t.id === id);
  if (t) t.pinned = !t.pinned;
  saveThreads(threads);
  renderThreadList();
}

function renderThreadList() {
  const threads = loadThreads().sort((a, b) => b.updatedAt - a.updatedAt);
  const pinned = threads.filter((t) => t.pinned);
  const recent = threads.filter((t) => !t.pinned);

  pinnedList.innerHTML = "";
  recentList.innerHTML = "";

  pinned.forEach((t) => pinnedList.appendChild(buildThreadItem(t)));
  recent.forEach((t) => recentList.appendChild(buildThreadItem(t)));
}

function buildThreadItem(thread) {
  const tpl = document.getElementById("tpl-thread-item");
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.querySelector(".thread-title").textContent = thread.title;
  node.classList.toggle("thread-item--active", thread.id === currentThreadId);

  const pinBtn = node.querySelector(".pin-btn");
  pinBtn.textContent = thread.pinned ? "★" : "☆";
  pinBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    togglePin(thread.id);
  });

  node.addEventListener("click", () => switchThread(thread.id, thread.title));
  return node;
}

function switchThread(id, title) {
  currentThreadId = id;
  currentThreadTitle.textContent = title;
  messageLog.innerHTML = "";
  appendSystemMessage("Switched thread.");
  renderThreadList();
  closeSidebarMobile();
}

function startNewChat() {
  const id = "thread-" + Math.random().toString(36).slice(2, 10);
  currentThreadId = id;
  currentThreadTitle.textContent = "New chat";
  messageLog.innerHTML = "";
  upsertThread(id, { title: "New chat" });
  closeSidebarMobile();
}
el("new-chat-btn").addEventListener("click", startNewChat);

// ---------- Mobile sidebar toggle ----------

el("sidebar-open-btn").addEventListener("click", () => sidebar.classList.add("sidebar--open"));
el("sidebar-close-btn").addEventListener("click", () => sidebar.classList.remove("sidebar--open"));
function closeSidebarMobile() {
  sidebar.classList.remove("sidebar--open");
}

// ---------- Message rendering ----------

function appendFromTemplate(templateId) {
  const tpl = document.getElementById(templateId);
  const node = tpl.content.firstElementChild.cloneNode(true);
  messageLog.appendChild(node);
  messageLog.scrollTop = messageLog.scrollHeight;
  return node;
}

function appendUserMessage(text) {
  appendFromTemplate("tpl-message-user").querySelector(".msg-bubble").textContent = text;
}

function appendAgentMessage(text) {
  appendFromTemplate("tpl-message-agent").querySelector(".msg-bubble").textContent = text;
}

function appendSystemMessage(text) {
  appendFromTemplate("tpl-message-system").querySelector(".msg-bubble").textContent = text;
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
  return node;
}

function resolveTicketUI(node, decision) {
  node.classList.add("ticket--resolved");
  node.querySelector(".ticket-flag").textContent = decision === "yes" ? "◆ APPROVED" : "◆ DECLINED";
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

  if (!currentThreadId) startNewChat();

  const threads = loadThreads();
  const thread = threads.find((t) => t.id === currentThreadId);
  if (thread && thread.title === "New chat") {
    const title = message.length > 40 ? message.slice(0, 40) + "…" : message;
    upsertThread(currentThreadId, { title });
    currentThreadTitle.textContent = title;
  } else {
    upsertThread(currentThreadId, {});
  }

  appendUserMessage(message);
  chatInput.value = "";
  chatInput.focus();

  const typingNode = showTyping();
  const data = await chatRequest("/chat", { message, thread_id: currentThreadId });
  typingNode.remove();
  handleChatResponse(data);
});

async function resolveTicket(node, decision) {
  resolveTicketUI(node, decision);
  const typingNode = showTyping();
  const data = await chatRequest("/chat/resume", { thread_id: currentThreadId, decision });
  typingNode.remove();
  handleChatResponse(data);
}

// ---------- Boot ----------

if (getToken()) {
  authScreen.hidden = true;
  appShell.hidden = false;
  renderThreadList();
  startNewChat();
}