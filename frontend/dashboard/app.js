/**
 * StadiumPulse Dashboard Operations scripting
 */

// Mock Data matching the schemas exactly
const MOCK_ZONES = [
  {
    zone_id: "zone_100_gate_a",
    zone_name: "100 Level – Gate A Concourse",
    current_count: 7717,
    capacity: 19500,
    forecast_count_15min: 7486,
    forecast_count_30min: 7255,
    status: "normal",
    connected_gates: ["gate_a", "gate_b"],
    accessible_routes: ["ramp_100_east", "elevator_100_a"]
  },
  {
    zone_id: "zone_200_gate_c",
    zone_name: "200 Level – Gate C Concourse",
    current_count: 14266,
    capacity: 18000,
    forecast_count_15min: 16342,
    forecast_count_30min: 17093,
    status: "critical",
    connected_gates: ["gate_c", "gate_d"],
    accessible_routes: ["ramp_200_north", "elevator_200_c"]
  },
  {
    zone_id: "zone_200_gate_e",
    zone_name: "200 Level – Gate E Concourse",
    current_count: 14041,
    capacity: 18000,
    forecast_count_15min: 14053,
    forecast_count_30min: 14065,
    status: "watch",
    connected_gates: ["gate_e"],
    accessible_routes: ["ramp_200_east", "elevator_200_e"]
  },
  {
    zone_id: "zone_300_gate_f",
    zone_name: "300 Level – Gate F Concourse",
    current_count: 17091,
    capacity: 18000,
    forecast_count_15min: 17088,
    forecast_count_30min: 17085,
    status: "critical",
    connected_gates: ["gate_f", "gate_g"],
    accessible_routes: ["ramp_300_west", "elevator_300_f"]
  },
  {
    zone_id: "zone_300_gate_h",
    zone_name: "300 Level – Gate H Concourse",
    current_count: 16234,
    capacity: 17500,
    forecast_count_15min: 16311,
    forecast_count_30min: 16356,
    status: "critical",
    connected_gates: ["gate_h"],
    accessible_routes: ["ramp_300_north", "elevator_300_h"]
  },
  {
    zone_id: "zone_field_gate_b",
    zone_name: "Field Level – Gate B Concourse",
    current_count: 7480,
    capacity: 18500,
    forecast_count_15min: 7428,
    forecast_count_30min: 7377,
    status: "normal",
    connected_gates: ["gate_b"],
    accessible_routes: ["ramp_field_south"]
  },
  {
    zone_id: "zone_field_gate_d",
    zone_name: "Field Level – Gate D Concourse",
    current_count: 4847,
    capacity: 12000,
    forecast_count_15min: 5178,
    forecast_count_30min: 5510,
    status: "normal",
    connected_gates: ["gate_d"],
    accessible_routes: ["ramp_field_east", "elevator_field_d"]
  }
];

const MOCK_BRIEFS = [
  {
    zone_id: "zone_300_gate_f",
    severity: "critical",
    summary_text: "300 Level - Gate F Concourse is at 17103/18000 capacity. Automated summary unavailable.",
    recommended_action: "Manual assessment recommended. LLM summary generation failed.",
    suggested_reroute_zone: "ramp_300_west",
    languages_needed: ["en"],
    generated_at: new Date().toISOString()
  },
  {
    zone_id: "zone_300_gate_h",
    severity: "critical",
    summary_text: "300 Level - Gate H Concourse is at 16234/17500 capacity. Automated summary unavailable.",
    recommended_action: "Manual assessment recommended. LLM summary generation failed.",
    suggested_reroute_zone: "ramp_300_north",
    languages_needed: ["en"],
    generated_at: new Date().toISOString()
  },
  {
    zone_id: "zone_200_gate_c",
    severity: "critical",
    summary_text: "200 Level - Gate C Concourse is at 16342/18000 capacity. Automated summary unavailable.",
    recommended_action: "Manual assessment recommended. LLM summary generation failed.",
    suggested_reroute_zone: "ramp_200_north",
    languages_needed: ["en"],
    generated_at: new Date().toISOString()
  },
  {
    zone_id: "zone_200_gate_e",
    severity: "medium",
    summary_text: "200 Level - Gate E Concourse is at 14046/18000 capacity. Automated summary unavailable.",
    recommended_action: "Manual assessment recommended. LLM summary generation failed.",
    suggested_reroute_zone: "ramp_200_east",
    languages_needed: ["en"],
    generated_at: new Date().toISOString()
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
