document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-update-panel]").forEach((panel) => {
    const checkButton = panel.querySelector('[data-update-action="check"]');
    const runButton = panel.querySelector('[data-update-action="run"]');
    const state = panel.querySelector("[data-update-state]");
    const message = panel.querySelector("[data-update-message] span");
    const progress = panel.querySelector("[data-update-progress]");
    const progressFill = panel.querySelector("[data-update-progress-fill]");
    const progressLabel = panel.querySelector("[data-update-progress-label]");
    const progressPercent = panel.querySelector("[data-update-progress-percent]");
    const progressTrack = panel.querySelector(".update-progress-track");
    let pollTimer = null;

    function setBusy(button, busy, label) {
      if (!button) return;
      button.disabled = busy;
      if (label) button.textContent = label;
    }

    function setMessage(text) {
      if (message) message.textContent = text || "No update status available.";
    }

    function updateField(name, value) {
      panel.querySelectorAll(`[data-update-field="${name}"]`).forEach((item) => {
        item.textContent = value || "-";
      });
    }

    function progressState(data) {
      const updateState = data?.update_status?.state || "idle";
      if (updateState === "queued") return {state: updateState, label: "Queued", percent: 20, text: "20%"};
      if (updateState === "updating") return {state: updateState, label: "Updating", percent: 60, text: "60%"};
      if (updateState === "success") return {state: updateState, label: "Update complete", percent: 100, text: "100%"};
      if (updateState === "error") return {state: updateState, label: "Update failed", percent: 100, text: "Stopped"};
      if (data?.version_apply_needed || data?.update_available) {
        return {state: "ready", label: "Ready", percent: 0, text: "0%"};
      }
      return {state: "idle", label: "Ready", percent: 0, text: "0%"};
    }

    function renderProgress(data) {
      const info = progressState(data);
      if (progress) progress.dataset.state = info.state;
      if (progressLabel) progressLabel.textContent = info.label;
      if (progressPercent) progressPercent.textContent = info.text;
      if (progressFill) progressFill.style.width = `${info.percent}%`;
      if (progressTrack) {
        progressTrack.setAttribute("aria-valuenow", String(info.percent));
        progressTrack.setAttribute("aria-valuetext", info.label);
      }
    }

    function stopPolling() {
      if (pollTimer) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
    }

    function pollStatus(delay = 2000) {
      stopPolling();
      pollTimer = window.setTimeout(async () => {
        try {
          const data = await fetchStatus("/api/system/update");
          const updateState = data?.update_status?.state || "idle";
          if (updateState === "queued" || updateState === "updating") {
            pollStatus(2500);
          }
        } catch (_) {
          pollStatus(4000);
        }
      }, delay);
    }

    function render(data) {
      if (!data) return;
      updateField("current_version", data.current_version);
      updateField("latest_version", data.latest_version);
      updateField("local_commit", data.local_commit);
      updateField("remote_commit", data.remote_commit);
      updateField("local_branch", data.local_branch);
      updateField("upstream_ref", data.upstream_ref);
      updateField("commits_behind", String(data.commits_behind ?? 0));
      updateField("last_checked_at", data.last_checked_at);

      if (state) {
        state.textContent = data.version_apply_needed ? "Ready to apply" : (data.update_available ? "Update available" : "Up to date");
        state.className = `status-pill ${data.update_available ? "warning" : "success"}`;
      }
      if (runButton) runButton.disabled = !data.can_start_update;
      const updateState = data.update_status?.state || "idle";
      const statusMessage = updateState !== "idle" ? data.update_status?.message : "";
      setMessage(statusMessage || data.check_message || data.check_error);
      renderProgress(data);
      if (updateState === "queued" || updateState === "updating") {
        pollStatus(2500);
      } else {
        stopPolling();
      }
    }

    async function fetchStatus(url, options) {
      const response = await fetch(url, {cache: "no-store", ...(options || {})});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Update request failed.");
      render(data);
      return data;
    }

    checkButton?.addEventListener("click", async function () {
      const original = checkButton.textContent;
      setBusy(checkButton, true, "Checking...");
      setMessage("Checking git for updates...");
      try {
        await fetchStatus("/api/system/update/check", {method: "POST"});
      } catch (error) {
        setMessage(error.message);
      } finally {
        checkButton.textContent = original;
        checkButton.disabled = false;
      }
    });

    runButton?.addEventListener("click", async function () {
      const original = runButton.textContent;
      setBusy(runButton, true, "Starting...");
      setMessage("Starting manual update...");
      renderProgress({update_status: {state: "queued"}});
      try {
        await fetchStatus("/api/system/update/run", {method: "POST"});
        pollStatus(1500);
      } catch (error) {
        setMessage(error.message);
        renderProgress({update_status: {state: "error"}});
        runButton.disabled = false;
      } finally {
        runButton.textContent = original;
      }
    });
  });
});
