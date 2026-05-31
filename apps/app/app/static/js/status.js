document.addEventListener("DOMContentLoaded", function () {
  const tabs = document.querySelectorAll(".advanced-tab");
  const panels = document.querySelectorAll(".advanced-panel");

  tabs.forEach((tab) => {
    tab.addEventListener("click", function () {
      const target = tab.dataset.tab;
      tabs.forEach((item) => item.classList.toggle("active", item === tab));
      panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === target));
    });
  });

  async function refreshUsage() {
    const response = await fetch("/status/usage", {cache: "no-store"});
    if (!response.ok) return;
    const data = await response.json();
    const percent = (value) => `${Number(value || 0).toFixed(1).replace(/\.0$/, "")}%`;
    const values = {
      CPU: percent(data.cpu),
      RAM: percent(data.ram),
      Disk: percent(data.disk),
      Uptime: data.uptime,
    };
    document.querySelectorAll("#advanced-usage .metric-card").forEach((card) => {
      const label = card.querySelector("strong")?.textContent?.trim();
      if (values[label]) card.querySelector("span").textContent = values[label];
    });
  }

  document.getElementById("log-filter")?.addEventListener("submit", async function (event) {
    event.preventDefault();
    const params = new URLSearchParams(new FormData(event.currentTarget));
    const response = await fetch(`/status/logs?${params.toString()}`, {cache: "no-store"});
    const data = await response.json();
    const output = document.getElementById("log-output");
    const rows = data.entries || [];
    output.innerHTML = rows.length
      ? rows.map((entry) => `
        <tr>
          <td class="mono">${escapeText(entry.time || "-")}</td>
          <td><span class="severity-badge ${(entry.level || "INFO").toLowerCase()}">${escapeText(entry.level || "INFO")}</span></td>
          <td>${escapeText(entry.message || "")}</td>
        </tr>
      `).join("")
      : '<tr><td colspan="3" class="muted">No log lines available.</td></tr>';
  });

  document.getElementById("asterisk-cli-form")?.addEventListener("submit", async function (event) {
    event.preventDefault();
    const response = await fetch("/status/asterisk-cli", {method: "POST", body: new FormData(event.currentTarget)});
    const data = await response.json();
    document.getElementById("asterisk-cli-output").textContent = data.output || "No output.";
  });

  document.getElementById("network-check-form")?.addEventListener("submit", async function (event) {
    event.preventDefault();
    const response = await fetch("/status/network-check", {method: "POST", body: new FormData(event.currentTarget)});
    const data = await response.json();
    document.getElementById("network-check-output").textContent = data.output || "No output.";
  });

  refreshUsage();
  const usageTimer = window.setInterval(refreshUsage, 4000);
  window.addEventListener("pagehide", () => window.clearInterval(usageTimer));

  function escapeText(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }
});
