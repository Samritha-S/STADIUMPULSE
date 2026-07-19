// Volunteer Desk App Logic
document.addEventListener("DOMContentLoaded", () => {
  // (device-time clock removed — was part of the old phone status bar chrome)

  const form = document.getElementById("incident-form");
  const textarea = document.getElementById("raw_text");
  const charCounter = document.getElementById("char-counter");
  const errorBanner = document.getElementById("form-error");
  const submitBtn = document.getElementById("submit-btn");
  const btnText = document.getElementById("btn-text");
  const btnLoader = document.getElementById("btn-loader");

  const confirmationPanel = document.getElementById("confirmation-panel");
  const confirmSummary = document.getElementById("confirm-summary");
  const tagCategory = document.getElementById("tag-category");
  const tagSeverity = document.getElementById("tag-severity");
  const tagZone = document.getElementById("tag-zone");
  const resetBtn = document.getElementById("reset-btn");

  // Character limit counter
  textarea.addEventListener("input", () => {
    const len = textarea.value.length;
    charCounter.textContent = `${len} / 1000`;
    if (len > 1000) {
      charCounter.style.color = "var(--pulse-critical)";
    } else {
      charCounter.style.color = "var(--ink-dim)";
    }
  });

  // Reset form to write another report
  resetBtn.addEventListener("click", () => {
    confirmationPanel.style.display = "none";
    form.style.display = "flex";
    textarea.value = "";
    charCounter.textContent = "0 / 1000";
    errorBanner.style.display = "none";
  });

  // Submit report to FastAPI
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const val = textarea.value.trim();

    // Reset error states
    errorBanner.style.display = "none";
    errorBanner.textContent = "";

    // Front-end validations
    if (!val) {
      showError("Report details cannot be empty.");
      return;
    }
    if (val.length > 1000) {
      showError("Report details exceed the maximum length of 1000 characters.");
      return;
    }

    // Set loading state
    setLoading(true);

    try {
      // POST to our endpoint
      const response = await fetch("/api/report", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ raw_text: val })
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned code ${response.status}`);
      }

      const report = await response.json();
      showSuccess(report);

    } catch (err) {
      showError(`Dispatch failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  });

  function showError(msg) {
    errorBanner.textContent = msg;
    errorBanner.style.display = "block";
  }

  function setLoading(isLoading) {
    if (isLoading) {
      submitBtn.disabled = true;
      btnText.textContent = "Dispatching...";
      btnLoader.style.display = "inline-block";
    } else {
      submitBtn.disabled = false;
      btnText.textContent = "Submit Incident";
      btnLoader.style.display = "none";
    }
  }

  function showSuccess(report) {
    // Hide form, show confirmation panel
    form.style.display = "none";
    confirmationPanel.style.display = "block";

    // Set summary
    confirmSummary.textContent = report.structured_summary;

    // Set Category Tag
    tagCategory.textContent = report.category;

    // Set Severity Tag
    tagSeverity.textContent = report.severity;
    // Clear old severity classes
    tagSeverity.className = "tag tag-severity";
    tagSeverity.classList.add(`severity-${report.severity}`);

    // Set Zone Tag
    if (report.zone_id) {
      tagZone.textContent = report.zone_id.replace("zone_", "").replace(/_/g, " ").toUpperCase();
      tagZone.style.display = "inline-block";
    } else {
      tagZone.style.display = "none";
    }
  }

  function updateClock() {
    const deviceTime = document.getElementById("device-time");
    if (!deviceTime) return;
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, "0");
    const minutes = String(now.getMinutes()).padStart(2, "0");
    deviceTime.textContent = `${hours}:${minutes}`;
  }
});
