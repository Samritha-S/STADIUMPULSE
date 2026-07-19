/**
 * StadiumPulse Fan Companion View scripting
 */

// Mock Data matching the schemas exactly
const MOCK_NUDGES = [
  {
    fan_id: "fan_4821",
    language: "en",
    mobility_needs: false,
    message_text: "Just a heads-up — gate 5 has shorter lines right now if you're heading out.",
    suggested_route: "gate_5",
    generated_at: new Date().toISOString()
  },
  {
    fan_id: "fan_1137",
    language: "es",
    mobility_needs: true,
    message_text: "Te recomendamos dirigirte a la rampa norte 1 para una salida más cómoda y rápida. ¡Buen partido!",
    suggested_route: "ramp_north_1",
    generated_at: new Date().toISOString()
  },
  {
    fan_id: "fan_3302",
    language: "fr",
    mobility_needs: false,
    message_text: "Pour sortir plus rapidement, nous vous conseillons de vous diriger vers la porte 2 — c'est l'itinéraire le plus fluide en ce moment.",
    suggested_route: "gate_2",
    generated_at: new Date().toISOString()
  }
];

const SCENARIOS = [
  { name: "Normal Exit Update (EN)", index: 0, urgency: "low" },
  { name: "Watch Alert - Spanish + Mobility (ES)", index: 1, urgency: "medium" },
  { name: "Critical Congestion Advisory (FR)", index: 2, urgency: "critical" }
];

let currentScenarioIndex = 0;

// API base URL — empty string uses relative paths from the current origin
const API_BASE = "";

// Fan profiles per demo scenario — match the 3 existing mock scenarios exactly:
//   0: EN / no mobility  (normal exit update)
//   1: ES / mobility     (watch alert)
//   2: FR / no mobility  (critical congestion)
const SCENARIO_FAN_PROFILES = [
  { fan_id: "fan_4821", language: "en", mobility_needs: false },
  { fan_id: "fan_1137", language: "es", mobility_needs: true  },
  { fan_id: "fan_3302", language: "fr", mobility_needs: false },
];

// ISOLATED DATA FETCH FUNCTION
// To point at the real backend: the try-block below does it automatically.
// Fallback to mock data keeps the UI working if the server is not running.
// Reads lang-select + mobility-select dropdowns if present; falls back to
// the scenario profile defaults so the existing cycle logic still works.
async function fetchNudge(index) {
  const baseProfile = SCENARIO_FAN_PROFILES[index];

  // Visual hook: read live selector values if they exist in the new HTML
  const langEl     = document.getElementById("lang-select");
  const mobilityEl = document.getElementById("mobility-select");
  const language       = langEl     ? langEl.value                      : baseProfile.language;
  const mobility_needs = mobilityEl ? mobilityEl.value === "true"        : baseProfile.mobility_needs;

  const params = new URLSearchParams({
    fan_id:         baseProfile.fan_id,
    language,
    mobility_needs,
  });
  try {
    const res = await fetch(`${API_BASE}/api/nudge?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("[StadiumPulse] /api/nudge unreachable, using mock data.", err.message);
    return MOCK_NUDGES[index];
  }
}

// RENDER LOGIC
let lastNudgeSignature = "";

function renderNudge(nudge, urgency) {
  const displayWrapper = document.getElementById("nudge-display-wrapper");
  if (!displayWrapper) return;

  const isMobility = nudge.mobility_needs;
  
  let statusColor = "var(--green)";
  let labelText = "Normal";

  if (urgency === "medium") {
    statusColor = "var(--amber)";
    labelText = "Recommended Reroute";
  } else if (urgency === "critical") {
    statusColor = "var(--red)";
    labelText = "Optimized Egress";
  }

  const signature = `${urgency}_${nudge.suggested_route}`;
  const isChanged = lastNudgeSignature && lastNudgeSignature !== signature;
  lastNudgeSignature = signature;

  const statusDot = document.getElementById("nudge-status-dot");
  if (statusDot) statusDot.style.background = statusColor;

  const statusLabel = document.getElementById("nudge-status-label");
  if (statusLabel) statusLabel.textContent = labelText;

  // The nudge message_text goes into a new <p class="nudge-message">
  displayWrapper.innerHTML = `
    <p class="nudge-message">${escapeHtml(nudge.message_text)}</p>
  `;

  const routeDisplay = document.getElementById("route-display");
  if (routeDisplay) {
    routeDisplay.textContent = escapeHtml(nudge.suggested_route);
  }

  const transitTipDisplay = document.getElementById("transit-tip-display");
  if (transitTipDisplay) {
    transitTipDisplay.textContent = nudge.transit_tip ? escapeHtml(nudge.transit_tip) : '—';
  }

  const fanLiveLabel = document.getElementById("fan-live-label");
  if (fanLiveLabel) fanLiveLabel.textContent = 'LIVE FEED';

  const fanLiveDot = document.getElementById("fan-live-dot");
  if (fanLiveDot) {
    fanLiveDot.classList.remove('offline');
    fanLiveDot.classList.add('live');
  }

  // Update transit status pill from backend broadcast
  const transitPill = document.getElementById("transit-status-pill");
  if (transitPill) {
    const ts = nudge.transit_status || "normal";
    transitPill.className = `transit-status-pill ${ts}`;
    const labels = { normal: "• NORMAL", watch: "⚠ HIGH DEMAND", critical: "✕ DISRUPTED" };
    transitPill.textContent = labels[ts] || "• NORMAL";
  }

  // Update the SVG wayfinding map whenever the nudge card updates
  renderMap(nudge.suggested_route, urgency, isMobility, isChanged);
}


// Helper: Escape HTML strings to prevent XSS
function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── SVG WAYFINDING MAP ────────────────────────────────────────────
// Generates a schematic SVG route diagram from the nudge's suggested_route.
// Called on every poll cycle from renderNudge(); updates in place with no flicker.
// animateIn — true when the route just changed, triggers pulse animation.
function renderMap(suggestedRoute, urgency, isMobility, animateIn) {
  const container = document.getElementById("map-grid-container");
  const caption   = document.getElementById("map-caption-text");
  if (!container) return;

  // ── Resolve color tokens from the CSS custom properties ──────
  // Read computed values so we stay in sync with the CSS design system.
  const style = getComputedStyle(document.documentElement);
  const colorNormal   = style.getPropertyValue("--pulse-normal").trim();
  const colorWatch    = style.getPropertyValue("--pulse-watch").trim();
  const colorCritical = style.getPropertyValue("--pulse-critical").trim();
  const colorMaroon   = style.getPropertyValue("--maroon-primary").trim();
  const colorInk      = style.getPropertyValue("--ink").trim();
  const colorMuted    = style.getPropertyValue("--ink-muted").trim();

  // Route line color tracks urgency (same logic as badge colors)
  let pathColor = colorNormal;
  if (urgency === "medium") pathColor = colorWatch;
  if (urgency === "critical") pathColor = colorCritical;

  // Friendly destination label from the route id
  const destLabel = suggestedRoute.replace(/_/g, ' ').toUpperCase();

  // ── SVG coordinate constants ─────────────────────────────────
  const W = 300, H = 140;   // viewBox dimensions
  const ORIGIN_X = 42, ORIGIN_Y = H / 2;
  const DEST_X   = W - 42,  DEST_Y   = H / 2;
  // Mid-point for a gentle arc bend
  const MID_X = W / 2, MID_Y = H / 2 - 20;

  // Solid path for standard routes; dashed for step-free / accessible routes
  const strokeDash = isMobility ? "6 4" : "none";

  // Wheelchair icon path — inlined so no external SVG dependency
  const wheelchairPath = `M${MID_X - 6},${MID_Y - 4}
    a4,4 0 1,0 8,0 a4,4 0 1,0-8,0
    m-2,6 l2-1 2,6 6,0 m-8-6 l-3,5`;

  // ── Build the SVG string ──────────────────────────────────────
  const svgNS = 'http://www.w3.org/2000/svg';

  // Use innerHTML for simplicity — no complex DOM diffing needed for this small element
  const destGroupClass = animateIn ? 'map-dest-animated' : '';
  const ringClass       = animateIn ? 'map-dest-ring-animated' : '';

  container.innerHTML = `
    <svg
      class="map-svg"
      viewBox="0 0 ${W} ${H}"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="${isMobility
        ? `Step-free accessible route to ${destLabel}`
        : `Route to ${destLabel}`}"
    >
      <!-- Visually-hidden text description for screen readers -->
      <title>${isMobility
        ? `Step-free accessible route to ${destLabel}`
        : `Optimised route from your current position to ${destLabel}`}</title>

      <!-- Route path: arc from origin to destination -->
      <path
        d="M${ORIGIN_X},${ORIGIN_Y} Q${MID_X},${MID_Y} ${DEST_X},${DEST_Y}"
        fill="none"
        stroke="${pathColor}"
        stroke-width="2"
        stroke-dasharray="${strokeDash}"
        stroke-linecap="round"
        opacity="0.85"
      />

      <!-- Origin node — fixed 'You' marker -->
      <circle cx="${ORIGIN_X}" cy="${ORIGIN_Y}" r="9"
        fill="${colorMaroon}" opacity="0.9" />
      <circle cx="${ORIGIN_X}" cy="${ORIGIN_Y}" r="9"
        fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="1.5" />
      <text x="${ORIGIN_X}" y="${ORIGIN_Y + 22}"
        class="map-node-text" text-anchor="middle">YOU</text>

      <!-- Destination node group — animated on route change -->
      <g class="${destGroupClass}" style="transform-origin: ${DEST_X}px ${DEST_Y}px;">
        <!-- Pulse ring (animates out on arrival) -->
        ${animateIn ? `<circle cx="${DEST_X}" cy="${DEST_Y}" r="9"
          fill="none" stroke="${pathColor}" stroke-width="1.5"
          class="${ringClass}" opacity="0" />` : ''}

        <!-- Destination fill circle -->
        <circle cx="${DEST_X}" cy="${DEST_Y}" r="10"
          fill="${pathColor}" opacity="0.9" />
        <circle cx="${DEST_X}" cy="${DEST_Y}" r="10"
          fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="1.5" />

        <!-- Destination route label -->
        <text x="${DEST_X}" y="${DEST_Y + 24}"
          class="map-dest-text" text-anchor="middle">
          ${destLabel.length > 14 ? destLabel.slice(0, 13) + '…' : destLabel}
        </text>
      </g>

      <!-- Mobility indicator: small wheelchair icon mid-path for step-free routes -->
      ${isMobility ? `
        <g transform="translate(${MID_X - 8}, ${MID_Y - 18})" aria-hidden="true">
          <rect width="16" height="16" rx="3"
            fill="rgba(10,10,11,0.75)" />
          <text x="8" y="12" text-anchor="middle"
            font-size="10" fill="${colorMuted}">♿</text>
        </g>
      ` : ''}
    </svg>
  `;

  // Update the text caption beneath the map
  if (caption) {
    caption.textContent = isMobility
      ? `Step-free route → ${destLabel}`
      : `Route → ${destLabel}`;
  }
}

// updateClock — kept as no-op stub so any legacy callers don't error
function updateClock() {}

let isInitialLoad = true;

// Load Nudge scenario
async function loadScenario(index, isPoll = false) {
  const wrapper = document.getElementById("nudge-display-wrapper");
  if (isInitialLoad && !isPoll) {
    wrapper.innerHTML = `<div class="nudge-loading">Receiving route updates...</div>`;
    isInitialLoad = false;
  }

  try {
    const nudge = await fetchNudge(index);
    const scenario = SCENARIOS[index];
    renderNudge(nudge, scenario.urgency);
    
    // Update scenario indicator text
    document.getElementById("scenario-info-text").textContent = `Scenario: ${scenario.name}`;
  const statusLabel = document.getElementById("nudge-status-label");
  if (statusLabel) statusLabel.textContent = labelText;

  // The nudge message_text goes into a new <p class="nudge-message">
  displayWrapper.innerHTML = `
    <p class="nudge-message">${escapeHtml(nudge.message_text)}</p>
  `;

  const routeDisplay = document.getElementById("route-display");
  if (routeDisplay) {
    routeDisplay.textContent = escapeHtml(nudge.suggested_route);
  }

  const transitTipDisplay = document.getElementById("transit-tip-display");
  if (transitTipDisplay) {
    transitTipDisplay.textContent = nudge.transit_tip ? escapeHtml(nudge.transit_tip) : '—';
  }

  const fanLiveLabel = document.getElementById("fan-live-label");
  if (fanLiveLabel) fanLiveLabel.textContent = 'LIVE FEED';

  const fanLiveDot = document.getElementById("fan-live-dot");
  if (fanLiveDot) {
    fanLiveDot.classList.remove('offline');
    fanLiveDot.classList.add('live');
  }

  // Update transit status pill from backend broadcast
  const transitPill = document.getElementById("transit-status-pill");
  if (transitPill) {
    const ts = nudge.transit_status || "normal";
    transitPill.className = `transit-status-pill ${ts}`;
    const labels = { normal: "• NORMAL", watch: "⚠ HIGH DEMAND", critical: "✕ DISRUPTED" };
    transitPill.textContent = labels[ts] || "• NORMAL";
  }

  // Update the SVG wayfinding map whenever the nudge card updates
  renderMap(nudge.suggested_route, urgency, isMobility, isChanged);
}


// Helper: Escape HTML strings to prevent XSS
function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── SVG WAYFINDING MAP ────────────────────────────────────────────
// Generates a schematic SVG route diagram from the nudge's suggested_route.
// Called on every poll cycle from renderNudge(); updates in place with no flicker.
// animateIn — true when the route just changed, triggers pulse animation.
function renderMap(suggestedRoute, urgency, isMobility, animateIn) {
  const container = document.getElementById("map-grid-container");
  const caption   = document.getElementById("map-caption-text");
  if (!container) return;

  // ── Resolve color tokens from the CSS custom properties ──────
  // Read computed values so we stay in sync with the CSS design system.
  const style = getComputedStyle(document.documentElement);
  const colorNormal   = style.getPropertyValue("--pulse-normal").trim();
  const colorWatch    = style.getPropertyValue("--pulse-watch").trim();
  const colorCritical = style.getPropertyValue("--pulse-critical").trim();
  const colorMaroon   = style.getPropertyValue("--maroon-primary").trim();
  const colorInk      = style.getPropertyValue("--ink").trim();
  const colorMuted    = style.getPropertyValue("--ink-muted").trim();

  // Route line color tracks urgency (same logic as badge colors)
  let pathColor = colorNormal;
  if (urgency === "medium") pathColor = colorWatch;
  if (urgency === "critical") pathColor = colorCritical;

  // Friendly destination label from the route id
  const destLabel = suggestedRoute.replace(/_/g, ' ').toUpperCase();

  // ── SVG coordinate constants ─────────────────────────────────
  const W = 300, H = 140;   // viewBox dimensions
  const ORIGIN_X = 42, ORIGIN_Y = H / 2;
  const DEST_X   = W - 42,  DEST_Y   = H / 2;
  // Mid-point for a gentle arc bend
  const MID_X = W / 2, MID_Y = H / 2 - 20;

  // Solid path for standard routes; dashed for step-free / accessible routes
  const strokeDash = isMobility ? "6 4" : "none";

  // Wheelchair icon path — inlined so no external SVG dependency
  const wheelchairPath = `M${MID_X - 6},${MID_Y - 4}
    a4,4 0 1,0 8,0 a4,4 0 1,0-8,0
    m-2,6 l2-1 2,6 6,0 m-8-6 l-3,5`;

  // ── Build the SVG string ──────────────────────────────────────
  const svgNS = 'http://www.w3.org/2000/svg';

  // Use innerHTML for simplicity — no complex DOM diffing needed for this small element
  const destGroupClass = animateIn ? 'map-dest-animated' : '';
  const ringClass       = animateIn ? 'map-dest-ring-animated' : '';

  container.innerHTML = `
    <svg
      class="map-svg"
      viewBox="0 0 ${W} ${H}"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="${isMobility
        ? `Step-free accessible route to ${destLabel}`
        : `Route to ${destLabel}`}"
    >
      <!-- Visually-hidden text description for screen readers -->
      <title>${isMobility
        ? `Step-free accessible route to ${destLabel}`
        : `Optimised route from your current position to ${destLabel}`}</title>

      <!-- Route path: arc from origin to destination -->
      <path
        d="M${ORIGIN_X},${ORIGIN_Y} Q${MID_X},${MID_Y} ${DEST_X},${DEST_Y}"
        fill="none"
        stroke="${pathColor}"
        stroke-width="2"
        stroke-dasharray="${strokeDash}"
        stroke-linecap="round"
        opacity="0.85"
      />

      <!-- Origin node — fixed 'You' marker -->
      <circle cx="${ORIGIN_X}" cy="${ORIGIN_Y}" r="9"
        fill="${colorMaroon}" opacity="0.9" />
      <circle cx="${ORIGIN_X}" cy="${ORIGIN_Y}" r="9"
        fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="1.5" />
      <text x="${ORIGIN_X}" y="${ORIGIN_Y + 22}"
        class="map-node-text" text-anchor="middle">YOU</text>

      <!-- Destination node group — animated on route change -->
      <g class="${destGroupClass}" style="transform-origin: ${DEST_X}px ${DEST_Y}px;">
        <!-- Pulse ring (animates out on arrival) -->
        ${animateIn ? `<circle cx="${DEST_X}" cy="${DEST_Y}" r="9"
          fill="none" stroke="${pathColor}" stroke-width="1.5"
          class="${ringClass}" opacity="0" />` : ''}

        <!-- Destination fill circle -->
        <circle cx="${DEST_X}" cy="${DEST_Y}" r="10"
          fill="${pathColor}" opacity="0.9" />
        <circle cx="${DEST_X}" cy="${DEST_Y}" r="10"
          fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="1.5" />

        <!-- Destination route label -->
        <text x="${DEST_X}" y="${DEST_Y + 24}"
          class="map-dest-text" text-anchor="middle">
          ${destLabel.length > 14 ? destLabel.slice(0, 13) + '…' : destLabel}
        </text>
      </g>

      <!-- Mobility indicator: small wheelchair icon mid-path for step-free routes -->
      ${isMobility ? `
        <g transform="translate(${MID_X - 8}, ${MID_Y - 18})" aria-hidden="true">
          <rect width="16" height="16" rx="3"
            fill="rgba(10,10,11,0.75)" />
          <text x="8" y="12" text-anchor="middle"
            font-size="10" fill="${colorMuted}">♿</text>
        </g>
      ` : ''}
    </svg>
  `;

  // Update the text caption beneath the map
  if (caption) {
    caption.textContent = isMobility
      ? `Step-free route → ${destLabel}`
      : `Route → ${destLabel}`;
  }
}

// updateClock — kept as no-op stub so any legacy callers don't error
function updateClock() {}

let isInitialLoad = true;

// Load Nudge scenario
async function loadScenario(index, isPoll = false) {
  const wrapper = document.getElementById("nudge-display-wrapper");
  if (isInitialLoad && !isPoll) {
    wrapper.innerHTML = `<div class="nudge-loading">Receiving route updates...</div>`;
    isInitialLoad = false;
  }

  try {
    const nudge = await fetchNudge(index);
    const scenario = SCENARIOS[index];
    renderNudge(nudge, scenario.urgency);
    
    // Update scenario indicator text
    document.getElementById("scenario-info-text").textContent = `Scenario: ${scenario.name}`;
  } catch (error) {
    console.error("Failed to load scenario nudge:", error);
  }
}

let pollingIntervalId = null;

// Lifecycle Hooks
document.addEventListener("DOMContentLoaded", () => {
  loadScenario(currentScenarioIndex);

  // Poll fetchNudge every 3 seconds using the current active scenario profile
  pollingIntervalId = setInterval(() => {
    loadScenario(currentScenarioIndex, true);
  }, 3000);

  // Next scenario cycle — also syncs selectors to match the new profile
  const nextBtn = document.getElementById("next-nudge-btn");
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      currentScenarioIndex = (currentScenarioIndex + 1) % MOCK_NUDGES.length;
      // Sync dropdowns to new profile so displayed state matches what will be fetched
      const newProfile = SCENARIO_FAN_PROFILES[currentScenarioIndex];
      const langEl     = document.getElementById("lang-select");
      const mobilityEl = document.getElementById("mobility-select");
      if (langEl)     langEl.value     = newProfile.language;
      if (mobilityEl) mobilityEl.value = String(newProfile.mobility_needs);
      isInitialLoad = true;
      loadScenario(currentScenarioIndex);
    });
  }

  // ── Accessibility toggle controls ─────────────────────────────────

  /**
   * Generic toggle handler: updates aria-checked, adds/removes a class on <html>
   * and persists the preference to sessionStorage.
   */
  function bindToggle(id, htmlClass, storageKey) {
    const btn = document.getElementById(id);
    if (!btn) return;

    // Restore persisted state
    const stored = sessionStorage.getItem(storageKey);
    if (stored === "true") {
      btn.setAttribute("aria-checked", "true");
      btn.classList.add("is-on");
      document.documentElement.classList.add(htmlClass);
    }

    btn.addEventListener("click", () => {
      const isOn = btn.getAttribute("aria-checked") === "true";
      const next = !isOn;
      btn.setAttribute("aria-checked", String(next));
      btn.classList.toggle("is-on", next);
      document.documentElement.classList.toggle(htmlClass, next);
      sessionStorage.setItem(storageKey, String(next));
    });
  }

  bindToggle("high-contrast-toggle", "a11y-high-contrast",  "sp_high_contrast");
  bindToggle("reduce-motion-toggle",  "a11y-reduce-motion",  "sp_reduce_motion");
  bindToggle("screen-reader-toggle",  "a11y-screen-reader",  "sp_screen_reader");

  // Font size select
  const fontSizeEl = document.getElementById("font-size-select");
  if (fontSizeEl) {
    // Restore persisted value
    const storedSize = sessionStorage.getItem("sp_font_size");
    if (storedSize) {
      fontSizeEl.value = storedSize;
      document.documentElement.setAttribute("data-font-size", storedSize);
    }
    fontSizeEl.addEventListener("change", () => {
      document.documentElement.setAttribute("data-font-size", fontSizeEl.value);
      sessionStorage.setItem("sp_font_size", fontSizeEl.value);
    });
  }

  // Screen-reader mode: announce nudge updates via a dedicated live region
  function maybeAnnounce(text) {
    if (!document.documentElement.classList.contains("a11y-screen-reader")) return;
    let region = document.getElementById("sr-announce-region");
    if (!region) {
      region = document.createElement("div");
      region.id = "sr-announce-region";
      region.setAttribute("aria-live", "assertive");
      region.setAttribute("aria-atomic", "true");
      region.className = "sr-only";
      document.body.appendChild(region);
    }
    region.textContent = "";
    // Delay to ensure screen readers pick up the change
    setTimeout(() => { region.textContent = text; }, 50);
  }

  // Expose so renderNudge can call it
  window.spAnnounce = maybeAnnounce;

  // ── Coordinated Dashboard & Tab Navigation ──────────────────────────
  const TABS = [
    { key: "dashboard", panel: "tab-panel-dashboard" },
    { key: "updates",   panel: "tab-panel-updates"   },
    { key: "route",     panel: "tab-panel-route"     },
    { key: "crowd",     panel: "tab-panel-crowd"     },
    { key: "transit",   panel: "tab-panel-transit"   },
    { key: "report",    panel: "tab-panel-report"    },
    { key: "info",      panel: "tab-panel-info"      },
  ];

  function switchTab(activeKey) {
    TABS.forEach(({ key, panel }) => {
      const panelEl = document.getElementById(panel);
      const isActive = key === activeKey;

      // Sync active state on all buttons targeting this tab (bottom nav + sidebar items)
      const btnEls = document.querySelectorAll(`[data-tab="${key}"], .menu-item[data-tab="${key}"]`);
      btnEls.forEach(btnEl => {
        btnEl.classList.toggle("active", isActive);
        btnEl.setAttribute("aria-selected", String(isActive));
      });

      if (panelEl) {
        panelEl.classList.toggle("is-active", isActive);
        if (isActive) {
          panelEl.removeAttribute("hidden");
        } else {
          panelEl.setAttribute("hidden", "");
        }
      }
    });
  }

  // Bind click listeners to all tab buttons (both bottom nav and sidebar menu items)
  document.querySelectorAll("[data-tab]").forEach(btnEl => {
    btnEl.addEventListener("click", () => {
      const targetTab = btnEl.getAttribute("data-tab");
      switchTab(targetTab);
    });
  });

  // ── Live Integrated Dashboard & Gate Stats Polling ─────────────────
  async function updateDashboardStatsAndGates() {
    try {
      const [zonesRes, reportsRes] = await Promise.all([
        fetch(`${API_BASE}/api/zones`).then(r => r.ok ? r.json() : []),
        fetch(`${API_BASE}/api/reports`).then(r => r.ok ? r.json() : [])
      ]);

      if (zonesRes && zonesRes.length > 0) {
        // 1. Total Attendance
        const totalAttendance = zonesRes.reduce((acc, z) => acc + z.current_count, 0);
        const totalCapacity = zonesRes.reduce((acc, z) => acc + z.capacity, 0);
        const attValEl = document.querySelector(".attendance-highlight .stat-box-value");
        if (attValEl) attValEl.textContent = totalAttendance.toLocaleString();
        const attSubEl = document.querySelector(".attendance-highlight .stat-box-sub");
        if (attSubEl) attSubEl.textContent = `of ${totalCapacity.toLocaleString()} capacity`;

        // 2. Critical Crowd Zones
        const criticalZones = zonesRes.filter(z => z.status === "critical");
        const critValEl = document.getElementById("stat-critical-zones-value");
        if (critValEl) critValEl.textContent = criticalZones.length;
        const critSubEl = document.getElementById("stat-monitored-zones-sub");
        if (critSubEl) critSubEl.textContent = `${zonesRes.length} zones monitored`;

        // 3. Populate Gate Crowd Levels widget
        const gateListEl = document.getElementById("gates-dashboard-list");
        if (gateListEl) {
          // Map zone records to gate display rows
          const displayZones = zonesRes.slice(0, 4);
          gateListEl.innerHTML = displayZones.map(zone => {
            const occupancyPercentage = Math.round((zone.current_count / zone.capacity) * 100);
            const badgeClass = zone.status === "critical" ? "badge-critical" : zone.status === "watch" ? "badge-watch" : "badge-normal";
            const statusText = zone.status === "critical" ? "Critical" : zone.status === "watch" ? "Moderate" : "Low";
            
            // Estimate wait time based on occupancy percentage
            let waitTime = "3 min wait";
            if (zone.status === "critical") {
              waitTime = `${Math.round(20 + (occupancyPercentage - 90) * 0.5)} min wait`;
            } else if (zone.status === "watch") {
              waitTime = `${Math.round(7 + (occupancyPercentage - 70) * 0.4)} min wait`;
            }

            // Format zone name to shorter Gate label if possible
            let gateName = zone.zone_name.split("–")[1] || zone.zone_name;
            gateName = gateName.trim();
            
            return `
              <div class="gate-row-item">
                <div class="gate-meta">
                  <span class="gate-code-name">${escapeHtml(gateName)}</span>
                  <span class="gate-occupancy-fraction">${zone.current_count.toLocaleString()} / ${zone.capacity.toLocaleString()}</span>
                </div>
                <div class="gate-status-group">
                  <span class="gate-badge ${badgeClass}">${statusText}</span>
                  <span class="gate-wait-time">${waitTime}</span>
                </div>
              </div>
            `;
          }).join('');
        }

        // 4. Render Crowd Intelligence tab panel cards
        const crowdGridEl = document.getElementById("crowd-zones-grid");
        if (crowdGridEl) {
          crowdGridEl.innerHTML = zonesRes.map(zone => {
            const pct = Math.round((zone.current_count / zone.capacity) * 100);
            return `
              <div class="stat-box-card" style="gap: 0.5rem;">
                <div class="stat-box-header">
                  <span class="gate-code-name" style="font-size: 0.9rem;">${escapeHtml(zone.zone_name)}</span>
                  <span class="gate-badge ${zone.status === "critical" ? "badge-critical" : zone.status === "watch" ? "badge-watch" : "badge-normal"}">${zone.status.toUpperCase()}</span>
                </div>
                <div class="stat-box-value" style="font-size: 1.5rem;">${pct}%</div>
                <div class="stat-box-title" style="font-size: 0.75rem; color: var(--ink-muted);">${zone.current_count.toLocaleString()} / ${zone.capacity.toLocaleString()}</div>
                <div style="height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px; overflow: hidden; margin-top: 0.25rem;">
                  <div style="height: 100%; width: ${Math.min(pct, 100)}%; background: ${zone.status === 'critical' ? 'var(--red)' : zone.status === 'watch' ? 'var(--amber)' : 'var(--green)'};"></div>
                </div>
              </div>
            `;
          }).join('');
        }
      }

      // 5. Active Incidents display
      const incidentCount = reportsRes ? reportsRes.length : 0;
      const activeIncidents = incidentCount + (zonesRes ? zonesRes.filter(z => z.status !== "normal").length : 0);
      
      const incidentValEl = document.getElementById("stat-incidents-value");
      if (incidentValEl) incidentValEl.textContent = activeIncidents;
      const incidentSubEl = document.getElementById("stat-incidents-sub");
      if (incidentSubEl) incidentSubEl.textContent = `${incidentCount} critical reports`;

      const topPillEl = document.getElementById("alert-incident-pill");
      const countLabelEl = document.getElementById("alert-count-label");
      if (topPillEl && countLabelEl) {
        if (activeIncidents > 0) {
          countLabelEl.textContent = `${activeIncidents} Active Incidents`;
          topPillEl.style.display = "flex";
        } else {
          topPillEl.style.display = "none";
        }
      }
    } catch (error) {
      console.warn("Failed to load dashboard dynamic stats:", error);
    }
  }

  // ── Incident Form submission handler ────────────────────────────────
  const incidentForm = document.getElementById("incident-form");
  const reportFeedback = document.getElementById("report-submission-feedback");

  if (incidentForm) {
    incidentForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const rawText = document.getElementById("raw_text").value.trim();
      if (!rawText) return;

      const submitBtn = document.getElementById("submit-report-btn");
      submitBtn.disabled = true;
      submitBtn.textContent = "Dispatching...";
      reportFeedback.innerHTML = "";

      try {
        const res = await fetch(`${API_BASE}/api/report`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ raw_text: rawText })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        reportFeedback.innerHTML = `
          <div class="triage-success-display">
            <div class="triage-success-header">
              <span>✓ Dispatched Successfully</span>
            </div>
            <p style="font-size: 0.85rem; color: var(--ink-secondary);">${escapeHtml(data.structured_summary)}</p>
            <div class="triage-details-list">
              <span class="triage-badge" style="color: ${data.severity === 'critical' ? 'var(--red)' : data.severity === 'high' ? 'var(--amber)' : 'var(--green)'}">${data.severity}</span>
              <span class="triage-badge">${data.category}</span>
              <span class="triage-badge">${data.detected_language}</span>
            </div>
          </div>
        `;
        document.getElementById("raw_text").value = "";
        updateDashboardStatsAndGates();
      } catch (err) {
        reportFeedback.innerHTML = `<p style="color: var(--red); font-size: 0.85rem; margin-top: 1rem;">✕ Submission failed: ${escapeHtml(err.message)}</p>`;
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Dispatch Report ➔";
      }
    });
  }

  // Initialise layout for whichever screen size we start on
  switchTab("dashboard");
  updateDashboardStatsAndGates();

  // Poll fetchNudge & dashboard statistics every 3 seconds
  pollingIntervalId = setInterval(() => {
    loadScenario(currentScenarioIndex, true);
    updateDashboardStatsAndGates();
  }, 3000);
});

