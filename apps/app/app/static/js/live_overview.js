document.addEventListener("DOMContentLoaded", function () {
    const tabs = document.querySelectorAll(".live-tab");
    const panels = document.querySelectorAll(".live-tab-panel");
    const refreshLabel = document.getElementById("live-refresh-label");
    const searchInput = document.querySelector(".topbar-search input");
    const supervisorExtension = document.getElementById("supervisor-extension");
    const actionMessage = document.getElementById("live-action-message");

    if (supervisorExtension) {
      supervisorExtension.value = window.localStorage.getItem("omnipbx-supervisor-extension") || "";
      supervisorExtension.addEventListener("input", function () {
        window.localStorage.setItem("omnipbx-supervisor-extension", supervisorExtension.value.trim());
      });
    }

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
        body.innerHTML = '<tr><td colspan="7" class="muted">No active calls right now</td></tr>';
        return;
      }
      body.innerHTML = calls.map((call) => `
        <tr>
          <td class="mono">${escapeText(call.from)}</td>
          <td class="mono">${escapeText(call.to)}</td>
          <td>${escapeText(call.direction)}</td>
          <td class="mono">${escapeText(call.duration)}</td>
          <td><span class="status-pill ${escapeText(call.status_class)}">${escapeText(call.status)}</span></td>
          <td>${escapeText(call.trunk)}</td>
          <td>
            <div class="supervisor-actions">
              <button type="button" class="secondary supervisor-action" data-action="listen" data-channel="${escapeText(call.id)}">Listen Quietly</button>
              <button type="button" class="secondary supervisor-action" data-action="guide" data-channel="${escapeText(call.id)}">Guide Agent</button>
              <button type="button" class="secondary supervisor-action" data-action="join" data-channel="${escapeText(call.id)}">Join Conversation</button>
            </div>
          </td>
        </tr>
      `).join("");
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
      const extension = supervisorExtension?.value.trim() || "";
      if (!extension) {
        showActionMessage("Enter your extension first, then choose an action.", false);
        supervisorExtension?.focus();
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
      try {
        const response = await fetch("/live-overview/data", {headers: {"Accept": "application/json"}});
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
      }
    }

    if (searchInput) {
      searchInput.addEventListener("input", applySearch);
    }

    document.addEventListener("click", function (event) {
      const button = event.target.closest(".supervisor-action");
      if (!button) return;
      runSupervisorAction(button);
    });

    function connectLiveEvents() {
      if (!window.EventSource) {
        window.setInterval(refreshOverview, 5000);
        return;
      }

      const source = new EventSource("/live-overview/events");
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
      window.setInterval(refreshOverview, 30000);
    }

    connectLiveEvents();
  });
