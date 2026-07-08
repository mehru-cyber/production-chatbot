const API_BASE = "http://localhost:8000";
const THREAD_ID = "thread-" + Math.random().toString(36).slice(2);

function getToken() {
  return localStorage.getItem("token");
}

async function register() {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) return showAuthError(await res.text());
  const data = await res.json();
  onAuthed(data.access_token);
}

async function login() {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) return showAuthError(await res.text());
  const data = await res.json();
  onAuthed(data.access_token);
}

function showAuthError(msg) {
  document.getElementById("auth-error").textContent = msg;
}

function onAuthed(token) {
  localStorage.setItem("token", token);
  document.getElementById("auth-view").style.display = "none";
  document.getElementById("chat-view").style.display = "block";
}

function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = `${role}: ${text}`;
  document.getElementById("messages").appendChild(div);
}

async function sendMessage() {
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;
  appendMessage("you", message);
  input.value = "";

  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ message, thread_id: THREAD_ID }),
  });

  if (res.status === 429) {
    appendMessage("system", "Rate or usage limit hit — try again shortly.");
    return;
  }

  const data = await res.json();
  handleChatResponse(data);
}

async function respondApproval(decision) {
  document.getElementById("approval").style.display = "none";
  appendMessage("you", decision);

  const res = await fetch(`${API_BASE}/chat/resume`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ thread_id: THREAD_ID, decision }),
  });
  const data = await res.json();
  handleChatResponse(data);
}

function handleChatResponse(data) {
  if (data.status === "pending_approval") {
    document.getElementById("approval-prompt").textContent = data.prompt;
    document.getElementById("approval").style.display = "block";
    return;
  }
  appendMessage("bot", data.reply);
}

if (getToken()) onAuthed(getToken());
