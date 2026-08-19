function loadSavedMessages() {
  try {
    return JSON.parse(localStorage.getItem("housing-generated-messages") ?? "{}") ?? {};
  } catch {
    return {};
  }
}

function saveMessages(messages) {
  localStorage.setItem("housing-generated-messages", JSON.stringify(messages));
}

const state = {
  properties: [],
  search: "",
  maxRent: Infinity,
  showHandled: false,
  resultTab: "couples",
  sortOrder: "recent",
  processStatuses: new Set(),
  messages: loadSavedMessages(),
};

const elements = {
  fresh: document.querySelector("#new-results"),
  process: document.querySelector("#process-results"),
  handled: document.querySelector("#handled-results"),
  handledSection: document.querySelector("#handled-section"),
  error: document.querySelector("#error"),
  toast: document.querySelector("#toast"),
  messageDialog: document.querySelector("#message-dialog"),
  generatedMessage: document.querySelector("#generated-message"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatSource(source) {
  return {
    dailyinfo: "Daily Info",
    finders: "Finders",
    onthemarket: "OnTheMarket",
    rightmove: "Rightmove",
    scottfraser: "Scott Fraser",
    taylors: "Taylors",
    spareroom: "SpareRoom",
  }[source] ?? source;
}

function fact(value, suffix) {
  return Number.isFinite(value) ? `<span>${escapeHtml(value)} ${suffix}</span>` : "";
}

const SHORTLIST_STATUSES = new Set([
  "in_process",
  "contacted",
  "viewing_confirmed",
  "waiting_for_selection",
]);

function archivedLabel(property) {
  const value = property.archived ?? property.first_qualified_at;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "";
  return `Archived ${new Date(timestamp).toLocaleString("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  })}`;
}

function sortProperties(properties) {
  return properties.sort((a, b) => {
    if (state.sortOrder === "rent") return a.rent - b.rent || a.id.localeCompare(b.id);
    const recent = Date.parse(b.archived ?? b.first_qualified_at) - Date.parse(a.archived ?? a.first_qualified_at);
    return (Number.isFinite(recent) && recent !== 0) ? recent : a.rent - b.rent;
  });
}

const STAGE_LABELS = {
  in_process: "In process",
  contacted: "Contacted",
  viewing_confirmed: "Viewing confirmed",
  waiting_for_selection: "Waiting for selection",
  failed: "Failed",
};

function actions(property) {
  const viewMessage = state.messages[property.id]
    ? `<button class="message-view" data-view-message title="View generated message" aria-label="View generated message">👁</button>`
    : "";
  if (SHORTLIST_STATUSES.has(property.status)) {
    const options = Object.entries(STAGE_LABELS)
      .map(([value, label]) => `
        <option value="${value}" ${property.status === value ? "selected" : ""}>
          ${label}
        </option>`)
      .join("");
    return `
      <label class="stage-select ${property.status}">
        <span>Stage</span>
        <select data-stage>${options}</select>
      </label>
      <button class="danger" data-status="ignored">Ignore</button>
      <button data-status="new">Return</button>
      <button data-message>Message</button>
      ${viewMessage}
    `;
  }
  if (property.status === "ignored" || property.status === "failed") {
    return `
      <button class="primary" data-status="new">Restore</button>
      <button data-message>Message</button>
    `;
  }
  return `
    <button class="danger" data-status="ignored">Ignore</button>
    <button class="primary" data-status="in_process">Shortlist</button>
    <button data-message>Message</button>
  `;
}

function propertyCard(property) {
  const article = document.createElement("article");
  article.className = "property-card";
  article.dataset.id = property.id;
  article.innerHTML = `
    <div class="card-topline">
      <strong class="rent">£${Number(property.rent).toLocaleString("en-GB")} <small>pcm</small></strong>
      <span class="source">${escapeHtml(formatSource(property.source))}</span>
    </div>
    <p class="address">${escapeHtml(property.address)}</p>
    <div class="property-facts">
      ${fact(property.bike_minutes, "min cycle")}
      ${fact(property.bike_distance_km, "km")}
      ${archivedLabel(property) ? `<span>${escapeHtml(archivedLabel(property))}</span>` : ""}
      ${property.couples_supported ? "<span>Couples supported</span>" : ""}
      ${property.self_contained ? "<span>Self-contained</span>" : ""}
    </div>
    <p class="description">${escapeHtml(property.description)}</p>
    <div class="card-actions">
      <a href="${escapeHtml(property.link)}" target="_blank" rel="noopener noreferrer">Advert ↗</a>
      ${actions(property)}
    </div>
    ${SHORTLIST_STATUSES.has(property.status) ? `
      <label class="property-note">
        <span>Shared note</span>
        <textarea data-note rows="1" maxlength="2000" placeholder="Add a note…">${escapeHtml(property.note)}</textarea>
      </label>` : ""}
  `;
  article.querySelectorAll("[data-status]").forEach((button) => {
    button.addEventListener("click", () => updateStatus(property.id, button.dataset.status, button));
  });
  article.querySelector("[data-stage]")?.addEventListener("change", (event) => {
    updateStatus(property.id, event.target.value, event.target);
  });
  article.querySelector("[data-view-message]")?.addEventListener("click", () => {
    openMessage(property.id);
  });
  const note = article.querySelector("[data-note]");
  if (note) {
    expandNote(note);
    note.addEventListener("input", () => {
      property.note = note.value;
      expandNote(note);
      queueNoteSave(property.id, note.value);
    });
  }
  article.querySelector("[data-message]")?.addEventListener("click", (event) => {
    generateMessage(property.id, event.currentTarget);
  });
  return article;
}

function visibleProperties() {
  const query = state.search.toLowerCase();
  return state.properties.filter((property) => {
    if (property.rent > state.maxRent) return false;
    if (!query) return true;
    return [property.address, property.description, property.source]
      .some((value) => String(value ?? "").toLowerCase().includes(query));
  });
}

function fill(container, properties, emptyMessage) {
  container.replaceChildren();
  if (!properties.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = emptyMessage;
    container.append(empty);
    return;
  }
  properties.forEach((property) => container.append(propertyCard(property)));
}

function render() {
  const properties = sortProperties(visibleProperties());
  const fresh = properties.filter((property) => property.status === "new");
  const couples = fresh.filter((property) => property.couples_supported);
  const selfContained = fresh.filter(
    (property) => !property.couples_supported && property.self_contained,
  );
  const process = properties.filter((property) =>
    SHORTLIST_STATUSES.has(property.status) &&
    (!state.processStatuses.size || state.processStatuses.has(property.status))
  );
  const handled = properties.filter((property) => ["ignored", "failed"].includes(property.status));
  const selectedResults = state.resultTab === "couples" ? couples : selfContained;
  const emptyMessage = state.resultTab === "couples"
    ? "No new couples-supported properties."
    : "No new self-contained properties.";

  fill(elements.fresh, selectedResults, emptyMessage);
  fill(elements.process, process, "No shortlisted properties match these statuses.");
  fill(elements.handled, handled, "No ignored or failed properties.");

  document.querySelector("#couples-count").textContent = couples.length;
  document.querySelector("#self-contained-count").textContent = selfContained.length;
  document.querySelector("#process-count").textContent = process.length;
  document.querySelector("#handled-count").textContent = handled.length;
  document.querySelectorAll("[data-result-tab]").forEach((tab) => {
    const active = tab.dataset.resultTab === state.resultTab;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  elements.handledSection.classList.toggle("hidden", !state.showHandled);
}

const noteTimers = new Map();

function expandNote(note) {
  note.style.height = "auto";
  note.style.height = `${note.scrollHeight}px`;
}

function queueNoteSave(id, note) {
  clearTimeout(noteTimers.get(id));
  noteTimers.set(id, setTimeout(() => saveNote(id, note), 600));
}

async function saveNote(id, note) {
  try {
    const response = await fetch(`/api/properties/${encodeURIComponent(id)}/note`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ note }),
    });
    if (!response.ok) throw new Error("Note save failed");
  } catch {
    showError("The note could not be saved. Please try again.");
  }
}

async function updateStatus(id, status, button) {
  button.disabled = true;
  try {
    const response = await fetch(`/api/properties/${encodeURIComponent(id)}/status`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!response.ok) throw new Error("Status update failed");
    const property = state.properties.find((item) => item.id === id);
    property.status = status;
    render();
    showToast("Status updated.");
  } catch {
    button.disabled = false;
    showError("The status could not be saved. Please try again.");
  }
}

function openMessage(id) {
  const message = state.messages[id];
  if (!message) return;
  elements.generatedMessage.value = message;
  elements.messageDialog.showModal();
}

async function generateMessage(id, button) {
  button.disabled = true;
  const label = button.textContent;
  button.textContent = "Writing…";
  try {
    const response = await fetch(`/api/properties/${encodeURIComponent(id)}/message`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error ?? "Message generation failed");
    state.messages[id] = data.message;
    saveMessages(state.messages);
    render();
    openMessage(id);
  } catch (error) {
    showError(error.message || "The message could not be generated. Please try again.");
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.classList.remove("hidden");
}

let toastTimer;
function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.remove("hidden");
  toastTimer = setTimeout(() => elements.toast.classList.add("hidden"), 2800);
}

async function loadProperties() {
  try {
    const response = await fetch("/api/properties");
    if (!response.ok) throw new Error("Properties request failed");
    const data = await response.json();
    state.properties = data.properties;
    document.querySelector("#snapshot-time").textContent =
      `Updated ${new Date(data.generated_at).toLocaleString("en-GB", {
        dateStyle: "medium",
        timeStyle: "short",
      })}`;
    render();
  } catch {
    showError("The latest housing results could not be loaded.");
  }
}

document.querySelector("#search").addEventListener("input", (event) => {
  state.search = event.target.value.trim();
  render();
});

document.querySelector("#rent-filter").addEventListener("change", (event) => {
  state.maxRent = Number(event.target.value);
  render();
});

document.querySelector("#sort-order").addEventListener("change", (event) => {
  state.sortOrder = event.target.value;
  render();
});

document.querySelectorAll("[data-process-status]").forEach((checkbox) => {
  checkbox.addEventListener("change", () => {
    state.processStatuses = new Set(
      [...document.querySelectorAll("[data-process-status]:checked")]
        .map((item) => item.value),
    );
    render();
  });
});

document.querySelectorAll("[data-result-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.resultTab = tab.dataset.resultTab;
    render();
  });
});

document.querySelector("#show-handled").addEventListener("click", (event) => {
  state.showHandled = !state.showHandled;
  event.currentTarget.textContent = state.showHandled ? "Hide history" : "Show history";
  render();
});

loadProperties();

document.querySelector("#copy-message").addEventListener("click", async () => {
  await navigator.clipboard.writeText(elements.generatedMessage.value);
  showToast("Message copied.");
});
