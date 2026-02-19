(function () {
  const vue = window.Vue;
  if (!vue) {
    window.MemoryGraphListApp = {
      mount: function mountWithoutVue() {
        return null;
      }
    };
    return;
  }

  const createApp = vue.createApp;
  const reactive = vue.reactive;
  const computed = vue.computed;

  function normalizeSort(value) {
    const raw = String(value == null ? "" : value).trim().toLowerCase();
    return raw === "asc" ? "asc" : "desc";
  }

  function normalizeFilterNumber(value) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return "";
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) return "";
    const clipped = Math.max(0, Math.min(1, parsed));
    return String(Math.round(clipped * 100) / 100);
  }

  function toMaybeNumber(value) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return null;
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) return null;
    return Math.max(0, Math.min(1, parsed));
  }

  function normalizeFilters(filters) {
    const src = filters && typeof filters === "object" ? filters : {};
    return {
      showConversations: src.showConversations !== false,
      showChunks: src.showChunks !== false,
      showFacts: src.showFacts !== false,
      minImportance: normalizeFilterNumber(src.minImportance),
      minConfidence: normalizeFilterNumber(src.minConfidence),
      createdAfter: String(src.createdAfter || "")
    };
  }

  function stableRows(rows) {
    if (!Array.isArray(rows)) return [];
    return rows
      .filter(function keepRow(entry) {
        return Array.isArray(entry) && entry.length === 2;
      })
      .map(function mapRow(entry) {
        return [String(entry[0]), String(entry[1])];
      });
  }

  function stableMetaBits(bits) {
    if (!Array.isArray(bits)) return [];
    return bits
      .filter(function keepBit(entry) {
        return entry != null && String(entry).trim() !== "";
      })
      .map(function mapBit(entry) {
        return String(entry);
      });
  }

  function stableItems(items) {
    if (!Array.isArray(items)) return [];
    return items
      .filter(function keepItem(item) {
        return item && typeof item === "object";
      })
      .map(function mapItem(item) {
        return {
          id: String(item.id || ""),
          kind: String(item.kind || ""),
          label: String(item.label || "(memory)"),
          note: String(item.note || ""),
          fullText: String(item.fullText || ""),
          timeLabel: String(item.timeLabel || "--"),
          dayLabel: String(item.dayLabel || "No timestamp"),
          metaRows: stableRows(item.metaRows),
          metaBits: stableMetaBits(item.metaBits),
          expanded: item.expanded === true,
          createdAt: item.createdAt == null ? "" : String(item.createdAt),
          timestamp: Number.isFinite(item.timestamp) ? Number(item.timestamp) : null
        };
      })
      .filter(function keepValid(item) {
        return item.id.length > 0;
      });
  }

  function mergeState(target, next) {
    const src = next && typeof next === "object" ? next : {};
    target.projectId = String(src.projectId || "");
    target.loading = src.loading === true;
    target.hasPayload = src.hasPayload === true;
    target.sort = normalizeSort(src.sort);
    target.search = String(src.search || "");
    target.metaText = String(src.metaText || "0 items");
    target.emptyMessage = String(src.emptyMessage || "No memories match current filters/search.");
    target.items = stableItems(src.items);
    const nextFilters = normalizeFilters(src.filters);
    target.filters.showConversations = nextFilters.showConversations;
    target.filters.showChunks = nextFilters.showChunks;
    target.filters.showFacts = nextFilters.showFacts;
    target.filters.minImportance = nextFilters.minImportance;
    target.filters.minConfidence = nextFilters.minConfidence;
    target.filters.createdAfter = nextFilters.createdAfter;
  }

  function emitFilters(state, onFiltersChange) {
    if (typeof onFiltersChange !== "function") return;
    onFiltersChange({
      showConversations: state.filters.showConversations,
      showChunks: state.filters.showChunks,
      showFacts: state.filters.showFacts,
      minImportance: toMaybeNumber(state.filters.minImportance),
      minConfidence: toMaybeNumber(state.filters.minConfidence),
      createdAfter: String(state.filters.createdAfter || "")
    });
  }

  window.MemoryGraphListApp = {
    mount: function mountTimelineApp(options) {
      const opts = options && typeof options === "object" ? options : {};
      const mountEl = opts.mountEl;
      if (!mountEl) return null;
      const state = reactive({
        projectId: "",
        loading: false,
        hasPayload: false,
        sort: "desc",
        search: "",
        metaText: "0 items",
        emptyMessage: "Load a project to see memories.",
        items: [],
        filters: normalizeFilters(null)
      });

      const app = createApp({
        setup: function setup() {
          const entries = computed(function buildEntries() {
            const rows = [];
            let currentDay = "";
            for (const item of state.items) {
              const day = item.dayLabel || "No timestamp";
              if (day !== currentDay) {
                currentDay = day;
                rows.push({
                  type: "day",
                  key: "day:" + day,
                  day: day
                });
              }
              rows.push({
                type: "item",
                key: "item:" + item.id,
                item: item
              });
            }
            return rows;
          });

          const kindCounts = computed(function buildKindCounts() {
            const counts = {
              conversation: 0,
              chunk: 0,
              fact: 0
            };
            for (const item of state.items) {
              const kind = String(item.kind || "").toLowerCase();
              if (Object.prototype.hasOwnProperty.call(counts, kind)) {
                counts[kind] += 1;
              }
            }
            return counts;
          });

          function onSearchInput(event) {
            const value = String(event && event.target ? event.target.value : "");
            state.search = value;
            if (typeof opts.onSearchChange === "function") {
              opts.onSearchChange(value);
            }
          }

          function onSortChange(event) {
            const value = normalizeSort(event && event.target ? event.target.value : "desc");
            state.sort = value;
            if (typeof opts.onSortChange === "function") {
              opts.onSortChange(value);
            }
          }

          function onFilterToggle(key, event) {
            if (!Object.prototype.hasOwnProperty.call(state.filters, key)) return;
            state.filters[key] = Boolean(event && event.target ? event.target.checked : false);
            emitFilters(state, opts.onFiltersChange);
          }

          function onFilterNumber(key, event) {
            if (!Object.prototype.hasOwnProperty.call(state.filters, key)) return;
            const value = normalizeFilterNumber(event && event.target ? event.target.value : "");
            state.filters[key] = value;
            emitFilters(state, opts.onFiltersChange);
          }

          function onFilterDate(event) {
            state.filters.createdAfter = String(event && event.target ? event.target.value : "").trim();
            emitFilters(state, opts.onFiltersChange);
          }

          function toggleExpand(itemId) {
            if (typeof opts.onToggleExpand === "function") {
              opts.onToggleExpand(String(itemId || ""));
            }
          }

          function openGraph(itemId) {
            if (typeof opts.onOpenGraph === "function") {
              opts.onOpenGraph(String(itemId || ""));
            }
          }

          function reload() {
            if (typeof opts.onLoad === "function") {
              opts.onLoad();
            }
          }

          return {
            state,
            entries,
            kindCounts,
            onSearchInput,
            onSortChange,
            onFilterToggle,
            onFilterNumber,
            onFilterDate,
            toggleExpand,
            openGraph,
            reload
          };
        },
        template: `
          <div class="timeline-app-shell">
            <div class="timeline-head">
              <div class="timeline-title">Memory Timeline</div>
              <div class="timeline-head-right">
                <button class="timeline-refresh" type="button" @click="reload">{{ state.loading ? 'Loading...' : 'Reload' }}</button>
                <select class="timeline-sort" aria-label="Timeline sort" :value="state.sort" @change="onSortChange">
                  <option value="desc">Newest</option>
                  <option value="asc">Oldest</option>
                </select>
                <div class="timeline-meta" aria-live="polite">{{ state.metaText }}</div>
              </div>
            </div>

            <div class="timeline-toolbar">
              <input
                class="timeline-search-input"
                type="search"
                placeholder="Search conversations, chunks, facts"
                :value="state.search"
                @input="onSearchInput"
              />
              <div class="timeline-filter-grid">
                <label class="timeline-toggle">
                  <input type="checkbox" :checked="state.filters.showConversations" @change="onFilterToggle('showConversations', $event)" />
                  <span>Conversations</span>
                </label>
                <label class="timeline-toggle">
                  <input type="checkbox" :checked="state.filters.showChunks" @change="onFilterToggle('showChunks', $event)" />
                  <span>Chunks</span>
                </label>
                <label class="timeline-toggle">
                  <input type="checkbox" :checked="state.filters.showFacts" @change="onFilterToggle('showFacts', $event)" />
                  <span>Facts</span>
                </label>
                <label class="timeline-input-wrap">
                  <span>Min importance</span>
                  <input
                    class="timeline-input-number"
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    :value="state.filters.minImportance"
                    @change="onFilterNumber('minImportance', $event)"
                  />
                </label>
                <label class="timeline-input-wrap">
                  <span>Min confidence</span>
                  <input
                    class="timeline-input-number"
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    :value="state.filters.minConfidence"
                    @change="onFilterNumber('minConfidence', $event)"
                  />
                </label>
                <label class="timeline-input-wrap">
                  <span>Created after</span>
                  <input class="timeline-input-date" type="date" :value="state.filters.createdAfter" @change="onFilterDate" />
                </label>
              </div>
              <div class="timeline-chip-row" aria-hidden="true">
                <span class="timeline-chip">conv {{ kindCounts.conversation }}</span>
                <span class="timeline-chip">chunk {{ kindCounts.chunk }}</span>
                <span class="timeline-chip">fact {{ kindCounts.fact }}</span>
              </div>
            </div>

            <div class="rx-list" role="list">
              <div v-if="!state.hasPayload || !state.items.length" class="timeline-empty">{{ state.emptyMessage }}</div>
              <template v-else>
                <template v-for="entry in entries" :key="entry.key">
                  <div v-if="entry.type === 'day'" class="rx-day">{{ entry.day }}</div>
                  <article v-else class="rx-card" :data-kind="entry.item.kind" role="listitem" :class="{ expanded: entry.item.expanded }">
                    <div
                      class="rx-summary"
                      role="button"
                      tabindex="0"
                      :aria-expanded="entry.item.expanded ? 'true' : 'false'"
                      @click="toggleExpand(entry.item.id)"
                      @keydown.enter.prevent="toggleExpand(entry.item.id)"
                      @keydown.space.prevent="toggleExpand(entry.item.id)"
                    >
                      <div class="rx-row">
                        <div class="rx-time">{{ entry.item.timeLabel }}</div>
                        <div class="rx-kind" :class="entry.item.kind ? entry.item.kind.toLowerCase() : ''">{{ entry.item.kind || '?' }}</div>
                      </div>
                      <div class="rx-label">{{ entry.item.label }}</div>
                      <div v-if="entry.item.note" class="rx-note">{{ entry.item.note }}</div>
                      <div v-if="entry.item.metaBits.length" class="rx-meta">{{ entry.item.metaBits.join(' | ') }}</div>
                    </div>
                    <div class="rx-expanded" v-show="entry.item.expanded">
                      <div class="rx-meta-grid">
                        <template v-for="(row, rowIdx) in entry.item.metaRows" :key="entry.item.id + ':meta:' + rowIdx">
                          <div class="rx-meta-k">{{ row[0] }}</div>
                          <div class="rx-meta-v">{{ row[1] }}</div>
                        </template>
                      </div>
                      <div v-if="entry.item.fullText" class="rx-fulltext">{{ entry.item.fullText }}</div>
                      <div class="rx-actions">
                        <button class="rx-jump" type="button" @click.stop="openGraph(entry.item.id)">Open In Graph</button>
                      </div>
                    </div>
                  </article>
                </template>
              </template>
            </div>
          </div>
        `
      });

      const appRoot = document.createElement("div");
      appRoot.className = "timeline-reactive-root";
      mountEl.appendChild(appRoot);

      try {
        app.mount(appRoot);
      } catch (err) {
        appRoot.remove();
        throw err;
      }
      mountEl.classList.add("timeline-reactive-active");

      return {
        update: function updateTimeline(nextState) {
          mergeState(state, nextState);
        },
        destroy: function destroyTimeline() {
          app.unmount();
          mountEl.classList.remove("timeline-reactive-active");
          if (appRoot.parentNode === mountEl) {
            appRoot.remove();
          }
        }
      };
    }
  };
})();
