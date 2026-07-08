document.addEventListener("DOMContentLoaded", function () {
    const tabs = document.querySelectorAll(".live-tab");
    const panels = document.querySelectorAll(".live-tab-panel");
    const refreshLabel = document.getElementById("live-refresh-label");
    const searchInput = document.querySelector(".topbar-search input");
    const supervisorExtension = document.getElementById("supervisor-extension");
    const actionMessage = document.getElementById("live-action-message");
    const canSupervise = document.body.dataset.canSupervise === "true";
    let refreshInFlight = false;
    const callDurationState = new Map();

    function durationToSeconds(value) {
      const parts = String(value || "").split(":").map((part) => Number.parseInt(part, 10));
      if (parts.some((part) => Number.isNaN(part))) return 0;
      if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
      if (parts.length === 2) return parts[0] * 60 + parts[1];
      return parts[0] || 0;
    }

    function formatDuration(seconds) {
      const total = Math.max(0, Math.floor(seconds || 0));
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const secs = total % 60;
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }

    function updateCallDurations() {
      const now = Date.now();
      document.querySelectorAll("[data-call-duration]").forEach((cell) => {
        const base = Number.parseInt(cell.dataset.durationSeconds || "0", 10);
        const baseAt = Number.parseInt(cell.dataset.durationBaseAt || String(now), 10);
        cell.textContent = formatDuration(base + Math.floor((now - baseAt) / 1000));
      });
    }

    function durationStateForCall(call, now) {
      const id = String(call.id || `${call.from || ""}-${call.to || ""}-${call.direction || ""}`);
      const serverSeconds = durationToSeconds(call.duration);
      const existing = callDurationState.get(id);
      if (!existing) {
        const next = {seconds: serverSeconds, baseAt: now};
        callDurationState.set(id, next);
        return next;
      }

      const displayedSeconds = existing.seconds + Math.floor((now - existing.baseAt) / 1000);
      if (serverSeconds > displayedSeconds + 1) {
        const next = {seconds: serverSeconds, baseAt: now};
        callDurationState.set(id, next);
        return next;
      }
      return existing;
    }

    function setSupervisorExtension(extension) {
      if (!supervisorExtension) return;
      if (supervisorExtension.tagName === "SELECT") {
        const normalized = String(extension || "").trim();
        if ([...supervisorExtension.options].some((option) => option.value === normalized)) {
          supervisorExtension.value = normalized;
        }
        return;
      }
      const normalized = String(extension || "").trim();
      supervisorExtension.dataset.extension = normalized;
      supervisorExtension.textContent = normalized || "Not available";
    }

    function getSupervisorExtension() {
      if (!supervisorExtension) return "";
      if (supervisorExtension.tagName === "SELECT") {
        return supervisorExtension.value || "";
      }
      return supervisorExtension.dataset.extension || "";
    }

    if (supervisorExtension?.tagName === "SELECT") {
      setSupervisorExtension(supervisorExtension.value || "");
    }

    window.addEventListener("omnipbx:webphone-config", function (event) {
      if (supervisorExtension?.tagName === "SELECT") return;
      setSupervisorExtension(event.detail?.extension);
    });

    tabs.forEach((tab) => {
      tab.addEventListener("click", function () {
        const target = tab.dataset.tab;
        tabs.forEach((item) => {
          const selected = item === tab;
          item.classList.toggle("active", selected);
          item.setAttribute("aria-selected", String(selected));
        });
        panels.forEach((item) => item.classList.toggle("active", item.dataset.panel === target));
      });
    });

    function escapeText(value) {
      return String(value ?? "").replace(/[&<>"']/g, function (char) {
        return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char];
      });
    }

    function renderCalls(calls) {
      const body = document.getElementById("active-calls-body");
      if (!body) return;
      if (!calls.length) {
        callDurationState.clear();
        body.innerHTML = `<tr><td colspan="${canSupervise ? 12 : 11}" class="muted">No active calls right now</td></tr>`;
        return;
      }
      const renderedAt = Date.now();
      const activeIds = new Set(calls.map((call) => String(call.id || `${call.from || ""}-${call.to || ""}-${call.direction || ""}`)));
      [...callDurationState.keys()].forEach((id) => {
        if (!activeIds.has(id)) callDurationState.delete(id);
      });
      body.innerHTML = calls.map((call) => `
        <tr>
          <td class="mono">${escapeText(call.from)}</td>
          <td class="mono">${escapeText(call.to)}</td>
          <td>${escapeText(call.direction)}</td>
          ${(() => {
            const state = durationStateForCall(call, renderedAt);
            return `<td class="mono" data-call-duration data-duration-seconds="${state.seconds}" data-duration-base-at="${state.baseAt}">${formatDuration(state.seconds + Math.floor((renderedAt - state.baseAt) / 1000))}</td>`;
          })()}
          <td><span class="status-pill ${escapeText(call.status_class)}">${escapeText(call.status)}</span></td>
          <td>${escapeText(call.trunk)}</td>
          <td class="mono">${escapeText(call.codec)}</td>
          <td class="mono">${escapeText(call.loss)}</td>
          <td class="mono">${escapeText(call.jitter)}</td>
          <td class="mono">${escapeText(call.rtt)}</td>
          <td><span class="status-pill ${escapeText(call.quality_class)}">${escapeText(call.quality)}</span></td>
          ${canSupervise ? `<td>
            <div class="supervisor-actions">
              <button type="button" class="secondary supervisor-action" data-action="listen" data-channel="${escapeText(call.id)}">Listen Quietly</button>
              <button type="button" class="secondary supervisor-action" data-action="guide" data-channel="${escapeText(call.id)}">Guide Agent</button>
              <button type="button" class="secondary supervisor-action" data-action="join" data-channel="${escapeText(call.id)}">Join Conversation</button>
            </div>
          </td>` : ""}
        </tr>
      `).join("");
      updateCallDurations();
    }

    function renderUsers(users) {
      const grid = document.getElementById("active-users-grid");
      if (!grid) return;
      if (!users.length) {
        grid.innerHTML = '<div class="panel"><div class="muted">No users configured</div></div>';
        return;
      }
      grid.innerHTML = users.map((user) => `
        <article class="live-user-card">
          <div class="live-user-avatar-wrap">
            <div class="live-user-avatar">${escapeText(user.initial)}</div>
            <span class="live-status-dot ${escapeText(user.status_class)}"></span>
          </div>
          <div class="live-user-copy">
            <strong>${escapeText(user.name)}</strong>
            <span>Extension ${escapeText(user.extension)}</span>
            <small>${escapeText(user.group)}</small>
            <em>${escapeText(user.status)}</em>
          </div>
        </article>
      `).join("");
    }

    function renderTrunks(trunks) {
      const body = document.getElementById("trunks-body");
      if (!body) return;
      if (!trunks.length) {
        body.innerHTML = '<tr><td colspan="6" class="muted">No trunks configured</td></tr>';
        return;
      }
      body.innerHTML = trunks.map((trunk) => `
        <tr>
          <td class="mono">${escapeText(trunk.name)}</td>
          <td>${escapeText(trunk.provider)}</td>
          <td><span class="status-pill ${escapeText(trunk.status_class)}">${escapeText(trunk.status)}</span></td>
          <td>${escapeText(trunk.active_calls)}</td>
          <td>${escapeText(trunk.last_registered)}</td>
          <td>${escapeText(trunk.message)}</td>
        </tr>
      `).join("");
    }

    function updateSummary(summary, systemStatus) {
      const values = {
        "Active Calls": summary.active_calls,
        "Active Users": summary.active_users,
        "Trunks Online": summary.trunks_online,
        "Quality Alerts": summary.quality_alerts,
        "System Status": summary.system_status,
      };
      document.querySelectorAll(".live-summary .metric-card").forEach((card) => {
        const label = card.querySelector("strong")?.textContent;
        if (label && values[label] !== undefined) {
          card.querySelector("span").textContent = values[label];
        }
        if (label === "System Status") {
          const detail = card.querySelector("small");
          if (detail) detail.textContent = systemStatus.message;
        }
      });
    }

    function applySearch() {
      const query = (searchInput?.value || "").trim().toLowerCase();
      document.querySelectorAll("#active-calls-body tr, #trunks-body tr, .live-user-card").forEach((item) => {
        item.style.display = !query || item.textContent.toLowerCase().includes(query) ? "" : "none";
      });
    }

    function showActionMessage(message, ok) {
      if (!actionMessage) return;
      actionMessage.textContent = message || "";
      actionMessage.classList.toggle("success", Boolean(ok));
      actionMessage.classList.toggle("error", !ok);
    }

    async function runSupervisorAction(button) {
      const extension = getSupervisorExtension();
      if (!extension) {
        showActionMessage("Choose a supervisor extension first.", false);
        return;
      }

      const formData = new FormData();
      formData.append("supervisor_extension", extension);
      formData.append("channel_id", button.dataset.channel || "");
      formData.append("action", button.dataset.action || "");
      button.disabled = true;
      try {
        const response = await fetch("/live-overview/supervisor-action", {
          method: "POST",
          body: formData,
          headers: {"Accept": "application/json"},
        });
        const data = await response.json();
        showActionMessage(data.message || "Action sent.", Boolean(data.ok));
      } catch (error) {
        showActionMessage("Could not send that action to Asterisk.", false);
      } finally {
        button.disabled = false;
      }
    }

    async function refreshOverview() {
      if (refreshInFlight) return;
      refreshInFlight = true;
      try {
        const response = await fetch("/live-overview/data", {
          cache: "no-store",
          headers: {"Accept": "application/json", "Cache-Control": "no-cache"},
        });
        if (!response.ok) return;
        const data = await response.json();
        renderCalls(data.active_calls || []);
        renderUsers(data.active_users || []);
        renderTrunks(data.trunks || []);
        updateSummary(data.summary || {}, data.system_status || {});
        applySearch();
        if (refreshLabel) refreshLabel.textContent = "Live";
      } catch (error) {
        if (refreshLabel) refreshLabel.textContent = "Limited";
      } finally {
        refreshInFlight = false;
      }
    }

    if (searchInput) {
      searchInput.addEventListener("input", applySearch);
    }

    document.addEventListener("click", function (event) {
      const button = event.target.closest(".supervisor-action");
      if (!button) return;
      if (!canSupervise) return;
      runSupervisorAction(button);
    });

    function connectLiveEvents() {
      if (!window.EventSource) {
        const fallbackIntervalId = window.setInterval(refreshOverview, 1000);
        window.addEventListener("pagehide", function () {
          window.clearInterval(fallbackIntervalId);
        });
        return;
      }

      const source = new EventSource("/live-overview/events");
      refreshOverview();
      window.addEventListener("pagehide", function () {
        source.close();
      });
      source.onmessage = function (event) {
        const data = JSON.parse(event.data);
        renderCalls(data.active_calls || []);
        renderUsers(data.active_users || []);
        renderTrunks(data.trunks || []);
        updateSummary(data.summary || {}, data.system_status || {});
        applySearch();
        if (refreshLabel) refreshLabel.textContent = "Live";
      };
      source.onerror = function () {
        if (refreshLabel) refreshLabel.textContent = "Reconnecting";
      };
      const refreshIntervalId = window.setInterval(refreshOverview, 1000);
      window.addEventListener("pagehide", function () {
        window.clearInterval(refreshIntervalId);
      });
    }

    const durationIntervalId = window.setInterval(updateCallDurations, 1000);
    window.addEventListener("pagehide", function () {
      window.clearInterval(durationIntervalId);
    });
    connectLiveEvents();
  });
