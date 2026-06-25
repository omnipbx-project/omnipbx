document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-update-panel]").forEach((panel) => {
    const checkButton = panel.querySelector('[data-update-action="check"]');
    const runButton = panel.querySelector('[data-update-action="run"]');
    const state = panel.querySelector("[data-update-state]");
    const message = panel.querySelector("[data-update-message] span");

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
        state.textContent = data.update_available ? "Update available" : "Up to date";
        state.className = `status-pill ${data.update_available ? "warning" : "success"}`;
      }
      if (runButton) runButton.disabled = !data.can_start_update;
      setMessage(data.update_status?.message || data.check_message || data.check_error);
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
      try {
        await fetchStatus("/api/system/update/run", {method: "POST"});
        window.setTimeout(() => fetchStatus("/api/system/update").catch(() => {}), 2500);
      } catch (error) {
        setMessage(error.message);
        runButton.disabled = false;
      } finally {
        runButton.textContent = original;
      }
    });
  });
});
