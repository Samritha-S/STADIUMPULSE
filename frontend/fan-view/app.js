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
  
  let nudgeClass = "nudge-low";
  let badgeClass = "urgency-badge-low";
  let labelText = "Normal";

  if (urgency === "medium") {
    nudgeClass = "nudge-medium";
    badgeClass = "urgency-badge-medium";
    labelText = "Recommended Reroute";
  } else if (urgency === "critical") {
    nudgeClass = "nudge-critical";
    badgeClass = "urgency-badge-critical";
    labelText = "Optimized Egress";
  }

  const signature = `${urgency}_${nudge.message_text}`;
  const isChanged = lastNudgeSignature && lastNudgeSignature !== signature;
  lastNudgeSignature = signature;

  const highlightClass = isChanged ? " nudge-highlight" : "";

  displayWrapper.innerHTML = `
    <article class="nudge-card ${nudgeClass}${highlightClass}">
      <div class="nudge-meta-bar">
        <span class="urgency-badge ${badgeClass}">${labelText}</span>
        <span class="lang-indicator">${nudge.language.toUpperCase()}</span>
      </div>
      <p class="nudge-body" id="nudge-message">${escapeHtml(nudge.message_text)}</p>
      
      <div class="nudge-route-box">
        <span class="route-direction-icon" aria-hidden="true">
          ${isMobility ? '♿' : '🚶'}
        </span>
        <div class="route-text-content">
          <span class="route-lbl">Suggested Route</span>
          <span class="route-val">${escapeHtml(nudge.suggested_route.toUpperCase().replace('_', ' '))}</span>
        </div>
      </div>
      
      ${isMobility ? `
        <span class="accessibility-pill">✓ Accessible Egress (Step-free)</span>
      ` : ''}
    </article>
  `;
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

// Update clock in phone simulator
function updateClock() {
  const clockEl = document.getElementById("device-time");
  if (clockEl) {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  }
}

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
  
  // Set simulator time
  updateClock();
  setInterval(updateClock, 30000);

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
});
