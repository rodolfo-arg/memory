function ensureElement(id, tagName) {
  const existing = document.getElementById(id);
  if (existing) return existing;
  const created = document.createElement(tagName);
  created.id = id;
  created.setAttribute("data-fallback", "1");
  created.style.display = "none";
  document.body.appendChild(created);
  return created;
}

function ensureInput(id, type, fallbackValue) {
  const el = ensureElement(id, "input");
  if (!el.getAttribute("type")) el.setAttribute("type", type);
  if (type === "checkbox") {
    if (el.getAttribute("data-fallback") === "1" && typeof fallbackValue === "boolean") {
      el.checked = fallbackValue;
    } else if (typeof el.checked !== "boolean") {
      el.checked = Boolean(fallbackValue);
    }
  } else if ((el.value == null || el.value === "") && fallbackValue != null) {
    el.value = String(fallbackValue);
  }
  return el;
}

function ensureButton(id) {
  return ensureElement(id, "button");
}

function ensureSelect(id, fallbackValue) {
  const el = ensureElement(id, "select");
  if (!el.options.length && fallbackValue != null) {
    const opt = document.createElement("option");
    opt.value = String(fallbackValue);
    opt.textContent = String(fallbackValue);
    el.appendChild(opt);
  }
  return el;
}

function ensureSelectOption(el, value, label) {
  const exists = Array.from(el.options || []).some((opt) => opt.value === value);
  if (exists) return;
  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = label;
  el.appendChild(opt);
}

const statusEl = document.getElementById("status");
const overlayEl = document.getElementById("overlay");
const overlayTitleEl = document.getElementById("overlayTitle");
const overlayBodyEl = document.getElementById("overlayBody");
const detailsEl = document.getElementById("details");
const errorEl = document.getElementById("error");
const loadBtn = document.getElementById("loadBtn");
const collapseBtn = document.getElementById("collapseBtn");
const expandAllBtn = document.getElementById("expandAllBtn");
const fitBtn = document.getElementById("fitBtn");
const projectEl = document.getElementById("projectId");
const maxConversationsEl = document.getElementById("maxConversations");
const maxChunksEl = document.getElementById("maxChunks");
const maxFactsEl = document.getElementById("maxFacts");
const includeArchivedEl = document.getElementById("includeArchived");
const renderModeEl = document.getElementById("renderMode");
const displayModeEl = ensureSelect("displayMode", "graph");
const liveModeEl = document.getElementById("liveMode");
const liveEverySecEl = document.getElementById("liveEverySec");
const searchInputEl = ensureInput("searchInput", "search", "");
const searchPrevBtn = ensureButton("searchPrevBtn");
const searchNextBtn = ensureButton("searchNextBtn");
const searchClearBtn = ensureButton("searchClearBtn");
const searchMetaEl = ensureElement("searchMeta", "div");
const showConversationsEl = ensureInput("showConversations", "checkbox", true);
const showChunksEl = ensureInput("showChunks", "checkbox", true);
const showFactsEl = ensureInput("showFacts", "checkbox", true);
const minImportanceEl = ensureInput("minImportance", "number", "");
const minConfidenceEl = ensureInput("minConfidence", "number", "");
const createdAfterEl = ensureInput("createdAfter", "date", "");
const viewPresetSelectEl = ensureSelect("viewPresetSelect");
const applyViewBtn = ensureButton("applyViewBtn");
const saveViewBtn = ensureButton("saveViewBtn");
const deleteViewBtn = ensureButton("deleteViewBtn");
const kpiNodesEl = document.getElementById("kpiNodes");
const kpiEdgesEl = document.getElementById("kpiEdges");
const kpiConversationsEl = document.getElementById("kpiConversations");
const kpiChunksEl = document.getElementById("kpiChunks");
const kpiFactsEl = document.getElementById("kpiFacts");
const kpiModeEl = document.getElementById("kpiMode");
const kpiLiveEl = document.getElementById("kpiLive");
const kpiUpdatedEl = document.getElementById("kpiUpdated");
const graphEl = document.getElementById("graph");
const inspectorEl = document.getElementById("drawer");
const currentProjectEl = ensureElement("currentProject", "div");
const graphViewBtn = ensureButton("graphViewBtn");
const listViewBtn = ensureButton("listViewBtn");
const timelineViewEl = ensureElement("timelineView", "section");
const timelineMetaEl = ensureElement("timelineMeta", "div");
const timelineListEl = ensureElement("timelineList", "div");
const timelineSortEl = ensureSelect("timelineSort", "desc");
ensureSelectOption(displayModeEl, "graph", "graph");
ensureSelectOption(displayModeEl, "list", "timeline");
ensureSelectOption(timelineSortEl, "desc", "Newest");
ensureSelectOption(timelineSortEl, "asc", "Oldest");

const COLORS = {
  project: "#89b8ff",
  conversation: "#65d3bb",
  chunk: "#eb8bb6",
  fact: "#ffd27b",
  dim: "rgba(90,104,120,0.22)"
};
const SIZE = {
  project: 8,
  conversation: 3.6,
  chunk: 2.0,
  fact: 2.2
};
const VIEW_PRESETS_KEY = "memoryGraphViewPresets.v1";
const CLIENT_FILTER_STATE_KEY = "memoryGraphClientFilters.v1";
const TIMELINE_SORT_KEY = "memoryGraphTimelineSort";

let graph = null;
let graphMode = "3d";
let rawPayload = null;
let rawNodes = [];
let rawLinks = [];
let nodesById = new Map();
let adjacency = new Map();
let conversationMetricsById = new Map();
let expandedNodes = new Set(["project"]);
let baseVisibleNodes = new Set(["project"]);
let selectedNodeId = null;
let currentData = { nodes: [], links: [] };
let nodeState = new Map();
let highlightedNodes = new Set();
let highlightedLinks = new Set();
let graphLoadInFlight = false;
let liveLoopTimer = null;
let lastLoadedAt = null;
let lastPayloadSignature = "";
let lastPayloadDelta = null;
let storageAvailable = true;
let recoveringFrom3DError = false;
let searchMatches = [];
let searchMatchIndex = -1;
let viewPresets = [];
let timelineExpandedIds = new Set();
let timelineRenderSignature = "";
let graphResizeRaf = null;
let timelineApp = null;
const TIMELINE_ITEM_TEMPLATE_VERSION = "20260218k";

function normalizeTimelineSort(value) {
  const normalized = String(value == null ? "" : value).trim().toLowerCase();
  return normalized === "asc" ? "asc" : "desc";
}

function setListSortFromUi(value) {
  const next = normalizeTimelineSort(value);
  timelineSortEl.value = next;
  setStorageItem(TIMELINE_SORT_KEY, next);
  if (activeDisplayMode() === "list") {
    renderTimelineView({ force: true });
  }
}

function setListSearchFromUi(value) {
  searchInputEl.value = String(value == null ? "" : value);
  if (activeDisplayMode() === "list") {
    renderTimelineView({ force: true });
    updateSearchMeta();
    return;
  }
  rebuildSearchMatches({ preserveCurrent: true, autoFocus: false });
}

function setListFiltersFromUi(filters) {
  const next = filters && typeof filters === "object" ? filters : {};
  if (typeof next.showConversations === "boolean") {
    showConversationsEl.checked = next.showConversations;
  }
  if (typeof next.showChunks === "boolean") {
    showChunksEl.checked = next.showChunks;
  }
  if (typeof next.showFacts === "boolean") {
    showFactsEl.checked = next.showFacts;
  }
  if (Object.prototype.hasOwnProperty.call(next, "minImportance")) {
    minImportanceEl.value = next.minImportance == null ? "" : String(next.minImportance);
    normalizeThresholdInput(minImportanceEl);
  }
  if (Object.prototype.hasOwnProperty.call(next, "minConfidence")) {
    minConfidenceEl.value = next.minConfidence == null ? "" : String(next.minConfidence);
    normalizeThresholdInput(minConfidenceEl);
  }
  if (Object.prototype.hasOwnProperty.call(next, "createdAfter")) {
    createdAfterEl.value = String(next.createdAfter || "");
  }
  refreshAfterClientFilterChange("list-filter");
}

function openNodeFromTimeline(nodeId) {
  const targetId = normalizeNodeId(nodeId);
  if (!targetId) return;
  if (!graph) createGraphInstance();
  displayModeEl.value = "graph";
  setStorageItem("memoryGraphDisplayMode", "graph");
  applyDisplayModeUi();
  refreshGraph({ reason: "timelineFocus", anchorId: targetId });
}

function toggleTimelineExpanded(nodeId) {
  const targetId = normalizeNodeId(nodeId);
  if (!targetId) return;
  if (timelineExpandedIds.has(targetId)) {
    timelineExpandedIds.delete(targetId);
  } else {
    timelineExpandedIds.add(targetId);
  }
  renderTimelineView({ force: true });
}

function timelineUiItemPayload(item) {
  const node = item.node || {};
  const nodeId = normalizeNodeId(node.id);
  const ts = item.ts;
  const kind = String(node.kind || "");
  const label = String(node.label || nodeId || "(memory)").trim();
  const rawNote = textSnippet(node.text || "", 240);
  const note = rawNote && rawNote !== label ? rawNote : "";
  const metaBits = [];
  if (node.conversation_id) metaBits.push("conv=" + node.conversation_id);
  if (node.chunk_type) metaBits.push("type=" + node.chunk_type);
  if (node.importance != null) metaBits.push("imp=" + node.importance);
  if (node.confidence != null) metaBits.push("conf=" + node.confidence);
  if (node.archived) metaBits.push("archived=1");
  if (node.created_at) metaBits.push("at=" + node.created_at);

  return {
    id: nodeId,
    kind,
    label,
    note,
    fullText: String(node.text || "").trim(),
    timeLabel: ts != null ? new Date(ts).toLocaleTimeString() : "--",
    dayLabel: ts != null ? new Date(ts).toLocaleDateString() : "No timestamp",
    metaRows: timelineMetaRows(node),
    metaBits,
    expanded: timelineExpandedIds.has(nodeId),
    createdAt: node.created_at || "",
    timestamp: ts
  };
}

function ensureTimelineApp() {
  if (timelineApp) return timelineApp;
  if (
    !window.MemoryGraphListApp ||
    typeof window.MemoryGraphListApp.mount !== "function" ||
    !timelineViewEl
  ) {
    return null;
  }

  try {
    timelineApp = window.MemoryGraphListApp.mount({
      mountEl: timelineViewEl,
      onSortChange: (value) => setListSortFromUi(value),
      onSearchChange: (value) => setListSearchFromUi(value),
      onFiltersChange: (filters) => setListFiltersFromUi(filters),
      onToggleExpand: (nodeId) => toggleTimelineExpanded(nodeId),
      onOpenGraph: (nodeId) => openNodeFromTimeline(nodeId),
      onLoad: async () => {
        await loadGraph({ reason: "load", preserveState: false });
        if (liveModeEl.checked) startLiveLoop();
      }
    });
  } catch (err) {
    setError("Reactive list failed to mount: " + String(err));
    timelineApp = null;
  }
  return timelineApp;
}

function setStatus(text) {
  statusEl.textContent = text;
}

function setError(text) {
  errorEl.textContent = text || "";
}

function getStorageItem(key) {
  if (!storageAvailable) return null;
  try {
    return window.localStorage.getItem(key);
  } catch (_err) {
    storageAvailable = false;
    return null;
  }
}

function setStorageItem(key, value) {
  if (!storageAvailable) return;
  try {
    window.localStorage.setItem(key, value);
  } catch (_err) {
    storageAvailable = false;
  }
}

function parseJson(value, fallback) {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch (_err) {
    return fallback;
  }
}

function toThreshold(value) {
  const text = String(value == null ? "" : value).trim();
  if (!text) return null;
  const parsed = Number(text);
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(1, parsed));
}

function normalizeThresholdInput(inputEl) {
  const value = toThreshold(inputEl.value);
  if (value === null) {
    inputEl.value = "";
    return;
  }
  inputEl.value = String(Math.round(value * 100) / 100);
}

function readClientFilterState() {
  const createdAfter = String(createdAfterEl.value || "").trim();
  let createdAfterTs = null;
  if (createdAfter) {
    const parsedTs = Date.parse(createdAfter + "T00:00:00");
    if (Number.isFinite(parsedTs)) createdAfterTs = parsedTs;
  }
  return {
    showConversations: showConversationsEl.checked,
    showChunks: showChunksEl.checked,
    showFacts: showFactsEl.checked,
    minImportance: toThreshold(minImportanceEl.value),
    minConfidence: toThreshold(minConfidenceEl.value),
    createdAfter,
    createdAfterTs
  };
}

function applyClientFilterState(state) {
  const next = state || {};
  showConversationsEl.checked = next.showConversations !== false;
  showChunksEl.checked = next.showChunks !== false;
  showFactsEl.checked = next.showFacts !== false;
  minImportanceEl.value = next.minImportance == null ? "" : String(next.minImportance);
  minConfidenceEl.value = next.minConfidence == null ? "" : String(next.minConfidence);
  createdAfterEl.value = String(next.createdAfter || "");
}

function persistClientFilterState() {
  const current = readClientFilterState();
  setStorageItem(
    CLIENT_FILTER_STATE_KEY,
    JSON.stringify({
      showConversations: current.showConversations,
      showChunks: current.showChunks,
      showFacts: current.showFacts,
      minImportance: current.minImportance,
      minConfidence: current.minConfidence,
      createdAfter: current.createdAfter
    })
  );
}

function restoreClientFilterState() {
  const parsed = parseJson(getStorageItem(CLIENT_FILTER_STATE_KEY), null);
  if (!parsed || typeof parsed !== "object") return;
  applyClientFilterState(parsed);
}

function filterSummary(state) {
  const bits = [];
  bits.push("kinds=" + [
    state.showConversations ? "conv" : null,
    state.showChunks ? "chunk" : null,
    state.showFacts ? "fact" : null
  ].filter(Boolean).join(","));
  if (state.minImportance != null) bits.push("imp>=" + String(state.minImportance));
  if (state.minConfidence != null) bits.push("conf>=" + String(state.minConfidence));
  if (state.createdAfter) bits.push("after=" + state.createdAfter);
  return bits.join(" ");
}

function hasActiveClientFilters(state) {
  return (
    state.showConversations !== true ||
    state.showChunks !== true ||
    state.showFacts !== true ||
    state.minImportance != null ||
    state.minConfidence != null ||
    Boolean(state.createdAfter)
  );
}

function formatPayloadDelta(delta) {
  if (!delta) return "-";
  return (
    "nodes +" + String(delta.nodes_added) +
    "/-" + String(delta.nodes_removed) +
    "/~" + String(delta.nodes_updated) +
    " edges +" + String(delta.edges_added) +
    "/-" + String(delta.edges_removed) +
    "/~" + String(delta.edges_updated)
  );
}

function activeDisplayMode() {
  const value = String(displayModeEl.value || "graph").trim().toLowerCase();
  return value === "list" ? "list" : "graph";
}

function updateViewButtons() {
  const mode = activeDisplayMode();
  if (graphViewBtn.classList) graphViewBtn.classList.toggle("active", mode === "graph");
  if (listViewBtn.classList) listViewBtn.classList.toggle("active", mode === "list");
  graphViewBtn.setAttribute("aria-pressed", mode === "graph" ? "true" : "false");
  listViewBtn.setAttribute("aria-pressed", mode === "list" ? "true" : "false");
}

function updateCurrentProjectLabel() {
  const value = String(projectEl.value || "").trim();
  currentProjectEl.textContent = value || "(set project_id in URL)";
  currentProjectEl.setAttribute("title", value || "");
}

function activeTimelineSort() {
  return normalizeTimelineSort(timelineSortEl.value || "desc");
}

function normalizeNodeId(value) {
  return String(value == null ? "" : value).trim();
}

function textSnippet(value, maxLen) {
  const text = String(value == null ? "" : value).trim();
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + "...";
}

function timelineEntryKeyForDay(day) {
  return "day:" + day;
}

function timelineEntryKeyForItem(nodeId) {
  return "item:" + normalizeNodeId(nodeId);
}

function timelineItemRenderHash(node, expanded, clock, note, metaBits, fullText) {
  return JSON.stringify([
    TIMELINE_ITEM_TEMPLATE_VERSION,
    node.id,
    node.kind,
    node.label,
    node.text,
    node.created_at,
    node.conversation_id,
    node.chunk_id,
    node.fact_id,
    node.chunk_type,
    node.importance,
    node.confidence,
    node.archived,
    clock,
    note,
    metaBits.join("|"),
    fullText,
    expanded
  ]);
}

function timelineMetaRows(node) {
  return [
    ["id", node.id],
    ["project", node.project_id],
    ["conversation", node.conversation_id],
    ["chunk_id", node.chunk_id],
    ["fact_id", node.fact_id],
    ["kind", node.kind],
    ["created_at", node.created_at],
    ["importance", node.importance],
    ["confidence", node.confidence]
  ]
    .filter((entry) => entry[1] !== null && entry[1] !== undefined && String(entry[1]) !== "");
}

function renderTimelineMetaGrid(metaGridEl, rows) {
  metaGridEl.textContent = "";
  const fragment = document.createDocumentFragment();
  for (const [key, value] of rows) {
    const keyEl = document.createElement("div");
    keyEl.className = "meta-k";
    keyEl.textContent = String(key);
    fragment.appendChild(keyEl);

    const valueEl = document.createElement("div");
    valueEl.className = "meta-v";
    valueEl.textContent = String(value);
    fragment.appendChild(valueEl);
  }
  metaGridEl.appendChild(fragment);
}

function ensureTimelineItemStructure(el) {
  const cached = el.__timelineRefs;
  if (
    cached &&
    cached.summary &&
    cached.summary.parentElement === el &&
    cached.expanded &&
    cached.expanded.parentElement === el
  ) {
    return cached;
  }

  el.innerHTML = "";

  const summary = document.createElement("div");
  summary.className = "timeline-summary";
  summary.setAttribute("role", "button");
  summary.setAttribute("tabindex", "0");
  summary.setAttribute("data-action", "toggle-expand");

  const row = document.createElement("div");
  row.className = "timeline-row";

  const timeEl = document.createElement("div");
  timeEl.className = "timeline-time";
  row.appendChild(timeEl);

  const kindEl = document.createElement("div");
  kindEl.className = "timeline-kind";
  row.appendChild(kindEl);

  const labelEl = document.createElement("div");
  labelEl.className = "timeline-label";

  const noteEl = document.createElement("div");
  noteEl.className = "timeline-note";
  noteEl.hidden = true;

  const metaRowEl = document.createElement("div");
  metaRowEl.className = "timeline-meta-row";
  metaRowEl.hidden = true;

  summary.appendChild(row);
  summary.appendChild(labelEl);
  summary.appendChild(noteEl);
  summary.appendChild(metaRowEl);

  const expanded = document.createElement("div");
  expanded.className = "timeline-expanded";
  expanded.hidden = true;

  const metaGrid = document.createElement("div");
  metaGrid.className = "meta-grid";

  const fullTextEl = document.createElement("div");
  fullTextEl.className = "timeline-fulltext";
  fullTextEl.hidden = true;

  const actions = document.createElement("div");
  actions.className = "timeline-actions";

  const jumpBtn = document.createElement("button");
  jumpBtn.className = "timeline-jump";
  jumpBtn.type = "button";
  jumpBtn.setAttribute("data-action", "open-graph");
  jumpBtn.textContent = "Open In Graph";
  actions.appendChild(jumpBtn);

  expanded.appendChild(metaGrid);
  expanded.appendChild(fullTextEl);
  expanded.appendChild(actions);

  el.appendChild(summary);
  el.appendChild(expanded);

  const refs = {
    summary,
    timeEl,
    kindEl,
    labelEl,
    noteEl,
    metaRowEl,
    expanded,
    metaGrid,
    fullTextEl,
    jumpBtn
  };
  el.__timelineRefs = refs;
  return refs;
}

function patchTimelineItemElement(el, item) {
  const node = item.node;
  const nodeId = normalizeNodeId(node.id);
  const kind = String(node.kind || "");
  const clock = item.ts != null ? new Date(item.ts).toLocaleTimeString() : "--";
  const labelText = String(node.label || nodeId || "(memory)").trim();
  const rawNote = textSnippet(node.text || "", 240);
  const note = rawNote && rawNote !== labelText ? rawNote : "";
  const fullText = String(node.text || "").trim();
  const expanded = timelineExpandedIds.has(nodeId);
  const metaBits = [];
  if (node.conversation_id) metaBits.push("conv=" + node.conversation_id);
  if (node.chunk_type) metaBits.push("type=" + node.chunk_type);
  if (node.importance != null) metaBits.push("imp=" + node.importance);
  if (node.confidence != null) metaBits.push("conf=" + node.confidence);
  if (node.archived) metaBits.push("archived=1");
  if (node.created_at) metaBits.push("at=" + node.created_at);
  const itemHash = timelineItemRenderHash(node, expanded, clock, note, metaBits, fullText);

  el.setAttribute("data-node-id", nodeId);
  el.setAttribute("data-kind", kind);
  el.setAttribute("role", "listitem");
  el.className = "timeline-item" + (expanded ? " expanded" : "");
  const refs = ensureTimelineItemStructure(el);
  refs.summary.setAttribute("data-node-id", nodeId);
  refs.jumpBtn.setAttribute("data-node-id", nodeId);
  if (
    el.getAttribute("data-template-version") === TIMELINE_ITEM_TEMPLATE_VERSION &&
    el.getAttribute("data-render-hash") === itemHash
  ) {
    return;
  }

  const rows = timelineMetaRows(node);
  const normalizedKind = kind.toLowerCase().replace(/[^a-z0-9_-]/g, "");
  refs.summary.setAttribute("aria-expanded", expanded ? "true" : "false");
  refs.timeEl.textContent = clock;
  refs.kindEl.className = normalizedKind ? "timeline-kind " + normalizedKind : "timeline-kind";
  refs.kindEl.textContent = kind || "?";
  refs.labelEl.textContent = labelText;

  if (note) {
    refs.noteEl.hidden = false;
    refs.noteEl.textContent = note;
  } else {
    refs.noteEl.hidden = true;
    refs.noteEl.textContent = "";
  }

  if (metaBits.length) {
    refs.metaRowEl.hidden = false;
    refs.metaRowEl.textContent = metaBits.join(" | ");
  } else {
    refs.metaRowEl.hidden = true;
    refs.metaRowEl.textContent = "";
  }

  refs.expanded.hidden = !expanded;
  renderTimelineMetaGrid(refs.metaGrid, rows);
  if (fullText) {
    refs.fullTextEl.hidden = false;
    refs.fullTextEl.textContent = fullText;
  } else {
    refs.fullTextEl.hidden = true;
    refs.fullTextEl.textContent = "";
  }

  el.setAttribute("data-template-version", TIMELINE_ITEM_TEMPLATE_VERSION);
  el.setAttribute("data-render-hash", itemHash);
}

function patchTimelineDom(items) {
  for (const child of Array.from(timelineListEl.children)) {
    if (!child.getAttribute("data-key")) {
      child.remove();
    }
  }

  const entries = [];
  let currentDay = "";
  for (const item of items) {
    const day = item.ts != null ? new Date(item.ts).toLocaleDateString() : "No timestamp";
    if (day !== currentDay) {
      currentDay = day;
      entries.push({ type: "day", key: timelineEntryKeyForDay(day), day });
    }
    entries.push({ type: "item", key: timelineEntryKeyForItem(item.node.id), item });
  }

  const existingByKey = new Map();
  for (const child of Array.from(timelineListEl.children)) {
    const key = child.getAttribute("data-key");
    if (key) existingByKey.set(key, child);
  }

  let cursor = timelineListEl.firstChild;
  for (const entry of entries) {
    let el = existingByKey.get(entry.key);
    if (!el) {
      el = document.createElement(entry.type === "day" ? "div" : "article");
      el.setAttribute("data-key", entry.key);
      if (entry.type === "day") {
        el.className = "timeline-day";
      } else {
        el.className = "timeline-item";
      }
    } else {
      existingByKey.delete(entry.key);
    }

    if (entry.type === "day") {
      if (el.className !== "timeline-day") el.className = "timeline-day";
      if (el.textContent !== entry.day) el.textContent = entry.day;
    } else {
      patchTimelineItemElement(el, entry.item);
    }

    if (el !== cursor) {
      timelineListEl.insertBefore(el, cursor);
    } else {
      cursor = cursor.nextSibling;
      continue;
    }
    cursor = el.nextSibling;
  }

  for (const stale of existingByKey.values()) {
    stale.remove();
  }
}

function setTimelineEmptyState(message) {
  const existing = timelineListEl.querySelector(".timeline-empty");
  if (
    existing &&
    existing.textContent === message &&
    timelineListEl.childElementCount === 1
  ) {
    return;
  }
  timelineListEl.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "timeline-empty";
  empty.setAttribute("data-key", "empty");
  empty.textContent = message;
  timelineListEl.appendChild(empty);
}

function timelineRenderStateSignature(items, sortDir, searchTerm, filters) {
  const expanded = Array.from(timelineExpandedIds).map(normalizeNodeId).filter(Boolean).sort().join(",");
  const ids = items
    .map((item) => {
      const node = item.node;
      const nodeId = normalizeNodeId(node.id);
      return [
        nodeId,
        node.kind,
        node.created_at || "",
        node.importance == null ? "" : String(node.importance),
        node.confidence == null ? "" : String(node.confidence),
        timelineExpandedIds.has(nodeId) ? "1" : "0"
      ].join("|");
    })
    .join(";");
  return JSON.stringify([
    projectEl.value.trim(),
    lastPayloadSignature,
    sortDir,
    searchTerm,
    filterSummary(filters),
    expanded,
    ids
  ]);
}

function renderTimelineView(opts = {}) {
  const listMode = activeDisplayMode() === "list";
  const timelineUi = ensureTimelineApp();
  if (timelineViewEl.classList) timelineViewEl.classList.toggle("hidden", !listMode);
  graphEl.style.display = listMode ? "none" : "";
  if (!listMode) {
    if (timelineUi && typeof timelineUi.update === "function") {
      timelineUi.update({
        loading: graphLoadInFlight,
        hasPayload: Boolean(rawPayload),
        projectId: projectEl.value.trim(),
        sort: activeTimelineSort(),
        search: String(searchInputEl.value || ""),
        filters: readClientFilterState(),
        metaText: "0 items",
        emptyMessage: rawPayload
          ? "List view is hidden while graph mode is active."
          : "Load a project to see memories.",
        items: []
      });
    }
    return;
  }

  if (!rawPayload) {
    timelineMetaEl.textContent = "0 items";
    if (timelineUi && typeof timelineUi.update === "function") {
      timelineUi.update({
        loading: graphLoadInFlight,
        hasPayload: false,
        projectId: projectEl.value.trim(),
        sort: activeTimelineSort(),
        search: String(searchInputEl.value || ""),
        filters: readClientFilterState(),
        metaText: "0 items",
        emptyMessage: "Load a project to see memories.",
        items: []
      });
    } else {
      setTimelineEmptyState("Load a project to see memories.");
    }
    timelineRenderSignature = "empty:project";
    return;
  }

  const filters = readClientFilterState();
  const searchTerm = String(searchInputEl.value || "").trim().toLowerCase();
  const sortDir = activeTimelineSort();
  const pool = rawNodes.filter((node) => node.kind !== "project");
  const items = pool
    .filter((node) => nodePassesFilters(node, filters))
    .filter((node) => !searchTerm || nodeSearchBlob({ raw: node }).includes(searchTerm))
    .map((node) => ({
      node,
      ts: createdAtTimestamp(node)
    }))
    .sort((a, b) => {
      const at = a.ts == null ? -Infinity : a.ts;
      const bt = b.ts == null ? -Infinity : b.ts;
      if (at !== bt) return sortDir === "asc" ? at - bt : bt - at;
      const aid = String(a.node.id);
      const bid = String(b.node.id);
      return sortDir === "asc" ? aid.localeCompare(bid) : bid.localeCompare(aid);
    });

  timelineMetaEl.textContent =
    String(items.length) + "/" + String(pool.length) + " items (" + (sortDir === "asc" ? "oldest" : "newest") + ")";
  const visibleIds = new Set(items.map((item) => normalizeNodeId(item.node.id)).filter(Boolean));
  timelineExpandedIds = new Set(
    Array.from(timelineExpandedIds)
      .map(normalizeNodeId)
      .filter((id) => id && visibleIds.has(id))
  );
  const signature = timelineRenderStateSignature(items, sortDir, searchTerm, filters);
  const force = opts && opts.force === true;
  if (!force && signature === timelineRenderSignature) {
    return;
  }

  const serializedItems = items.map((item) => timelineUiItemPayload(item));
  const metaText =
    String(items.length) + "/" + String(pool.length) + " items (" + (sortDir === "asc" ? "oldest" : "newest") + ")";

  if (timelineUi && typeof timelineUi.update === "function") {
    timelineUi.update({
      loading: graphLoadInFlight,
      hasPayload: true,
      projectId: projectEl.value.trim(),
      sort: sortDir,
      search: String(searchInputEl.value || ""),
      filters: filters,
      metaText,
      emptyMessage: items.length ? "" : "No memories match current filters/search.",
      items: serializedItems
    });
    timelineRenderSignature = signature;
    return;
  }

  if (!items.length) {
    setTimelineEmptyState("No memories match current filters/search.");
    timelineRenderSignature = signature;
    return;
  }

  const previousScroll = timelineListEl.scrollTop;
  patchTimelineDom(items);
  if (Number.isFinite(previousScroll)) {
    timelineListEl.scrollTop = previousScroll;
  }
  timelineRenderSignature = signature;
}

function applyDisplayModeUi() {
  updateViewButtons();
  if (activeDisplayMode() === "list") {
    stopLiveLoop();
    if (inspectorEl && inspectorEl.classList) inspectorEl.classList.add("hidden");
    if (timelineViewEl.classList) timelineViewEl.classList.add("full-width");
    renderTimelineView();
    setStatus(rawPayload ? "timeline view ready" : "timeline view (load project)");
    return;
  }
  if (inspectorEl && inspectorEl.classList) inspectorEl.classList.remove("hidden");
  if (timelineViewEl.classList) timelineViewEl.classList.remove("full-width");
  if (timelineViewEl.classList) timelineViewEl.classList.add("hidden");
  graphEl.style.display = "";
  scheduleGraphViewportSync({ fit: false });
  if (liveModeEl.checked) startLiveLoop();
  if (rawPayload && graph) {
    refreshGraph({ reason: "displayMode", anchorId: selectedNodeId || "project" });
  }
}

function updateSearchMeta() {
  const term = String(searchInputEl.value || "").trim();
  if (!term) {
    searchMetaEl.textContent = "search: 0";
    return;
  }
  if (!searchMatches.length) {
    searchMetaEl.textContent = "search: 0 matches";
    return;
  }
  const idx = searchMatchIndex >= 0 ? searchMatchIndex + 1 : 0;
  searchMetaEl.textContent = "search: " + String(idx) + "/" + String(searchMatches.length);
}

function nodeSearchBlob(node) {
  const raw = node && node.raw ? node.raw : node || {};
  return [
    raw.id,
    raw.label,
    raw.text,
    raw.conversation_id,
    raw.chunk_id,
    raw.fact_id,
    raw.chunk_type
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function setOverlay(title, body) {
  if (!title && !body) {
    overlayEl.classList.add("hidden");
    overlayTitleEl.textContent = "";
    overlayBodyEl.textContent = "";
    return;
  }
  overlayTitleEl.textContent = title || "";
  overlayBodyEl.textContent = body || "";
  overlayEl.classList.remove("hidden");
}

function toInt(value, fallback, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  const clipped = Math.round(n);
  return Math.max(min, Math.min(max, clipped));
}

function syncGraphViewport(opts = {}) {
  const w = Math.max(320, graphEl.clientWidth || 320);
  const h = Math.max(240, graphEl.clientHeight || 240);
  if (!graph) return;
  if (typeof graph.width === "function") { try { graph.width(w); } catch (_err) {} }
  if (typeof graph.height === "function") { try { graph.height(h); } catch (_err) {} }
  if (opts.fit === true && typeof graph.zoomToFit === "function") {
    try { graph.zoomToFit(220, 36); } catch (_err) {}
  }
}

function scheduleGraphViewportSync(opts = {}) {
  const next = { ...opts };
  if (graphResizeRaf !== null) {
    cancelAnimationFrame(graphResizeRaf);
    graphResizeRaf = null;
  }
  graphResizeRaf = requestAnimationFrame(() => {
    graphResizeRaf = null;
    syncGraphViewport(next);
  });
}

function liveIntervalMs() {
  return toInt(liveEverySecEl.value, 4, 1, 120) * 1000;
}

function payloadSignature(payload) {
  const nodes = payload && payload.nodes ? payload.nodes : [];
  const edges = payload && payload.edges ? payload.edges : [];
  const totals = payload && payload.totals ? payload.totals : {};
  const firstNode = (nodes.length && nodes[0] && nodes[0].data && nodes[0].data.id) ? nodes[0].data.id : "";
  const tailNode = nodes.length ? nodes[nodes.length - 1] : null;
  const tailEdge = edges.length ? edges[edges.length - 1] : null;
  const lastNode = (tailNode && tailNode.data && tailNode.data.id) ? tailNode.data.id : "";
  const lastEdge = (tailEdge && tailEdge.data && tailEdge.data.id) ? tailEdge.data.id : "";
  return JSON.stringify([totals, nodes.length, edges.length, firstNode, lastNode, lastEdge]);
}

function payloadEmpty(payload) {
  const totals = payload && payload.totals ? payload.totals : {};
  return (
    Number(totals.conversations || 0) === 0 &&
    Number(totals.chunks || 0) === 0 &&
    Number(totals.facts || 0) === 0
  );
}

function updateRuntimeKpis() {
  kpiModeEl.textContent = graphMode || "none";
  if (liveModeEl.checked) {
    kpiLiveEl.textContent = "on/" + String(liveIntervalMs() / 1000) + "s";
  } else {
    kpiLiveEl.textContent = "off";
  }
  kpiUpdatedEl.textContent = lastLoadedAt
    ? new Date(lastLoadedAt).toLocaleTimeString()
    : "-";
  updateSearchMeta();
}

function recoverTo2D(reason) {
  if (recoveringFrom3DError) return;
  recoveringFrom3DError = true;
  try {
    renderModeEl.value = "2d";
    setStorageItem("memoryGraphRenderMode", "2d");
    recreateGraphInstance();
    if (rawPayload) {
      refreshGraph({ reason: "recover2d", anchorId: selectedNodeId || "project" });
    }
    setStatus("recovered to 2d mode");
    setError("3d runtime failed; switched to 2d. " + reason);
    setOverlay("3D Runtime Error", "Switched to 2D automatically.\n" + String(reason || ""));
  } catch (err) {
    setStatus("error");
    setError("3d->2d recovery failed: " + String(err));
    setOverlay("Graph Runtime Error", String(err));
  } finally {
    setTimeout(() => { recoveringFrom3DError = false; }, 250);
  }
}

window.addEventListener("error", (event) => {
  if (!event || !event.message) return;
  const message = String(event.message);
  setError("runtime error: " + message);
  setOverlay("Graph Runtime Error", message);
  if (graphMode === "3d" && /tick|3d-force-graph|cannot read properties of undefined/i.test(message)) {
    recoverTo2D(message);
  }
});

window.addEventListener("unhandledrejection", (event) => {
  const message = event && event.reason ? String(event.reason) : "unknown rejection";
  setError("runtime rejection: " + message);
  setOverlay("Graph Runtime Error", message);
  if (graphMode === "3d" && /tick|3d-force-graph|cannot read properties of undefined/i.test(message)) {
    recoverTo2D(message);
  }
});

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMetaRows(entries) {
  return entries
    .filter((item) => item[1] !== null && item[1] !== undefined && String(item[1]) !== "")
    .map((item) => (
      '<div class="meta-k">' + escapeHtml(item[0]) + '</div>' +
      '<div class="meta-v">' + escapeHtml(item[1]) + '</div>'
    ))
    .join("");
}

function extractParamsFromText(text) {
  if (!text) return [];
  const found = [];
  const seen = new Set();
  function pushParam(rawKey, rawValue) {
    const key = String(rawKey || "").trim().replace(/^["']|["']$/g, "");
    let value = String(rawValue || "").trim().replace(/^["']|["']$/g, "");
    if (!key || !value) return;
    value = value.slice(0, 100);
    const signature = key + "=" + value;
    if (seen.has(signature)) return;
    seen.add(signature);
    found.push({ key, value });
  }

  const trimmed = String(text).trim();
  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        for (const [k, v] of Object.entries(parsed)) {
          if (v === null || v === undefined) continue;
          if (typeof v === "object") {
            const compact = JSON.stringify(v).slice(0, 100);
            pushParam(k, compact);
          } else {
            pushParam(k, v);
          }
          if (found.length >= 40) break;
        }
      }
    } catch (_err) {}
  }

  const patterns = [
    /([A-Za-z_][A-Za-z0-9_./-]{1,48})\\s*=\\s*([^,\\n;]+)/g,
    /([A-Za-z_][A-Za-z0-9_./-]{1,48})\\s*:\\s*([^,\\n;]+)/g
  ];

  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(text)) !== null) {
      pushParam(match[1], match[2]);
      if (found.length >= 40) break;
    }
    if (found.length >= 40) break;
  }
  return found;
}

function renderDetailsOverview() {
  if (!rawPayload) {
    detailsEl.innerHTML = '<div class="details-card"><div class="meta-v">No selection yet.</div></div>';
    return;
  }
  const totals = rawPayload.totals || {};
  const filters = readClientFilterState();
  const searchTerm = String(searchInputEl.value || "").trim();
  const searchText = searchTerm
    ? String(searchMatches.length) + " matches for \"" + searchTerm + "\""
    : "-";
  const rows = renderMetaRows([
    ["project_id", projectEl.value.trim()],
    ["nodes_loaded", rawNodes.length],
    ["edges_loaded", rawLinks.length],
    ["conversations", totals.conversations || 0],
    ["chunks", totals.chunks || 0],
    ["facts", totals.facts || 0],
    ["render_mode", graphMode],
    ["display_mode", activeDisplayMode()],
    ["live", liveModeEl.checked ? "on (" + String(liveIntervalMs() / 1000) + "s)" : "off"],
    ["filters", filterSummary(filters)],
    ["search", searchText],
    ["last_delta", formatPayloadDelta(lastPayloadDelta)],
    ["last_updated", lastLoadedAt ? new Date(lastLoadedAt).toISOString() : "-"]
  ]);
  const emptyText = payloadEmpty(rawPayload)
    ? '<div class="details-card"><div class="meta-v">No stored memories found for this project_id yet.</div></div>'
    : "";
  detailsEl.innerHTML =
    '<div class="details-card">' +
      '<div class="details-title">Graph Overview</div>' +
      '<div class="meta-grid">' + rows + '</div>' +
    '</div>' +
    emptyText;
}

function renderNodeDetails(node, neighbors) {
  const raw = node.raw || node;
  const text = String(raw.text || raw.label || "");
  const params = extractParamsFromText(text);
  const rows = renderMetaRows([
    ["kind", raw.kind],
    ["id", raw.id],
    ["project", raw.project_id],
    ["conversation", raw.conversation_id],
    ["chunk_id", raw.chunk_id],
    ["fact_id", raw.fact_id],
    ["chunk_type", raw.chunk_type],
    ["importance", raw.importance],
    ["confidence", raw.confidence],
    ["archived", raw.archived],
    ["created_at", raw.created_at],
    ["neighbors", neighbors.length],
    ["expanded", expandedNodes.has(raw.id)]
  ]);

  const paramsHtml = params.length
    ? (
      '<div class="details-card">' +
        '<div class="details-heading">Parameters</div>' +
        '<div class="param-grid">' +
          params.map((item) =>
            '<div class="param-chip">' +
              '<div class="param-k">' + escapeHtml(item.key) + '</div>' +
              '<div class="param-v">' + escapeHtml(item.value) + '</div>' +
            '</div>'
          ).join("") +
        '</div>' +
      '</div>'
    )
    : "";

  const noteHtml = text
    ? (
      '<div class="details-card">' +
        '<div class="details-heading">Note</div>' +
        '<div class="note-block">' + escapeHtml(text) + '</div>' +
      '</div>'
    )
    : "";

  detailsEl.innerHTML =
    '<div class="details-card">' +
      '<div class="details-title">' + escapeHtml(raw.label || raw.id) + '</div>' +
      '<div class="meta-grid">' + rows + '</div>' +
    '</div>' +
    paramsHtml +
    noteHtml;
}

function updateKpis(visibleNodeCount, visibleEdgeCount) {
  const totals = rawPayload ? (rawPayload.totals || {}) : {};
  const totalNodeCount = rawNodes.length;
  const totalEdgeCount = rawLinks.length;
  kpiNodesEl.textContent = String(visibleNodeCount) + "/" + String(totalNodeCount);
  kpiEdgesEl.textContent = String(visibleEdgeCount) + "/" + String(totalEdgeCount);

  let conv = 0;
  let chunks = 0;
  let facts = 0;
  for (const node of currentData.nodes) {
    if (node.kind === "conversation") conv += 1;
    if (node.kind === "chunk") chunks += 1;
    if (node.kind === "fact") facts += 1;
  }
  kpiConversationsEl.textContent = String(conv) + "/" + String(totals.conversations || 0);
  kpiChunksEl.textContent = String(chunks) + "/" + String(totals.chunks || 0);
  kpiFactsEl.textContent = String(facts) + "/" + String(totals.facts || 0);
}

function buildEndpointUrl() {
  const projectId = projectEl.value.trim();
  if (!projectId) return null;
  const params = new URLSearchParams();
  params.set("project_id", projectId);
  params.set("max_conversations", maxConversationsEl.value || "180");
  params.set("max_chunks", maxChunksEl.value || "1200");
  params.set("max_facts", maxFactsEl.value || "800");
  params.set("include_archived", includeArchivedEl.checked ? "true" : "false");
  return "/v1/memory/graph?" + params.toString();
}

function textLength(value) {
  return String(value == null ? "" : value).trim().length;
}

function computeConversationMetrics() {
  conversationMetricsById = new Map();
  for (const node of rawNodes) {
    if (node.kind !== "conversation") continue;
    const neighbors = adjacency.get(node.id) || new Set();
    let chunks = 0;
    let facts = 0;
    let other = 0;
    let chars = textLength(node.text);

    for (const neighborId of neighbors) {
      const neighbor = nodesById.get(neighborId);
      if (!neighbor) continue;
      const kind = String(neighbor.kind || "");
      if (kind === "chunk") {
        chunks += 1;
        chars += textLength(neighbor.text);
      } else if (kind === "fact") {
        facts += 1;
        chars += textLength(neighbor.text);
      } else if (kind !== "project" && kind !== "conversation") {
        other += 1;
        chars += textLength(neighbor.text);
      }
    }

    const linked = chunks + facts + other;
    const richness =
      (chunks * 1.25) +
      (facts * 0.9) +
      (other * 0.6) +
      Math.min(12, Math.log2(1 + (chars / 220)));

    conversationMetricsById.set(node.id, {
      chunks,
      facts,
      other,
      linked,
      chars,
      richness
    });
  }
}

function nodeVisualSize(node) {
  if (!node) return 2.2;
  const kind = String(node.kind || "");
  if (kind !== "conversation") {
    return SIZE[kind] || 2.2;
  }
  const metrics = conversationMetricsById.get(node.id);
  if (!metrics) return SIZE.conversation || 3.6;
  const score = Math.max(0, Number(metrics.richness) || 0);
  const scale = 1 + Math.min(1.0, Math.log2(1 + score) * 0.35);
  return Math.round((SIZE.conversation || 3.6) * scale * 100) / 100;
}

function buildIndices() {
  nodesById = new Map();
  adjacency = new Map();
  for (const node of rawNodes) {
    nodesById.set(node.id, node);
    adjacency.set(node.id, new Set());
  }
  for (const link of rawLinks) {
    if (!adjacency.has(link.source)) adjacency.set(link.source, new Set());
    if (!adjacency.has(link.target)) adjacency.set(link.target, new Set());
    adjacency.get(link.source).add(link.target);
    adjacency.get(link.target).add(link.source);
  }
  computeConversationMetrics();
}

function defaultBaseVisibleNodes() {
  const nextBase = new Set(["project"]);
  const rootNeighbors = adjacency.get("project") || new Set();
  for (const id of rootNeighbors) nextBase.add(id);

  if (rawNodes.length <= 120) {
    for (const node of rawNodes) nextBase.add(node.id);
  }
  return nextBase;
}

function initializeExplorer() {
  expandedNodes = new Set(["project"]);
  baseVisibleNodes = defaultBaseVisibleNodes();
}

function computeVisibleNodeIds() {
  const visible = new Set(baseVisibleNodes);
  visible.add("project");
  for (const expandedId of expandedNodes) {
    visible.add(expandedId);
    const neighbors = adjacency.get(expandedId) || new Set();
    for (const id of neighbors) visible.add(id);
  }
  return visible;
}

function createdAtTimestamp(node) {
  if (!node || !node.created_at) return null;
  const parsed = Date.parse(String(node.created_at));
  return Number.isFinite(parsed) ? parsed : null;
}

function nodePassesFilters(node, state) {
  if (!node) return false;
  if (node.kind === "project") return true;
  if (node.kind === "conversation" && !state.showConversations) return false;
  if (node.kind === "chunk" && !state.showChunks) return false;
  if (node.kind === "fact" && !state.showFacts) return false;
  if (node.kind === "chunk" && state.minImportance != null) {
    if (!Number.isFinite(node.importance) || Number(node.importance) < state.minImportance) return false;
  }
  if (node.kind === "fact" && state.minConfidence != null) {
    if (!Number.isFinite(node.confidence) || Number(node.confidence) < state.minConfidence) return false;
  }
  if (state.createdAfterTs != null) {
    const createdTs = createdAtTimestamp(node);
    if (createdTs == null || createdTs < state.createdAfterTs) return false;
  }
  return true;
}

function applyClientFilters(visibleIds) {
  const state = readClientFilterState();
  const filtered = new Set();
  for (const id of visibleIds) {
    const node = nodesById.get(id);
    if (nodePassesFilters(node, state)) {
      filtered.add(id);
    }
  }
  filtered.add("project");
  return filtered;
}

function sameMaybe(a, b) {
  return a === b || (a == null && b == null);
}

function nodeDataChanged(prevNode, nextNode) {
  if (!prevNode || !nextNode) return true;
  const watchedFields = [
    "label",
    "kind",
    "text",
    "conversation_id",
    "chunk_id",
    "fact_id",
    "chunk_type",
    "importance",
    "confidence",
    "archived",
    "created_at"
  ];
  for (const field of watchedFields) {
    if (!sameMaybe(prevNode[field], nextNode[field])) return true;
  }
  return false;
}

function linkDataChanged(prevLink, nextLink) {
  if (!prevLink || !nextLink) return true;
  return (
    !sameMaybe(prevLink.source, nextLink.source) ||
    !sameMaybe(prevLink.target, nextLink.target) ||
    !sameMaybe(prevLink.kind, nextLink.kind)
  );
}

function computePayloadDelta(prevNodes, prevLinks, nextNodes, nextLinks) {
  const prevNodeById = new Map();
  const nextNodeById = new Map();
  const prevLinkById = new Map();
  const nextLinkById = new Map();

  for (const node of prevNodes) prevNodeById.set(node.id, node);
  for (const node of nextNodes) nextNodeById.set(node.id, node);
  for (const link of prevLinks) prevLinkById.set(link.id, link);
  for (const link of nextLinks) nextLinkById.set(link.id, link);

  let nodesAdded = 0;
  let nodesRemoved = 0;
  let nodesUpdated = 0;
  let edgesAdded = 0;
  let edgesRemoved = 0;
  let edgesUpdated = 0;

  for (const node of nextNodes) {
    const prev = prevNodeById.get(node.id);
    if (!prev) {
      nodesAdded += 1;
    } else if (nodeDataChanged(prev, node)) {
      nodesUpdated += 1;
    }
  }
  for (const node of prevNodes) {
    if (!nextNodeById.has(node.id)) nodesRemoved += 1;
  }

  for (const link of nextLinks) {
    const prev = prevLinkById.get(link.id);
    if (!prev) {
      edgesAdded += 1;
    } else if (linkDataChanged(prev, link)) {
      edgesUpdated += 1;
    }
  }
  for (const link of prevLinks) {
    if (!nextLinkById.has(link.id)) edgesRemoved += 1;
  }

  return {
    nodes_added: nodesAdded,
    nodes_removed: nodesRemoved,
    nodes_updated: nodesUpdated,
    edges_added: edgesAdded,
    edges_removed: edgesRemoved,
    edges_updated: edgesUpdated
  };
}

function pruneTransientStateToKnownNodes() {
  const knownIds = new Set(rawNodes.map((node) => node.id));
  baseVisibleNodes = new Set(Array.from(baseVisibleNodes).filter((id) => knownIds.has(id)));
  expandedNodes = new Set(Array.from(expandedNodes).filter((id) => knownIds.has(id)));
  if (!expandedNodes.size) expandedNodes = new Set(["project"]);
  if (!baseVisibleNodes.size) baseVisibleNodes = defaultBaseVisibleNodes();
  if (selectedNodeId && !knownIds.has(selectedNodeId)) {
    selectedNodeId = "project";
  }
  for (const id of Array.from(nodeState.keys())) {
    if (!knownIds.has(id)) nodeState.delete(id);
  }
}

function rememberNodeState() {
  for (const node of currentData.nodes) {
    if (typeof node.x === "number" && typeof node.y === "number" && typeof node.z === "number") {
      nodeState.set(node.id, {
        x: node.x,
        y: node.y,
        z: node.z,
        vx: node.vx || 0,
        vy: node.vy || 0,
        vz: node.vz || 0
      });
    }
  }
}

function applyNodeState(nextNodes, anchorId) {
  const anchor = nextNodes.find((n) => n.id === anchorId);
  const anchorPos = anchor && typeof anchor.x === "number"
    ? { x: anchor.x, y: anchor.y, z: anchor.z }
    : { x: 0, y: 0, z: 0 };

  let freshIndex = 0;
  for (const node of nextNodes) {
    const saved = nodeState.get(node.id);
    if (saved) {
      node.x = saved.x;
      node.y = saved.y;
      node.z = saved.z;
      node.vx = saved.vx;
      node.vy = saved.vy;
      node.vz = saved.vz;
      continue;
    }

    const angle = (freshIndex * 0.58) + (Math.random() * 0.24);
    const radius = 20 + (freshIndex % 16) * 7;
    node.x = anchorPos.x + Math.cos(angle) * radius;
    node.y = anchorPos.y + Math.sin(angle) * radius;
    node.z = anchorPos.z + ((freshIndex % 5) - 2) * 4;
    freshIndex += 1;
  }
}

function buildSubgraph(visibleIds, anchorId) {
  const nextNodes = [];
  const nextLinks = [];

  for (const node of rawNodes) {
    if (!visibleIds.has(node.id)) continue;
    nextNodes.push({
      id: node.id,
      label: node.label,
      kind: node.kind,
      sizeVal: nodeVisualSize(node),
      raw: node
    });
  }

  for (const link of rawLinks) {
    if (!visibleIds.has(link.source) || !visibleIds.has(link.target)) continue;
    nextLinks.push({
      id: link.id,
      source: link.source,
      target: link.target,
      kind: link.kind
    });
  }

  applyNodeState(nextNodes, anchorId || "project");
  return { nodes: nextNodes, links: nextLinks };
}

function buildSubgraphIncremental(visibleIds, anchorId) {
  const existingNodesById = new Map();
  const existingLinksById = new Map();
  for (const node of currentData.nodes || []) existingNodesById.set(node.id, node);
  for (const link of currentData.links || []) existingLinksById.set(link.id, link);

  const nextNodes = [];
  const nextLinks = [];

  for (const rawNode of rawNodes) {
    if (!visibleIds.has(rawNode.id)) continue;
    const existing = existingNodesById.get(rawNode.id);
    if (existing) {
      existing.label = rawNode.label;
      existing.kind = rawNode.kind;
      existing.sizeVal = nodeVisualSize(rawNode);
      existing.raw = rawNode;
      nextNodes.push(existing);
      continue;
    }
    nextNodes.push({
      id: rawNode.id,
      label: rawNode.label,
      kind: rawNode.kind,
      sizeVal: nodeVisualSize(rawNode),
      raw: rawNode
    });
  }

  for (const rawLink of rawLinks) {
    if (!visibleIds.has(rawLink.source) || !visibleIds.has(rawLink.target)) continue;
    const existing = existingLinksById.get(rawLink.id);
    if (existing) {
      existing.source = rawLink.source;
      existing.target = rawLink.target;
      existing.kind = rawLink.kind;
      nextLinks.push(existing);
      continue;
    }
    nextLinks.push({
      id: rawLink.id,
      source: rawLink.source,
      target: rawLink.target,
      kind: rawLink.kind
    });
  }

  applyNodeState(nextNodes, anchorId || "project");
  return { nodes: nextNodes, links: nextLinks };
}

function tunePhysics(visibleCount, reason) {
  const linkForce = graph.d3Force("link");
  const charge = graph.d3Force("charge");
  if (linkForce) {
    const distance = Math.max(22, Math.min(120, 18 + Math.sqrt(visibleCount + 1) * 7));
    linkForce.distance(distance);
    linkForce.strength(0.11);
  }
  if (charge) {
    charge.strength(-Math.max(55, Math.min(220, 40 + visibleCount * 0.23)));
  }

  if (visibleCount > 750) {
    graph.d3AlphaDecay(0.12);
    graph.d3VelocityDecay(0.46);
    graph.cooldownTicks(45);
  } else if (visibleCount > 420) {
    graph.d3AlphaDecay(0.09);
    graph.d3VelocityDecay(0.4);
    graph.cooldownTicks(65);
  } else {
    graph.d3AlphaDecay(0.065);
    graph.d3VelocityDecay(0.34);
    graph.cooldownTicks(reason === "load" ? 120 : 78);
  }
}

function refreshStyling() {
  graph
    .nodeColor((node) => {
      if (!highlightedNodes.size) return COLORS[node.kind] || COLORS.project;
      if (highlightedNodes.has(node.id)) return COLORS[node.kind] || COLORS.project;
      return COLORS.dim;
    })
    .linkColor((link) => {
      if (!highlightedLinks.size) {
        return link.kind === "references"
          ? "rgba(157,169,255,0.55)"
          : "rgba(95,115,135,0.34)";
      }
      if (highlightedLinks.has(link.id)) {
        return link.kind === "references"
          ? "rgba(157,169,255,0.88)"
          : "rgba(133,194,255,0.74)";
      }
      return "rgba(70,80,95,0.18)";
    })
    .linkWidth((link) => {
      if (highlightedLinks.size && highlightedLinks.has(link.id)) return 1.9;
      return link.kind === "references" ? 1.1 : 0.58;
    });
}

function setHighlightFromNodeId(nodeId) {
  highlightedNodes = new Set();
  highlightedLinks = new Set();
  if (!nodeId) {
    refreshStyling();
    return;
  }

  highlightedNodes.add(nodeId);
  const neighborIds = adjacency.get(nodeId) || new Set();
  for (const n of neighborIds) highlightedNodes.add(n);
  for (const link of currentData.links) {
    if (link.source === nodeId || link.target === nodeId) highlightedLinks.add(link.id);
  }
  refreshStyling();
}

function focusNodeById(nodeId) {
  selectedNodeId = nodeId;
  setHighlightFromNodeId(nodeId);
  const node = currentData.nodes.find((n) => n.id === nodeId);
  if (!node) return;
  const neighbors = adjacency.get(nodeId) ? Array.from(adjacency.get(nodeId)) : [];
  renderNodeDetails(node, neighbors);

  if (graphMode === "3d") {
    if (typeof node.x === "number" && typeof node.y === "number" && typeof node.z === "number") {
      const dist = Math.max(70, Math.min(220, 64 + Math.sqrt(currentData.nodes.length) * 7));
      graph.cameraPosition(
        { x: node.x + dist, y: node.y + dist * 0.45, z: node.z + dist },
        { x: node.x, y: node.y, z: node.z },
        700
      );
    }
  } else if (typeof graph.centerAt === "function" && typeof node.x === "number" && typeof node.y === "number") {
    graph.centerAt(node.x, node.y, 480);
    const currentZoom = typeof graph.zoom === "function" ? Number(graph.zoom()) : 1;
    const nextZoom = Math.max(1.15, Math.min(7.0, currentZoom * 1.12));
    graph.zoom(nextZoom, 520);
  }
}

function rebuildSearchMatches(opts = {}) {
  const term = String(searchInputEl.value || "").trim().toLowerCase();
  if (!term) {
    searchMatches = [];
    searchMatchIndex = -1;
    updateSearchMeta();
    return;
  }

  const nextMatches = currentData.nodes
    .filter((node) => node.id !== "project" && nodeSearchBlob(node).includes(term))
    .map((node) => node.id);

  const preserveCurrent = opts.preserveCurrent === true;
  const currentId = selectedNodeId;

  searchMatches = nextMatches;
  if (!searchMatches.length) {
    searchMatchIndex = -1;
    updateSearchMeta();
    return;
  }

  if (preserveCurrent && currentId) {
    const idx = searchMatches.indexOf(currentId);
    if (idx >= 0) {
      searchMatchIndex = idx;
    } else if (searchMatchIndex < 0 || searchMatchIndex >= searchMatches.length) {
      searchMatchIndex = 0;
    }
  } else if (searchMatchIndex < 0 || searchMatchIndex >= searchMatches.length) {
    searchMatchIndex = 0;
  }

  if (opts.autoFocus === true && searchMatchIndex >= 0) {
    focusNodeById(searchMatches[searchMatchIndex]);
  }
  updateSearchMeta();
}

function focusSearchMatch(index) {
  if (!searchMatches.length) return;
  const wrapped = ((index % searchMatches.length) + searchMatches.length) % searchMatches.length;
  searchMatchIndex = wrapped;
  const nodeId = searchMatches[searchMatchIndex];
  focusNodeById(nodeId);
  updateSearchMeta();
  setStatus("search " + String(searchMatchIndex + 1) + "/" + String(searchMatches.length));
}

function advanceSearch(direction) {
  rebuildSearchMatches({ preserveCurrent: true, autoFocus: false });
  if (!searchMatches.length) {
    setStatus("search: no matches in current view");
    return;
  }
  if (searchMatchIndex < 0) {
    focusSearchMatch(direction >= 0 ? 0 : searchMatches.length - 1);
    return;
  }
  focusSearchMatch(searchMatchIndex + direction);
}

function clearSearch() {
  searchInputEl.value = "";
  searchMatches = [];
  searchMatchIndex = -1;
  updateSearchMeta();
  if (!selectedNodeId) {
    setStatus("ready");
  }
}

function isTypingTarget(target) {
  if (!target || !(target instanceof Element)) return false;
  const tag = String(target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  return target.hasAttribute("contenteditable");
}

function refreshGraph(opts = {}) {
  if (!graph || !rawPayload) return;
  const reason = opts.reason || "toggle";
  const requestedAnchorId = opts.anchorId || selectedNodeId || "project";
  const incremental = opts.incremental === true;
  const explorerVisibleIds = computeVisibleNodeIds();
  const visibleIds = applyClientFilters(explorerVisibleIds);
  const anchorId = visibleIds.has(requestedAnchorId) ? requestedAnchorId : "project";
  const filters = readClientFilterState();

  rememberNodeState();
  currentData = incremental
    ? buildSubgraphIncremental(visibleIds, anchorId)
    : buildSubgraph(visibleIds, anchorId);
  graph.graphData(currentData);

  tunePhysics(currentData.nodes.length, reason);
  graph.d3ReheatSimulation();
  updateKpis(currentData.nodes.length, currentData.links.length);

  const total = rawNodes.length;
  setStatus(
    "showing " + String(currentData.nodes.length) + " / " + String(total) + " nodes" +
    (hasActiveClientFilters(filters) ? " (filtered)" : "")
  );

  if (reason === "load" || reason === "expandAll" || reason === "collapse") {
    setTimeout(() => {
      try { graph.zoomToFit(500, 36); } catch (_err) {}
    }, 60);
  }

  rebuildSearchMatches({ preserveCurrent: true, autoFocus: false });
  if (reason === "search" && searchMatches.length) {
    if (searchMatchIndex < 0) searchMatchIndex = 0;
    focusSearchMatch(searchMatchIndex);
    return;
  }

  if (anchorId && currentData.nodes.some((n) => n.id === anchorId)) {
    focusNodeById(anchorId);
  } else {
    selectedNodeId = null;
    setHighlightFromNodeId(null);
    renderDetailsOverview();
  }
}

function pruneTransientExpanded(nodeId) {
  const neighbors = adjacency.get(nodeId) || new Set();
  for (const id of neighbors) {
    if (id === "project") continue;
    if (!baseVisibleNodes.has(id)) expandedNodes.delete(id);
  }
}

function toggleNodeExpansion(nodeId) {
  if (nodeId !== "project" && expandedNodes.has(nodeId)) {
    expandedNodes.delete(nodeId);
    pruneTransientExpanded(nodeId);
  } else {
    expandedNodes.add(nodeId);
  }
  refreshGraph({ reason: "toggle", anchorId: nodeId });
  const mode = expandedNodes.has(nodeId) ? "expanded" : "collapsed";
  setStatus(mode + " " + nodeId);
}

function collapseAll() {
  expandedNodes = new Set(["project"]);
  selectedNodeId = "project";
  refreshGraph({ reason: "collapse", anchorId: "project" });
  setStatus("collapsed to overview");
}

function expandAll() {
  expandedNodes = new Set(rawNodes.map((n) => n.id));
  refreshGraph({ reason: "expandAll", anchorId: selectedNodeId || "project" });
  setStatus("expanded full loaded graph");
}

function resetFocus() {
  selectedNodeId = null;
  setHighlightFromNodeId(null);
  renderDetailsOverview();
  setStatus("ready");
}

function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")));
  } catch (_err) {
    return false;
  }
}

function attachCommonHandlers() {
  graph
    .onNodeClick((node) => {
      toggleNodeExpansion(node.id);
    })
    .onNodeHover((node) => {
      graphEl.style.cursor = node ? "pointer" : "grab";
      if (node && !selectedNodeId) setStatus(node.kind + ": " + node.label);
      if (!node && !selectedNodeId) setStatus("ready");
    })
    .onBackgroundClick(() => {
      resetFocus();
    });
}

function createGraph3D() {
  if (typeof window.ForceGraph3D === "undefined") {
    throw new Error("3d-force-graph failed to load. Check /ui/static/vendor/3d-force-graph.min.js");
  }

  graphMode = "3d";
  graph = ForceGraph3D({
    controlType: "orbit",
    rendererConfig: { antialias: false, alpha: true }
  })(graphEl)
    .backgroundColor("#0b1018")
    .showNavInfo(false)
    .nodeId("id")
    .nodeLabel((node) => "[" + String(node.kind || "?") + "] " + String(node.label || node.id))
    .nodeVal((node) => (Number.isFinite(node.sizeVal) ? node.sizeVal : (SIZE[node.kind] || 2.2)))
    .nodeColor((node) => COLORS[node.kind] || COLORS.project)
    .nodeOpacity(0.95)
    .nodeResolution(6)
    .linkOpacity(0.45)
    .linkDirectionalArrowLength(0)
    .linkDirectionalParticles(0);

  attachCommonHandlers();
  graph.d3Force("center", null);
  graph.d3Force("charge").strength(-95);
  graph.d3Force("link").distance(58).strength(0.11);
  graph.d3VelocityDecay(0.34);
  graph.d3AlphaDecay(0.065);
  graph.cooldownTicks(110);
  syncGraphViewport({ fit: false });
}

function createGraph2D() {
  if (typeof window.ForceGraph === "undefined") {
    throw new Error("force-graph fallback failed to load. Check /ui/static/vendor/force-graph.min.js");
  }

  graphMode = "2d";
  graph = ForceGraph()(graphEl)
    .backgroundColor("#0b1018")
    .nodeId("id")
    .nodeLabel((node) => "[" + String(node.kind || "?") + "] " + String(node.label || node.id))
    .nodeVal((node) => (Number.isFinite(node.sizeVal) ? node.sizeVal : (SIZE[node.kind] || 2.2)))
    .nodeRelSize(4)
    .nodeColor((node) => COLORS[node.kind] || COLORS.project)
    .linkColor((link) => link.kind === "references" ? "rgba(157,169,255,0.55)" : "rgba(95,115,135,0.34)")
    .linkWidth((link) => link.kind === "references" ? 1.1 : 0.58);

  attachCommonHandlers();
  graph.d3Force("charge").strength(-95);
  graph.d3Force("link").distance(58).strength(0.11);
  graph.d3VelocityDecay(0.34);
  graph.d3AlphaDecay(0.065);
  graph.cooldownTicks(110);
  syncGraphViewport({ fit: false });
}

function createGraphInstance() {
  const requested = String(renderModeEl.value || "auto").toLowerCase();
  const canUse3D = webglAvailable() && typeof window.ForceGraph3D !== "undefined";

  if (requested === "auto") {
    createGraph2D();
    setStatus("auto mode resolved to 2d");
    updateRuntimeKpis();
    return;
  }

  if (requested === "2d") {
    createGraph2D();
    setStatus("2d mode ready");
    updateRuntimeKpis();
    return;
  }

  if (requested === "3d" || requested === "auto") {
    try {
      createGraph3D();
      setStatus("3d mode ready" + (requested === "auto" ? "" : " (forced)"));
      updateRuntimeKpis();
      return;
    } catch (err) {
      if (requested === "3d") {
        setError("forced 3d failed, falling back to 2d: " + String(err));
      } else if (canUse3D) {
        setError("3d init failed, falling back to 2d: " + String(err));
      }
    }
  }

  try {
    createGraph2D();
    setStatus("2d fallback mode ready");
    updateRuntimeKpis();
  } catch (err) {
    graph = null;
    graphMode = "none";
    updateRuntimeKpis();
    throw new Error(
      "graph init failed (3d and 2d). Check /ui/static/vendor assets. Details: " + String(err)
    );
  }
}

function recreateGraphInstance() {
  if (graph && typeof graph._destructor === "function") {
    try { graph._destructor(); } catch (_err) {}
  }
  graph = null;
  graphEl.innerHTML = "";
  createGraphInstance();
}

async function loadGraph(opts = {}) {
  const reason = opts.reason || "load";
  const preserveState = opts.preserveState === true;
  const silent = opts.silent === true;
  if (graphLoadInFlight) return;

  setError("");
  const endpoint = buildEndpointUrl();
  if (!endpoint) {
    setStatus("enter project_id");
    setOverlay("Project ID Required", "Set project_id to load graph data.");
    return;
  }
  updateCurrentProjectLabel();

  if (!silent) {
    setStatus(reason === "live" ? "syncing..." : "loading graph...");
  }
  if (!rawPayload && reason !== "live") {
    setOverlay("Loading Memory Graph", "Fetching nodes and edges from /v1/memory/graph ...");
  }

  graphLoadInFlight = true;
  if (activeDisplayMode() === "list") {
    renderTimelineView({ force: true });
  }
  const started = performance.now();
  const prevNodeCount = rawNodes.length;
  const prevEdgeCount = rawLinks.length;
  const prevSignature = lastPayloadSignature;
  const timeoutMs = reason === "live" ? Math.max(1200, liveIntervalMs() - 300) : 9000;
  const controller = new AbortController();
  const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const resp = await fetch(endpoint, { signal: controller.signal, cache: "no-store" });
    const payload = await resp.json();
    if (!resp.ok) {
      const errMsg = payload && payload.error && payload.error.message
        ? payload.error.message
        : ("request failed with status " + resp.status);
      throw new Error(errMsg);
    }

    const signature = payloadSignature(payload);
    if (reason === "live" && preserveState && signature === prevSignature) {
      rawPayload = payload;
      lastPayloadDelta = {
        nodes_added: 0,
        nodes_removed: 0,
        nodes_updated: 0,
        edges_added: 0,
        edges_removed: 0,
        edges_updated: 0
      };
      lastLoadedAt = Date.now();
      updateRuntimeKpis();
      if (payloadEmpty(payload)) {
        setOverlay(
          "No Memories Yet",
          "No conversations/chunks/facts exist for this project yet.\nData will appear here as hooks ingest activity."
        );
      } else {
        setOverlay("", "");
      }
      if (activeDisplayMode() === "list") {
        renderTimelineView();
      }
      if (!silent) setStatus("live synced (no changes)");
      return;
    }

    const nextRawNodes = (payload.nodes || []).map((entry) => ({ ...entry.data }));
    const nextRawLinks = (payload.edges || []).map((entry) => ({
      id: entry.data.id,
      source: entry.data.source,
      target: entry.data.target,
      kind: entry.data.kind
    }));
    const payloadDelta = computePayloadDelta(rawNodes, rawLinks, nextRawNodes, nextRawLinks);

    if (graph && preserveState) {
      rememberNodeState();
    }

    rawPayload = payload;
    rawNodes = nextRawNodes;
    rawLinks = nextRawLinks;
    buildIndices();

    if (preserveState && graph) {
      baseVisibleNodes = defaultBaseVisibleNodes();
      pruneTransientStateToKnownNodes();
    } else {
      initializeExplorer();
      nodeState = new Map();
      highlightedNodes = new Set();
      highlightedLinks = new Set();
      selectedNodeId = "project";
    }

    if (!graph) createGraphInstance();
    const anchorId = selectedNodeId || "project";
    const incremental = reason === "live" && preserveState;
    refreshGraph({
      reason: reason === "live" ? "live" : "load",
      anchorId,
      incremental
    });

    if (!preserveState && graphMode === "3d" && currentData.nodes.length > 0) {
      try {
        graph.cameraPosition({ x: 0, y: 0, z: 220 }, { x: 0, y: 0, z: 0 }, 0);
      } catch (_err) {}
    }

    const ms = Math.round(performance.now() - started);
    const nodeDelta = rawNodes.length - prevNodeCount;
    const edgeDelta = rawLinks.length - prevEdgeCount;
    lastPayloadDelta = payloadDelta;
    lastPayloadSignature = signature;
    lastLoadedAt = Date.now();
    updateRuntimeKpis();
    setStorageItem("memoryGraphProjectId", projectEl.value.trim());

    if (payloadEmpty(payload)) {
      setOverlay(
        "No Memories Yet",
        "No conversations/chunks/facts exist for this project yet.\nData will appear here as hooks ingest activity."
      );
      renderDetailsOverview();
    } else {
      setOverlay("", "");
    }
    if (activeDisplayMode() === "list") {
      renderTimelineView();
    }

    if (reason === "live") {
      setStatus(
        "live sync +" + String(nodeDelta) + " nodes, +" + String(edgeDelta) + " edges " +
        "(delta " + formatPayloadDelta(payloadDelta) + ") in " + String(ms) + "ms (" + graphMode + ")"
      );
    } else {
      setStatus("loaded in " + String(ms) + "ms (" + graphMode + ")");
    }
  } catch (err) {
    setStatus("error");
    setError(String(err));
    setOverlay("Graph Load Failed", String(err));
  } finally {
    clearTimeout(timeoutHandle);
    graphLoadInFlight = false;
    if (activeDisplayMode() === "list") {
      renderTimelineView({ force: true });
    }
  }
}

async function switchRenderModeAndRebuild() {
  if (!rawPayload) return;
  setError("");
  setStatus("switching render mode...");
  try {
    recreateGraphInstance();
    refreshGraph({ reason: "modeSwitch", anchorId: selectedNodeId || "project" });
    updateRuntimeKpis();
    setStatus("render mode switched to " + graphMode);
  } catch (err) {
    setStatus("error");
    setError(String(err));
    setOverlay("Render Mode Error", String(err));
  }
}

function stopLiveLoop() {
  if (liveLoopTimer !== null) {
    clearTimeout(liveLoopTimer);
    liveLoopTimer = null;
  }
  updateRuntimeKpis();
}

function startLiveLoop() {
  stopLiveLoop();
  if (!liveModeEl.checked) return;
  const tick = async () => {
    if (!liveModeEl.checked) {
      stopLiveLoop();
      return;
    }
    await loadGraph({ reason: "live", preserveState: true, silent: true });
    if (!liveModeEl.checked) return;
    liveLoopTimer = setTimeout(tick, liveIntervalMs());
  };
  liveLoopTimer = setTimeout(tick, liveIntervalMs());
  updateRuntimeKpis();
}

function captureCurrentViewPreset(name, id) {
  const filters = readClientFilterState();
  return {
    id,
    name,
    savedAt: new Date().toISOString(),
    projectId: projectEl.value.trim(),
    maxConversations: toInt(maxConversationsEl.value, 180, 1, 5000),
    maxChunks: toInt(maxChunksEl.value, 1200, 1, 20000),
    maxFacts: toInt(maxFactsEl.value, 800, 1, 10000),
    includeArchived: includeArchivedEl.checked,
    renderMode: String(renderModeEl.value || "2d"),
    displayMode: activeDisplayMode(),
    timelineSort: activeTimelineSort(),
    liveMode: liveModeEl.checked,
    liveEverySec: toInt(liveEverySecEl.value, 4, 1, 120),
    search: String(searchInputEl.value || "").trim(),
    filters: {
      showConversations: filters.showConversations,
      showChunks: filters.showChunks,
      showFacts: filters.showFacts,
      minImportance: filters.minImportance,
      minConfidence: filters.minConfidence,
      createdAfter: filters.createdAfter
    },
    selectedNodeId: selectedNodeId || "project",
    expandedNodeIds: Array.from(expandedNodes).slice(0, 5000)
  };
}

function sanitizePreset(raw) {
  if (!raw || typeof raw !== "object") return null;
  const id = typeof raw.id === "string" ? raw.id : "";
  const name = typeof raw.name === "string" ? raw.name : "";
  if (!id || !name) return null;
  return {
    id,
    name,
    savedAt: typeof raw.savedAt === "string" ? raw.savedAt : null,
    projectId: typeof raw.projectId === "string" ? raw.projectId : "",
    maxConversations: toInt(raw.maxConversations, 180, 1, 5000),
    maxChunks: toInt(raw.maxChunks, 1200, 1, 20000),
    maxFacts: toInt(raw.maxFacts, 800, 1, 10000),
    includeArchived: Boolean(raw.includeArchived),
    renderMode: ["auto", "2d", "3d"].includes(String(raw.renderMode || ""))
      ? String(raw.renderMode)
      : "2d",
    displayMode: ["graph", "list"].includes(String(raw.displayMode || ""))
      ? String(raw.displayMode)
      : "graph",
    timelineSort: ["asc", "desc"].includes(String(raw.timelineSort || ""))
      ? String(raw.timelineSort)
      : "desc",
    liveMode: Boolean(raw.liveMode),
    liveEverySec: toInt(raw.liveEverySec, 4, 1, 120),
    search: typeof raw.search === "string" ? raw.search : "",
    filters: {
      showConversations: raw.filters && raw.filters.showConversations !== false,
      showChunks: raw.filters && raw.filters.showChunks !== false,
      showFacts: raw.filters && raw.filters.showFacts !== false,
      minImportance: raw.filters ? toThreshold(raw.filters.minImportance) : null,
      minConfidence: raw.filters ? toThreshold(raw.filters.minConfidence) : null,
      createdAfter: raw.filters && typeof raw.filters.createdAfter === "string"
        ? raw.filters.createdAfter
        : ""
    },
    selectedNodeId: typeof raw.selectedNodeId === "string" ? raw.selectedNodeId : "project",
    expandedNodeIds: Array.isArray(raw.expandedNodeIds)
      ? raw.expandedNodeIds.filter((id) => typeof id === "string").slice(0, 5000)
      : ["project"]
  };
}

function renderViewPresetOptions(selectedId) {
  const previous = selectedId || viewPresetSelectEl.value || "";
  viewPresetSelectEl.innerHTML = '<option value="">saved views</option>';
  for (const preset of viewPresets) {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = preset.name;
    viewPresetSelectEl.appendChild(option);
  }
  if (previous && viewPresets.some((preset) => preset.id === previous)) {
    viewPresetSelectEl.value = previous;
  } else {
    viewPresetSelectEl.value = "";
  }
}

function persistViewPresets(selectedId) {
  setStorageItem(VIEW_PRESETS_KEY, JSON.stringify(viewPresets.slice(0, 40)));
  renderViewPresetOptions(selectedId);
}

function restoreViewPresets() {
  const parsed = parseJson(getStorageItem(VIEW_PRESETS_KEY), []);
  if (!Array.isArray(parsed)) {
    viewPresets = [];
    renderViewPresetOptions("");
    return;
  }
  viewPresets = parsed
    .map((item) => sanitizePreset(item))
    .filter(Boolean)
    .slice(0, 40);
  renderViewPresetOptions("");
}

async function applyViewPresetById(id) {
  const preset = viewPresets.find((item) => item.id === id);
  if (!preset) return;

  projectEl.value = preset.projectId || projectEl.value;
  maxConversationsEl.value = String(preset.maxConversations);
  maxChunksEl.value = String(preset.maxChunks);
  maxFactsEl.value = String(preset.maxFacts);
  includeArchivedEl.checked = preset.includeArchived;
  renderModeEl.value = preset.renderMode;
  displayModeEl.value = preset.displayMode || "graph";
  timelineSortEl.value = preset.timelineSort || "desc";
  liveModeEl.checked = preset.liveMode;
  liveEverySecEl.value = String(preset.liveEverySec);
  searchInputEl.value = preset.search;
  applyClientFilterState(preset.filters || {});
  normalizeThresholdInput(minImportanceEl);
  normalizeThresholdInput(minConfidenceEl);

  expandedNodes = new Set(preset.expandedNodeIds || ["project"]);
  expandedNodes.add("project");
  selectedNodeId = preset.selectedNodeId || "project";

  persistClientFilterState();
  setStorageItem("memoryGraphLiveMode", liveModeEl.checked ? "1" : "0");
  setStorageItem("memoryGraphLiveEverySec", liveEverySecEl.value);
  setStorageItem("memoryGraphRenderMode", renderModeEl.value);
  setStorageItem("memoryGraphDisplayMode", displayModeEl.value);
  setStorageItem(TIMELINE_SORT_KEY, timelineSortEl.value);

  recreateGraphInstance();
  await loadGraph({ reason: "load", preserveState: false });
  applyDisplayModeUi();
  if (selectedNodeId && activeDisplayMode() !== "list") {
    refreshGraph({ reason: "view", anchorId: selectedNodeId });
  }

  if (liveModeEl.checked) {
    startLiveLoop();
  } else {
    stopLiveLoop();
  }
  setStatus("applied view \"" + preset.name + "\"");
}

async function applySelectedViewPreset() {
  const selected = String(viewPresetSelectEl.value || "");
  if (!selected) return;
  await applyViewPresetById(selected);
}

function saveCurrentViewPreset() {
  const currentId = String(viewPresetSelectEl.value || "");
  const existing = currentId ? viewPresets.find((item) => item.id === currentId) : null;
  const defaultName = existing
    ? existing.name
    : ((projectEl.value.trim().split("/").pop() || "memory") + " view");
  const name = window.prompt("Name for this view preset:", defaultName);
  if (!name || !name.trim()) return;

  const id = existing ? existing.id : ("view-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 7));
  const preset = captureCurrentViewPreset(name.trim(), id);
  viewPresets = [preset, ...viewPresets.filter((item) => item.id !== id)].slice(0, 40);
  persistViewPresets(id);
  setStatus("saved view \"" + preset.name + "\"");
}

function deleteSelectedViewPreset() {
  const selected = String(viewPresetSelectEl.value || "");
  if (!selected) return;
  const existing = viewPresets.find((item) => item.id === selected);
  viewPresets = viewPresets.filter((item) => item.id !== selected);
  persistViewPresets("");
  setStatus("deleted view \"" + (existing ? existing.name : selected) + "\"");
}

function refreshAfterClientFilterChange(reason) {
  persistClientFilterState();
  if (!rawPayload) {
    updateSearchMeta();
    return;
  }
  if (activeDisplayMode() === "list") {
    renderTimelineView();
    return;
  }
  if (!graph) {
    updateSearchMeta();
    return;
  }
  refreshGraph({ reason: reason || "filter", anchorId: selectedNodeId || "project" });
}

function initializeFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const projectFromUrl = params.get("project_id");
  const remembered = getStorageItem("memoryGraphProjectId");
  const rememberedMode = getStorageItem("memoryGraphRenderMode");
  const rememberedDisplay = getStorageItem("memoryGraphDisplayMode");
  const rememberedTimelineSort = getStorageItem(TIMELINE_SORT_KEY);
  const rememberedLive = getStorageItem("memoryGraphLiveMode");
  const rememberedEvery = getStorageItem("memoryGraphLiveEverySec");
  restoreClientFilterState();

  if (projectFromUrl && !projectEl.value) {
    projectEl.value = projectFromUrl;
  } else if (!projectEl.value && remembered) {
    projectEl.value = remembered;
  }

  const modeFromUrl = params.get("mode");
  const mode = (modeFromUrl || rememberedMode || "2d").toLowerCase();
  if (mode === "2d" || mode === "3d" || mode === "auto") {
    renderModeEl.value = mode;
  }

  const displayFromUrl = params.get("view") || params.get("display");
  const display = String(displayFromUrl || rememberedDisplay || "graph").toLowerCase();
  if (display === "list" || display === "graph") {
    displayModeEl.value = display;
  } else {
    displayModeEl.value = "graph";
  }
  setStorageItem("memoryGraphDisplayMode", displayModeEl.value);

  const timelineSortFromUrl = params.get("timeline_sort") || params.get("sort");
  const timelineSort = String(timelineSortFromUrl || rememberedTimelineSort || "desc").toLowerCase();
  timelineSortEl.value = timelineSort === "asc" ? "asc" : "desc";
  setStorageItem(TIMELINE_SORT_KEY, timelineSortEl.value);

  const liveFromUrl = params.get("live");
  if (liveFromUrl === "1" || liveFromUrl === "true") {
    liveModeEl.checked = true;
  } else if (liveFromUrl === "0" || liveFromUrl === "false") {
    liveModeEl.checked = false;
  } else if (rememberedLive) {
    liveModeEl.checked = rememberedLive === "1";
  }

  const everyFromUrl = params.get("every");
  const every = everyFromUrl || rememberedEvery || liveEverySecEl.value;
  liveEverySecEl.value = String(toInt(every, 4, 1, 120));

  const searchFromUrl = params.get("q");
  if (searchFromUrl !== null) {
    searchInputEl.value = searchFromUrl;
  }

  const kindsFromUrl = params.get("kinds");
  if (kindsFromUrl) {
    const kinds = new Set(
      kindsFromUrl
        .split(",")
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean)
    );
    showConversationsEl.checked = kinds.has("conv") || kinds.has("conversation");
    showChunksEl.checked = kinds.has("chunk") || kinds.has("chunks");
    showFactsEl.checked = kinds.has("fact") || kinds.has("facts");
  }

  const minImportanceFromUrl = params.get("min_importance");
  if (minImportanceFromUrl !== null) minImportanceEl.value = minImportanceFromUrl;
  const minConfidenceFromUrl = params.get("min_confidence");
  if (minConfidenceFromUrl !== null) minConfidenceEl.value = minConfidenceFromUrl;
  const createdAfterFromUrl = params.get("created_after");
  if (createdAfterFromUrl !== null) createdAfterEl.value = createdAfterFromUrl;

  normalizeThresholdInput(minImportanceEl);
  normalizeThresholdInput(minConfidenceEl);
  persistClientFilterState();
  updateCurrentProjectLabel();
  updateSearchMeta();
}

loadBtn.addEventListener("click", async () => {
  await loadGraph({ reason: "load", preserveState: false });
  if (liveModeEl.checked) startLiveLoop();
});
collapseBtn.addEventListener("click", () => {
  if (!graph) return;
  collapseAll();
});
expandAllBtn.addEventListener("click", () => {
  if (!graph) return;
  expandAll();
});
fitBtn.addEventListener("click", () => {
  if (!graph) return;
  try { graph.zoomToFit(400, 36); } catch (_err) {}
});
displayModeEl.addEventListener("change", () => {
  setStorageItem("memoryGraphDisplayMode", activeDisplayMode());
  applyDisplayModeUi();
});
graphViewBtn.addEventListener("click", () => {
  displayModeEl.value = "graph";
  setStorageItem("memoryGraphDisplayMode", "graph");
  applyDisplayModeUi();
});
listViewBtn.addEventListener("click", () => {
  displayModeEl.value = "list";
  setStorageItem("memoryGraphDisplayMode", "list");
  applyDisplayModeUi();
});
timelineSortEl.addEventListener("change", () => {
  setListSortFromUi(timelineSortEl.value);
});
timelineListEl.addEventListener("click", (event) => {
  const target = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-action]")
    : null;
  if (!target) return;
  const parentItem = target.closest(".timeline-item");
  const nodeId = normalizeNodeId(
    target.getAttribute("data-node-id") ||
    (parentItem ? parentItem.getAttribute("data-node-id") : "")
  );
  if (!nodeId) return;
  const action = String(target.getAttribute("data-action") || "");
  if (action === "toggle-expand") {
    toggleTimelineExpanded(nodeId);
    return;
  }
  if (action === "open-graph") {
    openNodeFromTimeline(nodeId);
  }
});
timelineListEl.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const target = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-action='toggle-expand']")
    : null;
  if (!target) return;
  const nodeId = normalizeNodeId(target.getAttribute("data-node-id"));
  if (!nodeId) return;
  event.preventDefault();
  toggleTimelineExpanded(nodeId);
});
searchInputEl.addEventListener("input", () => {
  if (activeDisplayMode() === "list") {
    renderTimelineView();
    updateSearchMeta();
    return;
  }
  rebuildSearchMatches({ preserveCurrent: true, autoFocus: false });
  if (!searchInputEl.value.trim()) {
    if (!selectedNodeId) {
      renderDetailsOverview();
    }
    return;
  }
  if (!rawPayload || !graph) return;
  if (!searchMatches.length) {
    setStatus("search: no matches in current view");
  }
});
searchInputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    if (activeDisplayMode() === "list") {
      renderTimelineView();
      return;
    }
    advanceSearch(1);
  }
});
searchPrevBtn.addEventListener("click", () => {
  if (activeDisplayMode() === "list") {
    setStatus("search prev/next is available in graph view");
    return;
  }
  advanceSearch(-1);
});
searchNextBtn.addEventListener("click", () => {
  if (activeDisplayMode() === "list") {
    setStatus("search prev/next is available in graph view");
    return;
  }
  advanceSearch(1);
});
searchClearBtn.addEventListener("click", () => {
  clearSearch();
  if (activeDisplayMode() === "list") {
    renderTimelineView();
    return;
  }
  if (!selectedNodeId) renderDetailsOverview();
});
projectEl.addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    await loadGraph({ reason: "load", preserveState: false });
    if (liveModeEl.checked) startLiveLoop();
  }
});
renderModeEl.addEventListener("change", async () => {
  setStorageItem("memoryGraphRenderMode", renderModeEl.value);
  updateRuntimeKpis();
  await switchRenderModeAndRebuild();
});
liveModeEl.addEventListener("change", () => {
  setStorageItem("memoryGraphLiveMode", liveModeEl.checked ? "1" : "0");
  if (liveModeEl.checked) {
    startLiveLoop();
  } else {
    stopLiveLoop();
  }
  updateRuntimeKpis();
});
liveEverySecEl.addEventListener("change", () => {
  liveEverySecEl.value = String(toInt(liveEverySecEl.value, 4, 1, 120));
  setStorageItem("memoryGraphLiveEverySec", liveEverySecEl.value);
  if (liveModeEl.checked) startLiveLoop();
  updateRuntimeKpis();
});
showConversationsEl.addEventListener("change", () => {
  refreshAfterClientFilterChange("filter");
});
showChunksEl.addEventListener("change", () => {
  refreshAfterClientFilterChange("filter");
});
showFactsEl.addEventListener("change", () => {
  refreshAfterClientFilterChange("filter");
});
minImportanceEl.addEventListener("change", () => {
  normalizeThresholdInput(minImportanceEl);
  refreshAfterClientFilterChange("filter");
});
minConfidenceEl.addEventListener("change", () => {
  normalizeThresholdInput(minConfidenceEl);
  refreshAfterClientFilterChange("filter");
});
createdAfterEl.addEventListener("change", () => {
  refreshAfterClientFilterChange("filter");
});
applyViewBtn.addEventListener("click", async () => {
  await applySelectedViewPreset();
});
saveViewBtn.addEventListener("click", () => {
  saveCurrentViewPreset();
});
deleteViewBtn.addEventListener("click", () => {
  deleteSelectedViewPreset();
});
includeArchivedEl.addEventListener("change", async () => {
  if (!rawPayload) return;
  await loadGraph({ reason: "load", preserveState: false });
});
maxConversationsEl.addEventListener("change", async () => {
  maxConversationsEl.value = String(toInt(maxConversationsEl.value, 180, 1, 5000));
  if (!rawPayload) return;
  await loadGraph({ reason: "load", preserveState: false });
});
maxChunksEl.addEventListener("change", async () => {
  maxChunksEl.value = String(toInt(maxChunksEl.value, 1200, 1, 20000));
  if (!rawPayload) return;
  await loadGraph({ reason: "load", preserveState: false });
});
maxFactsEl.addEventListener("change", async () => {
  maxFactsEl.value = String(toInt(maxFactsEl.value, 800, 1, 10000));
  if (!rawPayload) return;
  await loadGraph({ reason: "load", preserveState: false });
});
window.addEventListener("resize", () => {
  scheduleGraphViewportSync({ fit: true });
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopLiveLoop();
  } else if (liveModeEl.checked) {
    startLiveLoop();
  }
});
document.addEventListener("keydown", (event) => {
  if (isTypingTarget(event.target)) return;
  if (event.key === "/") {
    if (searchInputEl.offsetParent === null) return;
    event.preventDefault();
    searchInputEl.focus();
    searchInputEl.select();
    return;
  }
  if (event.key === "g" || event.key === "G") {
    displayModeEl.value = "graph";
    setStorageItem("memoryGraphDisplayMode", "graph");
    applyDisplayModeUi();
    return;
  }
  if (event.key === "t" || event.key === "T") {
    displayModeEl.value = "list";
    setStorageItem("memoryGraphDisplayMode", "list");
    applyDisplayModeUi();
    return;
  }
  if (event.key === "l" || event.key === "L") {
    loadGraph({ reason: "load", preserveState: false }).then(() => {
      if (liveModeEl.checked) startLiveLoop();
    });
  }
});

restoreViewPresets();
initializeFromUrl();
syncGraphViewport({ fit: false });
updateRuntimeKpis();
applyDisplayModeUi();
if (projectEl.value.trim()) {
  loadGraph({ reason: "load", preserveState: false }).then(() => {
    applyDisplayModeUi();
    if (liveModeEl.checked) startLiveLoop();
  });
} else {
  setStatus("enter project_id");
  setOverlay("Project ID Required", "Set project_id to load graph data.");
}

// ===== DASHBOARD RAIL / FLYOUT INIT =====
(function initDashboard() {
  // --- Element refs ---
  var railFilterBtn    = document.getElementById("railFilterBtn");
  var railSearchBtn    = document.getElementById("railSearchBtn");
  var railLiveBtn      = document.getElementById("railLiveBtn");
  var railSettingsBtn  = document.getElementById("railSettingsBtn");
  var filterFlyout     = document.getElementById("filterFlyout");
  var settingsFlyout   = document.getElementById("settingsFlyout");
  var filterFlyoutClose   = document.getElementById("filterFlyoutClose");
  var settingsFlyoutClose = document.getElementById("settingsFlyoutClose");
  var searchBarEl      = document.getElementById("searchBar");
  var statusDotEl      = document.getElementById("statusDot");

  // Pill buttons
  var pillConversations = document.getElementById("pillConversations");
  var pillChunks        = document.getElementById("pillChunks");
  var pillFacts         = document.getElementById("pillFacts");

  // Filter flyout controls
  var flyoutMinImportance    = document.getElementById("flyoutMinImportance");
  var flyoutMinImportanceVal = document.getElementById("flyoutMinImportanceVal");
  var flyoutMinConfidence    = document.getElementById("flyoutMinConfidence");
  var flyoutMinConfidenceVal = document.getElementById("flyoutMinConfidenceVal");
  var flyoutCreatedAfter     = document.getElementById("flyoutCreatedAfter");
  var flyoutIncludeArchived  = document.getElementById("flyoutIncludeArchived");

  // Settings flyout controls
  var flyoutMaxConversations = document.getElementById("flyoutMaxConversations");
  var flyoutMaxChunks        = document.getElementById("flyoutMaxChunks");
  var flyoutMaxFacts         = document.getElementById("flyoutMaxFacts");
  var flyoutLiveEverySec     = document.getElementById("flyoutLiveEverySec");
  var flyoutRenderMode       = document.getElementById("flyoutRenderMode");

  // --- Flyout management ---
  var activeFlyoutId = null;

  function openFlyout(id) {
    if (activeFlyoutId && activeFlyoutId !== id) {
      var prev = document.getElementById(activeFlyoutId);
      if (prev) prev.classList.remove("open");
    }
    activeFlyoutId = id;
    var el = document.getElementById(id);
    if (el) el.classList.add("open");
    document.body.setAttribute("data-flyout-open", "1");
    setTimeout(function() { scheduleGraphViewportSync(); }, 200);
  }

  function closeFlyout() {
    if (activeFlyoutId) {
      var el = document.getElementById(activeFlyoutId);
      if (el) el.classList.remove("open");
      activeFlyoutId = null;
    }
    document.body.removeAttribute("data-flyout-open");
    setTimeout(function() { scheduleGraphViewportSync(); }, 200);
  }

  function toggleFlyout(id) {
    if (activeFlyoutId === id) { closeFlyout(); } else { openFlyout(id); }
  }

  // --- Rail button events ---
  if (railFilterBtn) {
    railFilterBtn.addEventListener("click", function() { toggleFlyout("filterFlyout"); });
  }
  if (railSettingsBtn) {
    railSettingsBtn.addEventListener("click", function() { toggleFlyout("settingsFlyout"); });
  }
  if (railSearchBtn) {
    railSearchBtn.addEventListener("click", function() {
      if (!searchBarEl) return;
      var opening = !searchBarEl.classList.contains("open");
      searchBarEl.classList.toggle("open");
      if (opening) {
        var inp = document.getElementById("searchInput");
        if (inp) setTimeout(function() { inp.focus(); }, 180);
      }
    });
  }
  if (railLiveBtn) {
    railLiveBtn.addEventListener("click", function() {
      liveModeEl.checked = !liveModeEl.checked;
      liveModeEl.dispatchEvent(new Event("change"));
    });
  }
  if (filterFlyoutClose)   filterFlyoutClose.addEventListener("click", closeFlyout);
  if (settingsFlyoutClose) settingsFlyoutClose.addEventListener("click", closeFlyout);

  // Close flyout when clicking on graph canvas
  if (graphEl) {
    graphEl.addEventListener("click", function() {
      if (activeFlyoutId) closeFlyout();
    });
  }

  // --- Live rail button visual state ---
  function updateRailLiveBtn() {
    if (!railLiveBtn) return;
    var on = liveModeEl && liveModeEl.checked;
    railLiveBtn.classList.toggle("pulsing", !!on);
    railLiveBtn.classList.toggle("active",  !!on);
    if (statusDotEl) {
      statusDotEl.style.background = on ? "var(--ok)" : "var(--muted)";
    }
  }

  // Patch: update rail live btn whenever live mode changes
  liveModeEl.addEventListener("change", updateRailLiveBtn);

  // --- Pill sync ---
  function syncPillFromCheckbox(pill, checkbox) {
    if (pill && checkbox) pill.classList.toggle("active", !!checkbox.checked);
  }

  function setupPill(pill, checkboxEl) {
    if (!pill || !checkboxEl) return;
    syncPillFromCheckbox(pill, checkboxEl);
    pill.addEventListener("click", function() {
      checkboxEl.checked = !checkboxEl.checked;
      syncPillFromCheckbox(pill, checkboxEl);
      checkboxEl.dispatchEvent(new Event("change"));
    });
  }

  setupPill(pillConversations, showConversationsEl);
  setupPill(pillChunks,        showChunksEl);
  setupPill(pillFacts,         showFactsEl);

  // Keep pills in sync when checkboxes change externally (e.g. view preset apply)
  showConversationsEl.addEventListener("change", function() { syncPillFromCheckbox(pillConversations, showConversationsEl); });
  showChunksEl.addEventListener("change",        function() { syncPillFromCheckbox(pillChunks,        showChunksEl); });
  showFactsEl.addEventListener("change",         function() { syncPillFromCheckbox(pillFacts,         showFactsEl); });

  // --- Filter slider sync ---
  function fmtSlider(v) { return parseFloat(v || 0).toFixed(2); }

  if (flyoutMinImportance && minImportanceEl) {
    flyoutMinImportance.value = minImportanceEl.value || "0";
    if (flyoutMinImportanceVal) flyoutMinImportanceVal.textContent = fmtSlider(flyoutMinImportance.value);
    flyoutMinImportance.addEventListener("input", function() {
      if (flyoutMinImportanceVal) flyoutMinImportanceVal.textContent = fmtSlider(flyoutMinImportance.value);
      minImportanceEl.value = flyoutMinImportance.value;
      minImportanceEl.dispatchEvent(new Event("change"));
    });
    minImportanceEl.addEventListener("change", function() {
      flyoutMinImportance.value = minImportanceEl.value || "0";
      if (flyoutMinImportanceVal) flyoutMinImportanceVal.textContent = fmtSlider(flyoutMinImportance.value);
    });
  }

  if (flyoutMinConfidence && minConfidenceEl) {
    flyoutMinConfidence.value = minConfidenceEl.value || "0";
    if (flyoutMinConfidenceVal) flyoutMinConfidenceVal.textContent = fmtSlider(flyoutMinConfidence.value);
    flyoutMinConfidence.addEventListener("input", function() {
      if (flyoutMinConfidenceVal) flyoutMinConfidenceVal.textContent = fmtSlider(flyoutMinConfidence.value);
      minConfidenceEl.value = flyoutMinConfidence.value;
      minConfidenceEl.dispatchEvent(new Event("change"));
    });
    minConfidenceEl.addEventListener("change", function() {
      flyoutMinConfidence.value = minConfidenceEl.value || "0";
      if (flyoutMinConfidenceVal) flyoutMinConfidenceVal.textContent = fmtSlider(flyoutMinConfidence.value);
    });
  }

  // --- Date and archive sync ---
  if (flyoutCreatedAfter && createdAfterEl) {
    flyoutCreatedAfter.value = createdAfterEl.value || "";
    flyoutCreatedAfter.addEventListener("change", function() {
      createdAfterEl.value = flyoutCreatedAfter.value;
      createdAfterEl.dispatchEvent(new Event("change"));
    });
  }

  if (flyoutIncludeArchived && includeArchivedEl) {
    flyoutIncludeArchived.checked = includeArchivedEl.checked;
    flyoutIncludeArchived.addEventListener("change", function() {
      includeArchivedEl.checked = flyoutIncludeArchived.checked;
      includeArchivedEl.dispatchEvent(new Event("change"));
    });
  }

  // --- Settings flyout sync ---
  function syncNumInput(flyoutInput, hiddenInput) {
    if (!flyoutInput || !hiddenInput) return;
    flyoutInput.value = hiddenInput.value;
    flyoutInput.addEventListener("change", function() {
      hiddenInput.value = flyoutInput.value;
      hiddenInput.dispatchEvent(new Event("change"));
    });
    hiddenInput.addEventListener("change", function() {
      flyoutInput.value = hiddenInput.value;
    });
  }

  syncNumInput(flyoutMaxConversations, maxConversationsEl);
  syncNumInput(flyoutMaxChunks,        maxChunksEl);
  syncNumInput(flyoutMaxFacts,         maxFactsEl);
  syncNumInput(flyoutLiveEverySec,     liveEverySecEl);

  if (flyoutRenderMode && renderModeEl) {
    flyoutRenderMode.value = renderModeEl.value || "auto";
    flyoutRenderMode.addEventListener("change", function() {
      renderModeEl.value = flyoutRenderMode.value;
      renderModeEl.dispatchEvent(new Event("change"));
    });
    renderModeEl.addEventListener("change", function() {
      flyoutRenderMode.value = renderModeEl.value;
    });
  }

  // --- Initial state ---
  updateRailLiveBtn();
})();

// ===== NODE POPOVER =====
(function initNodePopover() {
  var popEl = document.getElementById("nodePopover");
  if (!popEl) return;

  var _lastPtrX = 0;
  var _lastPtrY = 0;

  // Track pointer on graph canvas for fallback positioning
  if (graphEl) {
    graphEl.addEventListener("pointerdown", function(e) {
      _lastPtrX = e.clientX;
      _lastPtrY = e.clientY;
    });
  }

  function hidePopover() {
    popEl.classList.remove("visible");
    popEl.setAttribute("aria-hidden", "true");
    popEl.style.display = "none";
  }

  function showPopover(node) {
    var raw = node.raw || node;
    var kind = String(raw.kind || "");
    var label = String(raw.label || raw.id || "");
    var text = String(raw.text || "");
    var nbrs = adjacency.get(raw.id) ? Array.from(adjacency.get(raw.id)) : [];

    var metaRows = renderMetaRows([
      ["id",           raw.id],
      ["conversation", raw.conversation_id],
      ["chunk_id",     raw.chunk_id],
      ["fact_id",      raw.fact_id],
      ["importance",   raw.importance  != null ? Number(raw.importance).toFixed(2)  : null],
      ["confidence",   raw.confidence  != null ? Number(raw.confidence).toFixed(2)  : null],
      ["created_at",   raw.created_at],
      ["neighbors",    nbrs.length],
      ["expanded",     expandedNodes.has(raw.id) ? "yes" : "no"]
    ]);

    var noteHtml = text
      ? '<div class="node-popover-note">' +
          '<div class="node-popover-note-label">Note</div>' +
          '<div class="note-block" style="max-height:110px;">' + escapeHtml(text) + '</div>' +
        '</div>'
      : "";

    popEl.innerHTML =
      '<div class="node-popover-header">' +
        '<span class="node-popover-kind ' + escapeHtml(kind) + '">' + escapeHtml(kind) + '</span>' +
        '<span class="node-popover-title" title="' + escapeHtml(label) + '">' + escapeHtml(label) + '</span>' +
        '<button class="node-popover-close" id="nodePopoverClose" title="Dismiss (Esc)">✕</button>' +
      '</div>' +
      '<div class="node-popover-body">' +
        '<div class="meta-grid">' + metaRows + '</div>' +
        noteHtml +
      '</div>';

    document.getElementById("nodePopoverClose").addEventListener("click", function(e) {
      e.stopPropagation();
      hidePopover();
    });

    // Compute anchor position: prefer graph coords, fall back to pointer
    var px = _lastPtrX;
    var py = _lastPtrY;
    if (graph && typeof graph.graph2ScreenCoords === "function" &&
        raw.x != null && raw.y != null) {
      try {
        var rect = graphEl.getBoundingClientRect();
        var sc = graph.graph2ScreenCoords(raw.x, raw.y);
        px = rect.left + sc.x;
        py = rect.top + sc.y;
      } catch (_e) {}
    }

    // Measure popover before positioning
    popEl.style.display = "flex";
    popEl.classList.remove("visible");

    requestAnimationFrame(function() {
      var pw = popEl.offsetWidth || 300;
      var ph = popEl.offsetHeight || 200;
      var m  = 12;

      // Read rail widths from CSS vars (with fallbacks)
      var railW = 56, rightW = 44;
      try {
        var cs = getComputedStyle(document.documentElement);
        var _rw = parseFloat(cs.getPropertyValue("--rail-w"));
        var _dw = parseFloat(cs.getPropertyValue("--drawer-w") ||
                             cs.getPropertyValue("--right-rail-w") || "44");
        if (_rw > 0) railW = _rw;
        if (_dw > 0) rightW = _dw;
      } catch (_e) {}

      var vw = window.innerWidth;
      var vh = window.innerHeight;

      // Center horizontally on node, drop below it
      var left = px - pw / 2;
      var top  = py + 20;

      left = Math.max(railW + m, Math.min(left, vw - rightW - pw - m));

      // Flip above if not enough room below
      if (top + ph > vh - m) top = py - ph - 20;
      top = Math.max(m, Math.min(top, vh - ph - m));

      popEl.style.left = Math.round(left) + "px";
      popEl.style.top  = Math.round(top)  + "px";
      popEl.classList.add("visible");
      popEl.setAttribute("aria-hidden", "false");
    });
  }

  // Monkey-patch renderNodeDetails to also drive the popover
  var _origRenderNodeDetails = renderNodeDetails;
  renderNodeDetails = function(node, neighbors) {
    _origRenderNodeDetails(node, neighbors);
    showPopover(node);
  };

  // Monkey-patch resetFocus to dismiss the popover
  var _origResetFocus = resetFocus;
  resetFocus = function() {
    _origResetFocus();
    hidePopover();
  };

  // Dismiss on Escape
  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape") hidePopover();
  });

  // Dismiss on click outside (capture so it fires before graph handlers)
  document.addEventListener("pointerdown", function(e) {
    if (!popEl.classList.contains("visible")) return;
    if (!popEl.contains(e.target)) hidePopover();
  }, true);
})();
