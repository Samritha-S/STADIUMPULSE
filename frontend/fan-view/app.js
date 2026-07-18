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

// API base URL — change the port here if you run the server elsewhere
const API_BASE = "http://localhost:8000";

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
async function fetchNudge(index) {
  const profile = SCENARIO_FAN_PROFILES[index];
  const params = new URLSearchParams({
    fan_id:         profile.fan_id,
    language:       profile.language,
    mobility_needs: profile.mobility_needs,
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
function renderNudge(nudge, urgency) {
  const displayWrapper = document.getElementById("nudge-display-wrapper");
  if (!displayWrapper) return;

  const formattedTime = new Date(nudge.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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

  displayWrapper.innerHTML = `
    <article class="nudge-card ${nudgeClass}">
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

// Load Nudge scenario
async function loadScenario(index) {
  const wrapper = document.getElementById("nudge-display-wrapper");
  wrapper.innerHTML = `<div class="nudge-loading">Receiving route updates...</div>`;

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

// Lifecycle Hooks
document.addEventListener("DOMContentLoaded", () => {
  loadScenario(currentScenarioIndex);
  
  // Set simulator time
  updateClock();
  setInterval(updateClock, 30000);

  // Next scenarios cycle event
  const nextBtn = document.getElementById("next-nudge-btn");
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      currentScenarioIndex = (currentScenarioIndex + 1) % MOCK_NUDGES.length;
      loadScenario(currentScenarioIndex);
    });
  }
});
