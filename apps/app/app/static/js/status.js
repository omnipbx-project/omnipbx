document.addEventListener("DOMContentLoaded", function () {
  const tabs = document.querySelectorAll(".advanced-tab");
  const panels = document.querySelectorAll(".advanced-panel");

  function activateTab(target) {
    tabs.forEach((item) => item.classList.toggle("active", item.dataset.tab === target));
    panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === target));
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", function () {
      const target = tab.dataset.tab;
      activateTab(target);
      if (target) window.history.replaceState(null, "", `#${target}`);
    });
  });

  if (window.location.hash) {
    const target = window.location.hash.slice(1);
    if (document.querySelector(`.advanced-tab[data-tab="${target}"]`)) {
      activateTab(target);
    }
  }

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

  const accessMode = document.getElementById("advanced-access-mode");
  const sslMode = document.getElementById("advanced-ssl-mode");
  const customCertUpload = document.getElementById("advanced-custom-certificate-upload");
  function updateCustomCertUpload() {
    const show = sslMode?.value === "custom_certificate" || accessMode?.value === "private_self_hosted";
    if (customCertUpload) customCertUpload.style.display = show ? "block" : "none";
  }
  accessMode?.addEventListener("change", function () {
    const recommended = {
      local_network: "internal_local",
      public_domain: "public_domain",
      public_ip: "public_ip",
      private_self_hosted: "custom_certificate",
      http_only: "http",
    };
    if (sslMode && recommended[accessMode.value]) sslMode.value = recommended[accessMode.value];
    updateCustomCertUpload();
  });
  sslMode?.addEventListener("change", updateCustomCertUpload);
  updateCustomCertUpload();

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
