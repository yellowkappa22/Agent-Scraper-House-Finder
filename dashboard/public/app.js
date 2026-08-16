const state = {
  properties: [],
  search: "",
  maxRent: Infinity,
  showHandled: false,
  resultTab: "couples",
};

const elements = {
  fresh: document.querySelector("#new-results"),
  process: document.querySelector("#process-results"),
  handled: document.querySelector("#handled-results"),
  handledSection: document.querySelector("#handled-section"),
  error: document.querySelector("#error"),
  toast: document.querySelector("#toast"),
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

const STAGE_LABELS = {
  in_process: "In process",
  contacted: "Contacted",
  viewing_confirmed: "Viewing confirmed",
  waiting_for_selection: "Waiting for selection",
  failed: "Failed",
};

function actions(property) {
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
      ${property.couples_supported ? "<span>Couples supported</span>" : ""}
      ${property.self_contained ? "<span>Self-contained</span>" : ""}
    </div>
    <p class="description">${escapeHtml(property.description)}</p>
    <div class="card-actions">
      <a href="${escapeHtml(property.link)}" target="_blank" rel="noopener noreferrer">Advert ↗</a>
      ${actions(property)}
    </div>
  `;
  article.querySelectorAll("[data-status]").forEach((button) => {
    button.addEventListener("click", () => updateStatus(property.id, button.dataset.status, button));
  });
  article.querySelector("[data-stage]")?.addEventListener("change", (event) => {
    updateStatus(property.id, event.target.value, event.target);
  });
  article.querySelector("[data-message]")?.addEventListener("click", () => {
    showToast("Message generation will be connected in a later step.");
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
  const properties = visibleProperties().sort((a, b) => a.rent - b.rent || a.id.localeCompare(b.id));
  const fresh = properties.filter((property) => property.status === "new");
  const couples = fresh.filter((property) => property.couples_supported);
  const selfContained = fresh.filter(
    (property) => !property.couples_supported && property.self_contained,
  );
  const process = properties.filter((property) =>
    SHORTLIST_STATUSES.has(property.status)
  );
  const handled = properties.filter((property) => ["ignored", "failed"].includes(property.status));
  const selectedResults = state.resultTab === "couples" ? couples : selfContained;
  const emptyMessage = state.resultTab === "couples"
    ? "No new couples-supported properties."
    : "No new self-contained properties.";

  fill(elements.fresh, selectedResults, emptyMessage);
  fill(elements.process, process, "Move a property here when you want to pursue it.");
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
