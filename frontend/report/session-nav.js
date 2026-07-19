/**
 * session-nav.js — Shared persistent identity nav bar for StadiumPulse portals.
 */

(function () {
  "use strict";

  const ROLE_LABELS = {
    fan: "Fan Companion",
    ops: "Ops Staff",
    report: "Report Desk",
  };

  const PORTALS = [
    { key: "ops",    href: "/admin",   label: "Ops Center" },
    { key: "fan",    href: "/fan",     label: "Fan View"   },
    { key: "report", href: "/report",  label: "Report Desk" },
  ];

  function detectCurrentPortal() {
    const p = window.location.pathname;
    if (p.startsWith("/admin"))  return "ops";
    if (p.startsWith("/report")) return "report";
    return "fan";
  }

  function inject() {
    const name = sessionStorage.getItem("stadiumpulse_name");
    const role = sessionStorage.getItem("stadiumpulse_role");
    const current = detectCurrentPortal();

    const isGuest = !name || !role;
    const displayName = isGuest ? "Guest" : name;
    const displayRole = isGuest ? "" : (ROLE_LABELS[role] || role);

    // Add class to document element for global styling hooks
    document.documentElement.classList.add("has-session-nav");

    // ── Styles ────────────────────────────────────────────────────────────────
    const style = document.createElement("style");
    style.textContent = `
      :root { --sp-nav-h: 48px; }

      /* push page content down by nav height */
      body { padding-top: var(--sp-nav-h) !important; }

      /* Offset sticky application headers */
      .app-header {
        top: var(--sp-nav-h) !important;
      }

      /* Adjust centered bodies to layout below the nav bar */
      html.has-session-nav body.mobile-body {
        padding-top: calc(var(--sp-nav-h) + 1.5rem) !important;
        align-items: flex-start !important;
      }

      /* Fan view wrapper needs special handling */
      .phone-wrapper { margin-top: 0 !important; }

      #sp-session-nav {
        position: fixed;
        top: 0; left: 0; right: 0;
        height: var(--sp-nav-h);
        background: rgba(18, 14, 14, 0.85);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(255,255,255,0.06);
        display: flex;
        align-items: center;
        padding: 0 1.5rem;
        gap: 0.75rem;
        z-index: 9999;
        font-family: "Inter", "Space Grotesk", system-ui, sans-serif;
        font-size: 0.78rem;
      }

      #sp-session-nav .sp-brand {
        font-family: "Space Grotesk", system-ui, sans-serif;
        font-weight: 700;
        font-size: 0.9rem;
        color: #F0E8E3;
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-shrink: 0;
        letter-spacing: -0.02em;
      }

      #sp-session-nav .sp-dot {
        width: 8px; height: 8px;
        background: #8B2333;
        border-radius: 50%;
        flex-shrink: 0;
        box-shadow: 0 0 8px rgba(139,35,51,0.8);
        animation: sp-pulse-dot 2s ease-in-out infinite;
      }

      @keyframes sp-pulse-dot {
        0%, 100% { opacity: 1; transform: scale(1); }
        50%       { opacity: 0.45; transform: scale(1.15); }
      }

      #sp-session-nav .sp-divider {
        width: 1px; height: 18px;
        background: rgba(255,255,255,0.08);
        flex-shrink: 0;
      }

      #sp-session-nav .sp-identity {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-shrink: 0;
        color: #F0E8E3;
        font-weight: 500;
      }

      #sp-session-nav .sp-role-badge {
        font-size: 0.58rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #8c7d78;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 4px;
        padding: 0.1rem 0.4rem;
      }

      #sp-session-nav .sp-guest-prompt {
        font-size: 0.72rem;
        color: #8c7d78;
      }
      #sp-session-nav .sp-guest-prompt a {
        color: #D66B78;
        text-decoration: underline;
      }

      #sp-session-nav .sp-spacer { flex: 1; }

      #sp-session-nav .sp-portal-links {
        display: flex;
        align-items: center;
        gap: 0.35rem;
      }

      #sp-session-nav .sp-portal-link {
        color: #8c7d78;
        text-decoration: none;
        font-size: 0.72rem;
        font-weight: 600;
        padding: 0.3rem 0.65rem;
        border-radius: 4px;
        border: 1px solid transparent;
        transition: all 0.15s;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      #sp-session-nav .sp-portal-link:hover {
        color: #F0E8E3;
        background: rgba(255,255,255,0.02);
      }
      #sp-session-nav .sp-portal-link.active {
        color: #F0E8E3;
        background: rgba(139,35,51,0.08);
        border-color: rgba(139,35,51,0.22);
      }

      #sp-session-nav .sp-logout {
        background: transparent;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 4px;
        color: #8c7d78;
        font-family: inherit;
        font-size: 0.7rem;
        font-weight: 600;
        padding: 0.3rem 0.65rem;
        cursor: pointer;
        transition: all 0.15s;
        flex-shrink: 0;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      #sp-session-nav .sp-logout:hover {
        color: #F0E8E3;
        border-color: rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.02);
      }
    `;
    document.head.appendChild(style);

    // ── Build nav HTML ────────────────────────────────────────────────────────
    const nav = document.createElement("nav");
    nav.id = "sp-session-nav";
    nav.setAttribute("aria-label", "StadiumPulse site navigation");

    // Brand
    const brand = document.createElement("a");
    brand.href = "/";
    brand.className = "sp-brand";
    brand.setAttribute("aria-label", "StadiumPulse home");
    brand.innerHTML = `<span class="sp-dot" aria-hidden="true"></span>StadiumPulse`;
    nav.appendChild(brand);

    const div1 = document.createElement("span");
    div1.className = "sp-divider";
    div1.setAttribute("aria-hidden", "true");
    nav.appendChild(div1);

    // Identity
    if (isGuest) {
      const guestEl = document.createElement("span");
      guestEl.className = "sp-guest-prompt";
      guestEl.innerHTML = `Browsing as Guest — <a href="/">enter your details</a>`;
      nav.appendChild(guestEl);
    } else {
      const identity = document.createElement("span");
      identity.className = "sp-identity";
      identity.innerHTML = `
        <span>${displayName}</span>
        <span class="sp-role-badge">${displayRole}</span>
      `;
      nav.appendChild(identity);
    }

    // Spacer
    const spacer = document.createElement("span");
    spacer.className = "sp-spacer";
    nav.appendChild(spacer);

    // Portal links
    const links = document.createElement("div");
    links.className = "sp-portal-links";
    links.setAttribute("role", "list");
    PORTALS.forEach(function (portal) {
      const a = document.createElement("a");
      a.href = portal.href;
      a.className = "sp-portal-link" + (portal.key === current ? " active" : "");
      a.textContent = portal.label;
      a.setAttribute("role", "listitem");
      if (portal.key === current) {
        a.setAttribute("aria-current", "page");
      }
      links.appendChild(a);
    });
    nav.appendChild(links);

    const div2 = document.createElement("span");
    div2.className = "sp-divider";
    div2.setAttribute("aria-hidden", "true");
    nav.appendChild(div2);

    // Log out
    const logout = document.createElement("button");
    logout.className = "sp-logout";
    logout.textContent = "Log out";
    logout.setAttribute("aria-label", "Clear session and return to entry screen");
    logout.addEventListener("click", function () {
      sessionStorage.removeItem("stadiumpulse_name");
      sessionStorage.removeItem("stadiumpulse_role");
      window.location.href = "/";
    });
    nav.appendChild(logout);

    // Inject at very top of body
    document.body.insertBefore(nav, document.body.firstChild);
  }

  // Run after DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inject);
  } else {
    inject();
  }
})();
