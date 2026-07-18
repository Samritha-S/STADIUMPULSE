/**
 * StadiumPulse Dashboard Operations scripting
 */

// Mock Data matching the schemas exactly
const MOCK_ZONES = [
  {
    zone_id: "zone_east_concourse",
    zone_name: "East Concourse",
    current_count: 180,
    capacity: 800,
    forecast_count_15min: 195,
    forecast_count_30min: 210,
    status: "normal",
    connected_gates: ["gate_5", "gate_6"],
    accessible_routes: ["ramp_east_1", "elevator_east"]
  },
  {
    zone_id: "zone_north_gate3",
    zone_name: "North Concourse Gate 3",
    current_count: 580,
    capacity: 800,
    forecast_count_15min: 640,
    forecast_count_30min: 710,
    status: "watch",
    connected_gates: ["gate_3", "gate_4"],
    accessible_routes: ["ramp_north_1", "elevator_north"]
  },
  {
    zone_id: "zone_south_main",
    zone_name: "South Main Concourse",
    current_count: 740,
    capacity: 800,
    forecast_count_15min: 830,
    forecast_count_30min: 900,
    status: "critical",
    connected_gates: ["gate_1", "gate_2"],
    accessible_routes: ["ramp_south_1", "elevator_south"]
  },
  {
    zone_id: "zone_west_standing",
    zone_name: "West Standing Area",
    current_count: 320,
    capacity: 600,
    forecast_count_15min: 330,
    forecast_count_30min: 340,
    status: "normal",
    connected_gates: ["gate_7"],
    accessible_routes: ["ramp_west_1"]
  }
];

const MOCK_BRIEFS = [
  {
    zone_id: "zone_south_main",
    severity: "critical",
    summary_text: "South Main Concourse is at 92% capacity (740/800). Forecast projects 830 in 15 min, exceeding capacity by 30 persons.",
    recommended_action: "Deploy crowd management staff to gate 1 and gate 2 immediately. Activate hard PA reroute announcement directing fans to ramp_south_1.",
    suggested_reroute_zone: "ramp_south_1",
    languages_needed: ["en", "es", "fr", "ar", "pt"],
    generated_at: new Date().toISOString()
  },
  {
    zone_id: "zone_north_gate3",
    severity: "medium",
    summary_text: "North Concourse Gate 3 is at 72% capacity (580/800) and rising. Forecast projects 710 in 30 min.",
    recommended_action: "Increase monitoring at gate 3 and gate 4. Consider a soft PA announcement advising fans that ramp_north_1 offers shorter wait times.",
    suggested_reroute_zone: "ramp_north_1",
    languages_needed: ["en", "es", "fr"],
    generated_at: new Date(Date.now() - 300000).toISOString() // 5 mins ago
  },
  {
    zone_id: "zone_east_concourse",
    severity: "low",
    summary_text: "East Concourse is operating within safe parameters (22% capacity). Forecast remains stable.",
    recommended_action: "No action required. Continue routine monitoring.",
    suggested_reroute_zone: "none",
    languages_needed: ["en", "es"],
    generated_at: new Date(Date.now() - 900000).toISOString() // 15 mins ago
  }
];

// API base URL — change the port here if you run the server elsewhere
const API_BASE = "http://localhost:8088";

let isLastFetchMocked = false;

// ISOLATED DATA FETCH FUNCTIONS
// To swap between mock and live: change only these two functions.
async function fetchZoneStates() {
  try {
    const res = await fetch(`${API_BASE}/api/zones`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    isLastFetchMocked = false;
    return await res.json();
  } catch (err) {
    console.warn("[StadiumPulse] /api/zones unreachable, using mock data.", err.message);
    isLastFetchMocked = true;
    return MOCK_ZONES;
  }
}

async function fetchLatestBriefs() {
  try {
    const res = await fetch(`${API_BASE}/api/briefs`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    isLastFetchMocked = false;
    // If the server returned no briefs (all zones normal), fall back to mock
    // so the demo always has something to show in the brief feed panel.
    return data.length > 0 ? data : MOCK_BRIEFS;
  } catch (err) {
    console.warn("[StadiumPulse] /api/briefs unreachable, using mock data.", err.message);
    isLastFetchMocked = true;
    return MOCK_BRIEFS;
  }
}

// RENDER LOGIC
function renderZones(zones) {
  const container = document.getElementById("zone-grid-container");
  if (!container) return;

  if (zones.length === 0) {
    container.innerHTML = `<div class="loading-state">No zone records found.</div>`;
    return;
  }

  // Clear initial loading state
  if (container.querySelector(".loading-state")) {
    container.innerHTML = "";
  }

  // Update zone cards in place to avoid flickering and retain layout
  zones.forEach(zone => {
    const occupancyPercentage = Math.round((zone.current_count / zone.capacity) * 100);
    let statusClass = "status-badge-normal";
    if (zone.status === "watch") statusClass = "status-badge-watch";
    if (zone.status === "critical") statusClass = "status-badge-critical";

    let card = container.querySelector(`[data-zone-id="${zone.zone_id}"]`);
    if (!card) {
      card = document.createElement("article");
      card.className = "zone-card";
      card.setAttribute("data-zone-id", zone.zone_id);
      container.appendChild(card);
    }

    card.innerHTML = `
      <div class="zone-card-header">
        <h3 class="zone-name">${escapeHtml(zone.zone_name)}</h3>
        <span class="status-badge ${statusClass}">${escapeHtml(zone.status)}</span>
      </div>
      <div class="zone-stats-list">
        <div class="stat-item">
          <span class="stat-label">Current Count</span>
          <span class="stat-value">${zone.current_count}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Capacity (Limit)</span>
          <span class="stat-value">${zone.capacity} (${occupancyPercentage}%)</span>
        </div>
      </div>
      <div class="zone-forecast-bar">
        <div>Forecast 15m: <span class="forecast-val">${zone.forecast_count_15min}</span></div>
        <div>Forecast 30m: <span class="forecast-val">${zone.forecast_count_30min}</span></div>
      </div>
    `;
  });

  // Remove any cards that are no longer active
  const activeIds = new Set(zones.map(z => z.zone_id));
  container.querySelectorAll("[data-zone-id]").forEach(card => {
    const cid = card.getAttribute("data-zone-id");
    if (!activeIds.has(cid)) {
      card.remove();
    }
  });
}

const renderedBriefSignatures = new Set();

function renderBriefs(briefs) {
  const container = document.getElementById("brief-feed-container");
  if (!container) return;

  if (briefs.length === 0) {
    container.innerHTML = `<div class="loading-state">No alerts or briefings at this time.</div>`;
    return;
  }

  // Clear initial loading state
  if (container.querySelector(".loading-state")) {
    container.innerHTML = "";
  }

  const existingBriefCards = {};
  container.querySelectorAll("[data-brief-id]").forEach(card => {
    existingBriefCards[card.getAttribute("data-brief-id")] = card;
  });

  const activeSignatures = new Set();

  briefs.forEach(brief => {
    const signature = `${brief.zone_id}_${brief.severity}_${brief.summary_text.slice(0, 30)}`;
    activeSignatures.add(signature);

    const isNew = !renderedBriefSignatures.has(signature);
    if (isNew) {
      renderedBriefSignatures.add(signature);
    }

    const formattedTime = new Date(brief.generated_at).toLocaleTimeString();
    const severityLabel = brief.severity.toUpperCase();

    let card = existingBriefCards[signature];
    if (!card) {
      card = document.createElement("article");
      card.setAttribute("data-brief-id", signature);
      container.appendChild(card);
    }

    card.className = `brief-card brief-${brief.severity}` + (isNew ? " new-brief-highlight" : "");

    card.innerHTML = `
      <div class="brief-card-header">
        <span class="brief-zone-id">Zone: ${escapeHtml(brief.zone_id)}</span>
        <span class="brief-time">
          ${formattedTime}
          ${isNew ? `<span class="brief-new-badge">NEW</span>` : ''}
        </span>
      </div>
      <p class="brief-summary">
        <strong>[${severityLabel}]</strong> ${escapeHtml(brief.summary_text)}
      </p>
      <div class="brief-action-box">
        <span class="action-label">Recommended Action</span>
        <p class="brief-action-text">${escapeHtml(brief.recommended_action)}</p>
      </div>
      ${brief.suggested_reroute_zone !== "none" ? `
        <div class="brief-reroute-tag">
          Suggested Reroute: <strong>${escapeHtml(brief.suggested_reroute_zone)}</strong>
        </div>
      ` : ''}
    `;
  });

  // Remove stale briefs
  Object.keys(existingBriefCards).forEach(sig => {
    if (!activeSignatures.has(sig)) {
      existingBriefCards[sig].remove();
    }
  });

  // Maintain severity order by re-appending in order of the active list
  briefs.forEach(brief => {
    const signature = `${brief.zone_id}_${brief.severity}_${brief.summary_text.slice(0, 30)}`;
    const card = container.querySelector(`[data-brief-id="${signature}"]`);
    if (card) {
      container.appendChild(card);
    }
  });
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

let consecutiveFailures = 0;
let pollingIntervalId = null;

// Refresh triggers
async function loadDashboardData() {
  try {
    const [zones, briefs] = await Promise.all([
      fetchZoneStates(),
      fetchLatestBriefs()
    ]);

    if (isLastFetchMocked) {
      consecutiveFailures++;
    } else {
      consecutiveFailures = 0;
    }

    const liveIndicator = document.getElementById("live-indicator");
    if (liveIndicator) {
      if (consecutiveFailures >= 3) {
        liveIndicator.textContent = "● PAUSED (OFFLINE)";
        liveIndicator.classList.add("paused");
        if (pollingIntervalId) {
          clearInterval(pollingIntervalId);
          pollingIntervalId = null;
        }
      } else {
        liveIndicator.textContent = "● LIVE";
        liveIndicator.classList.remove("paused");
      }
    }

    renderZones(zones);
    renderBriefs(briefs);
  } catch (error) {
    console.error("Failed to load dashboard data:", error);
  }
}

// Clock updates
function updateClock() {
  const clockEl = document.getElementById("clock");
  if (clockEl) {
    clockEl.textContent = new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
  }
}

// Initialise on load
document.addEventListener("DOMContentLoaded", () => {
  loadDashboardData();
  
  // Real time clock updating
  updateClock();
  setInterval(updateClock, 1000);

  // Setup auto-polling every 3 seconds
  pollingIntervalId = setInterval(loadDashboardData, 3000);

  // Manual refresh hook (resets offline pauses)
  const refreshBtn = document.getElementById("refresh-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      consecutiveFailures = 0;
      const liveIndicator = document.getElementById("live-indicator");
      if (liveIndicator) {
        liveIndicator.textContent = "● LIVE";
        liveIndicator.classList.remove("paused");
      }
      loadDashboardData();
      if (!pollingIntervalId) {
        pollingIntervalId = setInterval(loadDashboardData, 3000);
      }
    });
  }
});
