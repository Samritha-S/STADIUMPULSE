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
    generated_at: new Date(Date.now() - 300000).toISOString()
  },
  {
    zone_id: "zone_east_concourse",
    severity: "low",
    summary_text: "East Concourse is operating within safe parameters (22% capacity). Forecast remains stable.",
    recommended_action: "No action required. Continue routine monitoring.",
    suggested_reroute_zone: "none",
    languages_needed: ["en", "es"],
    generated_at: new Date(Date.now() - 900000).toISOString()
  }
];

// API base URL — empty string uses relative paths from the current origin
const API_BASE = "";

let isLastFetchMocked = false;

// ISOLATED DATA FETCH FUNCTIONS
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
    return data.length > 0 ? data : MOCK_BRIEFS;
  } catch (err) {
    console.warn("[StadiumPulse] /api/briefs unreachable, using mock data.", err.message);
    isLastFetchMocked = true;
    return MOCK_BRIEFS;
  }
}

async function fetchVolunteerReports() {
  try {
    const res = await fetch(`${API_BASE}/api/reports`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("[StadiumPulse] /api/reports unreachable.", err.message);
    return [];
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

  if (container.querySelector(".loading-state")) {
    container.innerHTML = "";
  }

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
      card.setAttribute("data-status", zone.status);
      container.appendChild(card);
    }

    card.setAttribute("data-status", zone.status);

    // Occupancy ring SVG
    const radius = 24;
    const circumference = 2 * Math.PI * radius;
    const ringColor = zone.status === 'critical' ? 'var(--red)' : zone.status === 'watch' ? 'var(--amber)' : 'var(--green)';
    const dashoffset = circumference * (1 - Math.min(occupancyPercentage, 100) / 100);

    card.innerHTML = `
      <div class="zone-card-header">
        <div class="zone-card-left">
          <h3 class="zone-name">${escapeHtml(zone.zone_name)}</h3>
          <span class="status-badge ${statusClass}">${escapeHtml(zone.status)}</span>
          <div class="capacity-bar-track"><div class="capacity-bar-fill" data-pct="${occupancyPercentage}" style="width:${Math.min(occupancyPercentage,100)}%"></div></div>
        </div>
        <div class="zone-ring" aria-label="${occupancyPercentage}% occupancy" role="img">
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none" aria-hidden="true">
            <circle cx="28" cy="28" r="${radius}" stroke="rgba(255,255,255,0.06)" stroke-width="4" fill="none"/>
            <circle cx="28" cy="28" r="${radius}" stroke="${ringColor}" stroke-width="4" fill="none"
              stroke-dasharray="${circumference.toFixed(2)}"
              stroke-dashoffset="${dashoffset.toFixed(2)}"
              stroke-linecap="round"
              transform="rotate(-90 28 28)"
              class="ring-arc"/>
          </svg>
          <span class="ring-pct">${occupancyPercentage}%</span>
        </div>
      </div>
      <div class="zone-forecast-bar">
        <div>15m: <span class="forecast-val">${zone.forecast_count_15min.toLocaleString()}</span></div>
        <div>30m: <span class="forecast-val">${zone.forecast_count_30min.toLocaleString()}</span></div>
        <div class="zone-capacity-note">${zone.current_count.toLocaleString()} / ${zone.capacity.toLocaleString()}</div>
      </div>
    `;
  });

  const activeIds = new Set(zones.map(z => z.zone_id));
  container.querySelectorAll("[data-zone-id]").forEach(card => {
    if (!activeIds.has(card.getAttribute("data-zone-id"))) card.remove();
  });
}

const renderedBriefSignatures = new Set();

function renderCriticalRail(briefs) {
  const rail = document.getElementById('critical-alert-rail');
  if (!rail) return;
  const criticals = briefs.filter(b => b.severity === 'critical');
  if (criticals.length === 0) {
    rail.style.display = 'none';
    return;
  }
  rail.style.display = 'flex';
  rail.innerHTML = criticals.map(b => `
    <article class="rail-card" role="alert">
      <span class="rail-zone">${escapeHtml(b.zone_id.replace('zone_','').replace(/_/g,' ').toUpperCase())}</span>
      <p class="rail-summary">${escapeHtml(b.summary_text.slice(0, 120))}${b.summary_text.length > 120 ? '…' : ''}</p>
      <span class="rail-time">${new Date(b.generated_at).toLocaleTimeString()}</span>
    </article>
  `).join('');
}

function renderBriefs(briefs, reports = []) {
  renderCriticalRail(briefs);
  
  const container = document.getElementById("brief-feed-container");
  if (!container) return;

  const combined = [];
  briefs.forEach(b => {
    combined.push({
      id: `auto_${b.zone_id}_${b.severity}_${b.summary_text.slice(0, 20)}`,
      type: "auto",
      severity: b.severity,
      generated_at: b.generated_at,
      title: `Zone: ${b.zone_id.replace("zone_", "").replace(/_/g, " ").toUpperCase()}`,
      summary: b.summary_text,
      recommended: b.recommended_action,
      reroute: b.suggested_reroute_zone,
      languages: b.languages_needed
    });
  });

  reports.forEach(r => {
    const zoneLabel = r.zone_id ? ` (Zone: ${r.zone_id.replace("zone_", "").replace(/_/g, " ").toUpperCase()})` : " (Location Unspecified)";
    combined.push({
      id: `vol_${r.report_id}`,
      type: "volunteer",
      severity: r.severity,
      generated_at: r.generated_at,
      title: `Volunteer Report: ${r.report_id.toUpperCase()}${zoneLabel}`,
      summary: r.structured_summary,
      raw_text: r.raw_text,
      category: r.category,
      lang: r.detected_language
    });
  });

  combined.sort((a, b) => new Date(b.generated_at) - new Date(a.generated_at));

  if (combined.length === 0) {
    container.innerHTML = `<div class="loading-state">No alerts or briefings at this time.</div>`;
    return;
  }

  if (container.querySelector(".loading-state")) {
    container.innerHTML = "";
  }

  const existingBriefCards = {};
  container.querySelectorAll("[data-brief-id]").forEach(card => {
    existingBriefCards[card.getAttribute("data-brief-id")] = card;
  });

  const activeSignatures = new Set();

  combined.forEach(item => {
    const signature = item.id;
    activeSignatures.add(signature);

    const isNew = !renderedBriefSignatures.has(signature);
    if (isNew) renderedBriefSignatures.add(signature);

    const formattedTime = new Date(item.generated_at).toLocaleTimeString();
    const severityLabel = item.severity.toUpperCase();
    const typeBadge = item.type === "auto" ? "badge-auto" : "badge-vol";
    const typeLabel = item.type === "auto" ? "AUTO ALERT" : "FIELD REPORT";

    let card = existingBriefCards[signature];
    if (!card) {
      card = document.createElement("article");
      card.setAttribute("data-brief-id", signature);
      container.appendChild(card);
    }

    card.className = `brief-card brief-${item.severity}` + (isNew ? " new-brief-highlight" : "");

    let innerHTML = `
      <div class="brief-card-header">
        <span class="brief-zone-id">${escapeHtml(item.title)}</span>
        <div style="display: flex; gap: 0.5rem; align-items: center;">
          <span class="badge ${typeBadge}">${typeLabel}</span>
          <span class="brief-time">
            ${formattedTime}
            ${isNew ? `<span class="brief-new-badge">NEW</span>` : ''}
          </span>
        </div>
      </div>
      <p class="brief-summary">
        <strong>[${severityLabel}]</strong> ${escapeHtml(item.summary)}
      </p>
    `;

    if (item.type === "auto") {
      innerHTML += `
        <div class="brief-action-box">
          <span class="action-label">Recommended Action</span>
          <p class="brief-action-text">${escapeHtml(item.recommended)}</p>
        </div>
        ${item.reroute !== "none" ? `
          <div class="brief-reroute-tag">
            Suggested Reroute: <strong>${escapeHtml(item.reroute)}</strong>
          </div>
        ` : ''}
      `;
    } else {
      innerHTML += `
        <div class="brief-action-box" style="margin-top: 0.5rem; padding: 0.5rem 0.75rem;">
          <span class="action-label" style="font-size: 0.65rem; color: var(--ink-muted);">Original Text (${item.lang.toUpperCase()})</span>
          <p class="brief-action-text" style="font-size: 0.8rem; font-style: italic; color: var(--ink); margin-top: 0.2rem;">"${escapeHtml(item.raw_text)}"</p>
        </div>
        <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
          <span class="badge badge-ops" style="font-size: 0.6rem; opacity: 0.8;">Category: ${escapeHtml(item.category.toUpperCase())}</span>
        </div>
      `;
    }

    card.innerHTML = innerHTML;
  });

  Object.keys(existingBriefCards).forEach(sig => {
    if (!activeSignatures.has(sig)) existingBriefCards[sig].remove();
  });

  combined.forEach(item => {
    const card = container.querySelector(`[data-brief-id="${item.id}"]`);
    if (card) container.appendChild(card);
  });
}

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

async function loadDashboardData() {
  try {
    const [zones, briefs, reports] = await Promise.all([
      fetchZoneStates(),
      fetchLatestBriefs(),
      fetchVolunteerReports()
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

    const zonesCountEl = document.getElementById("stat-zones-count");
    if (zonesCountEl) zonesCountEl.textContent = zones.length;
    const alertsCountEl = document.getElementById("stat-alerts-count");
    if (alertsCountEl) {
      const activeAlerts = briefs.filter(b => b.severity !== "low").length + reports.length;
      alertsCountEl.textContent = activeAlerts;
    }

    renderZones(zones);
    renderBriefs(briefs, reports);

  } catch (error) {
    console.error("Failed to load dashboard data:", error);
  }
}

function updateClock() {
  const clockEl = document.getElementById("clock");
  if (clockEl) {
    clockEl.textContent = new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadDashboardData();
  updateClock();
  setInterval(updateClock, 1000);
  pollingIntervalId = setInterval(loadDashboardData, 3000);

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

  // ── Transit Alert Console Logic ──
  const transitForm = document.getElementById("transit-alert-form");
  const transitStatusSelect = document.getElementById("transit-status-select");
  const transitCustomTip = document.getElementById("transit-custom-tip");
  const clearTransitBtn = document.getElementById("clear-transit-btn");
  const transitFeedback = document.getElementById("transit-console-feedback");

  // Load current active transit alert at startup
  fetch(`${API_BASE}/api/transit-alert`)
    .then(res => res.json())
    .then(data => {
      if (transitStatusSelect && data.transit_status) transitStatusSelect.value = data.transit_status;
      if (transitCustomTip && data.custom_tip) transitCustomTip.value = data.custom_tip;
    })
    .catch(err => console.warn("Failed to load startup transit alert:", err));

  if (transitForm) {
    transitForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const status = transitStatusSelect.value;
      const tip = transitCustomTip.value.trim();

      try {
        const res = await fetch(`${API_BASE}/api/transit-alert`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ transit_status: status, custom_tip: tip })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        transitFeedback.textContent = "✓ Advisory broadcasted successfully!";
        transitFeedback.style.color = "var(--green)";
        setTimeout(() => { transitFeedback.textContent = ""; }, 3000);
      } catch (err) {
        transitFeedback.textContent = "✕ Failed to broadcast: " + err.message;
        transitFeedback.style.color = "var(--red)";
      }
    });
  }

  if (clearTransitBtn) {
    clearTransitBtn.addEventListener("click", async () => {
      if (transitCustomTip) transitCustomTip.value = "";
      if (transitStatusSelect) transitStatusSelect.value = "normal";

      try {
        const res = await fetch(`${API_BASE}/api/transit-alert`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ transit_status: "normal", custom_tip: "" })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        transitFeedback.textContent = "✓ Override cleared.";
        transitFeedback.style.color = "var(--green)";
        setTimeout(() => { transitFeedback.textContent = ""; }, 3000);
      } catch (err) {
        transitFeedback.textContent = "✕ Failed to clear: " + err.message;
        transitFeedback.style.color = "var(--red)";
      }
    });
  }
});
