const STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired"];
const STAGE_COLORS = {
  Applied: "#7C8FA3",
  Screening: "#C9A227",
  Interview: "#3F6B8C",
  Offer: "#B5772E",
  Hired: "#3F5D45",
  Rejected: "#A6432B",
};

let boardData = {};       // stage -> [candidate]
let currentMatchIds = null; // Set of ids currently highlighted by search, or null
let openCandidateId = null;

const $ = (sel) => document.querySelector(sel);

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || "Something went wrong.");
    err.data = data;
    throw err;
  }
  return data;
}

function fmtDuration(days) {
  if (days < 1) {
    const hours = Math.round(days * 24);
    return hours <= 1 ? "less than an hour" : `${hours}h`;
  }
  const whole = Math.floor(days);
  return `${whole}d`;
}

function fmtTimestamp(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

// ------------------------------------------------------------------ board

async function loadBoard() {
  boardData = await api("/api/candidates");
  renderBoard();
}

function renderBoard() {
  const board = $("#board");
  board.innerHTML = "";

  STAGES.forEach((stage) => {
    const col = document.createElement("div");
    col.className = "column";
    col.style.setProperty("--stage-color", STAGE_COLORS[stage]);

    const allInStage = boardData[stage] || [];
    const visible = currentMatchIds
      ? allInStage.filter((c) => currentMatchIds.has(c.id))
      : allInStage;

    col.innerHTML = `
      <div class="column-header">
        <h2>${stage}</h2>
        <span class="column-count">${visible.length}</span>
      </div>
      <div class="column-body"></div>
    `;
    const body = col.querySelector(".column-body");

    if (visible.length === 0) {
      body.innerHTML = `<div class="column-empty">${currentMatchIds ? "No matches here." : "No one here yet."}</div>`;
    } else {
      visible.forEach((c) => body.appendChild(renderCard(c, stage)));
    }
    board.appendChild(col);
  });

  renderRejectedTray();
}

function renderCard(c, stage) {
  const card = document.createElement("div");
  card.className = "card";
  if (currentMatchIds && currentMatchIds.has(c.id)) card.classList.add("is-match");
  card.dataset.id = c.id;

  const canAdvance = stage !== "Hired" && stage !== "Rejected";
  card.innerHTML = `
    <div class="card-name">${escapeHtml(c.name)}</div>
    <div class="card-meta">${fmtDuration(c.days_in_stage)} in ${stage}</div>
    ${canAdvance ? `<div class="card-advance"><button class="chip-btn" data-advance="${c.id}">Advance →</button></div>` : ""}
  `;
  card.addEventListener("click", (e) => {
    if (e.target.closest("[data-advance]")) return;
    openDetail(c.id);
  });
  const advBtn = card.querySelector("[data-advance]");
  if (advBtn) {
    advBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await api(`/api/candidates/${c.id}/advance`, { method: "POST" });
        await loadBoard();
      } catch (err) {
        alert(err.message);
      }
    });
  }
  return card;
}

function renderRejectedTray() {
  const rejected = boardData["Rejected"] || [];
  const visible = currentMatchIds
    ? rejected.filter((c) => currentMatchIds.has(c.id))
    : rejected;
  $("#rejectedCount").textContent = `(${visible.length})`;
  const list = $("#rejectedList");
  list.innerHTML = "";
  visible.forEach((c) => list.appendChild(renderCard(c, "Rejected")));
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// ------------------------------------------------------------------ search

let searchDebounce = null;
$("#searchInput").addEventListener("input", (e) => {
  clearTimeout(searchDebounce);
  const q = e.target.value;
  $("#clearSearch").hidden = q.length === 0;
  searchDebounce = setTimeout(() => runSearch(q), 220);
});

$("#clearSearch").addEventListener("click", () => {
  $("#searchInput").value = "";
  $("#clearSearch").hidden = true;
  runSearch("");
});

async function runSearch(q) {
  if (!q.trim()) {
    currentMatchIds = null;
    $("#searchFeedback").hidden = true;
    renderBoard();
    return;
  }
  const useAi = $("#aiToggle").checked ? "&ai=1" : "";
  const data = await api(`/api/search?q=${encodeURIComponent(q)}${useAi}`);
  const feedback = $("#searchFeedback");

  if (!data.understood) {
    currentMatchIds = new Set();
    feedback.hidden = false;
    feedback.classList.add("is-error");
    feedback.textContent = data.errors[0];
    renderBoard();
    return;
  }

  feedback.classList.remove("is-error");
  if (data.results.length === 0) {
    feedback.hidden = false;
    feedback.textContent = data.errors[0] || "No matches.";
    currentMatchIds = new Set();
    renderBoard();
    return;
  } else if (data.explanation) {
    feedback.hidden = false;
    let text = (data.used_ai ? "✨ " : "") + data.explanation;
    if (data.notes && data.notes.length) text += " (" + data.notes.join(" ") + ")";
    feedback.textContent = text + ` — ${data.results.length} match${data.results.length === 1 ? "" : "es"}.`;
  } else {
    feedback.hidden = true;
  }

  currentMatchIds = new Set(data.results.map((r) => r.id));
  renderBoard();

  // if the match set is entirely rejected candidates, auto-open the tray
  if (data.results.length && data.results.every((r) => r.current_stage === "Rejected")) {
    $("#rejectedList").hidden = false;
  }
}

// ------------------------------------------------------------------ add candidate

$("#openAddBtn").addEventListener("click", () => {
  $("#newCandidateName").value = "";
  $("#addError").hidden = true;
  $("#addModal").hidden = false;
  $("#newCandidateName").focus();
});
$("#cancelAdd").addEventListener("click", () => ($("#addModal").hidden = true));
$("#addModal").addEventListener("click", (e) => {
  if (e.target === $("#addModal")) $("#addModal").hidden = true;
});
$("#confirmAdd").addEventListener("click", async () => {
  const name = $("#newCandidateName").value.trim();
  if (!name) {
    $("#addError").hidden = false;
    $("#addError").textContent = "Enter a name first.";
    return;
  }
  try {
    await api("/api/candidates", { method: "POST", body: JSON.stringify({ name }) });
    $("#addModal").hidden = true;
    await loadBoard();
  } catch (err) {
    $("#addError").hidden = false;
    $("#addError").textContent = err.message;
  }
});
$("#newCandidateName").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#confirmAdd").click();
});

// ------------------------------------------------------------------ detail modal

async function openDetail(id) {
  openCandidateId = id;
  const c = await api(`/api/candidates/${id}`);
  renderDetail(c);
  $("#detailModal").hidden = false;
}

function renderDetail(c) {
  $("#detailName").textContent = c.name;
  $("#detailStageInfo").textContent =
    `${c.current_stage} · ${fmtDuration(c.days_in_stage)} in this stage`;
  $("#detailError").hidden = true;

  const actions = $("#detailActions");
  actions.innerHTML = "";
  if (c.current_stage !== "Hired" && c.current_stage !== "Rejected") {
    const advBtn = document.createElement("button");
    advBtn.className = "btn-primary";
    advBtn.textContent = "Advance to next stage";
    advBtn.onclick = () => doTransition(c.id, "advance");
    actions.appendChild(advBtn);

    const rejBtn = document.createElement("button");
    rejBtn.className = "btn-ghost";
    rejBtn.textContent = "Reject candidate";
    rejBtn.onclick = () => doTransition(c.id, "reject");
    actions.appendChild(rejBtn);
  } else {
    const span = document.createElement("span");
    span.className = "card-meta";
    span.textContent = c.current_stage === "Hired"
      ? "Hired — final outcome, no further action."
      : "Rejected — final outcome, no further action.";
    actions.appendChild(span);
  }

  const list = $("#historyList");
  list.innerHTML = "";
  c.history.forEach((h) => {
    const li = document.createElement("li");
    if (h.to_stage === "Rejected") li.classList.add("is-rejected");
    if (h.to_stage === "Hired") li.classList.add("is-hired");
    const label = h.event_type === "created"
      ? "Entered the pipeline at Applied"
      : h.event_type === "rejected"
        ? `Rejected from ${h.from_stage}`
        : `Moved from ${h.from_stage} to ${h.to_stage}`;
    li.innerHTML = `
      <div class="history-line">${label}</div>
      <div class="history-time">${fmtTimestamp(h.at)}</div>
    `;
    list.appendChild(li);
  });
}

async function doTransition(id, kind) {
  try {
    const updated = await api(`/api/candidates/${id}/${kind}`, { method: "POST" });
    renderDetail(updated);
    await loadBoard();
  } catch (err) {
    $("#detailError").hidden = false;
    $("#detailError").textContent = err.message;
  }
}

$("#closeDetail").addEventListener("click", () => ($("#detailModal").hidden = true));
$("#detailModal").addEventListener("click", (e) => {
  if (e.target === $("#detailModal")) $("#detailModal").hidden = true;
});

$("#toggleRejected").addEventListener("click", () => {
  const list = $("#rejectedList");
  list.hidden = !list.hidden;
});

$("#aiToggle").addEventListener("change", () => {
  const q = $("#searchInput").value;
  if (q.trim()) runSearch(q);
});

// ------------------------------------------------------------------ init

async function checkAiAvailability() {
  try {
    const status = await api("/api/ai-status");
    $("#aiToggleWrap").hidden = !status.available;
  } catch {
    $("#aiToggleWrap").hidden = true;
  }
}

loadBoard();
checkAiAvailability();
