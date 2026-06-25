function scrollUsers(direction) {
    const carousel = document.getElementById("user-carousel");
    if (!carousel) return;
    carousel.scrollBy({ left: direction * carousel.clientWidth, behavior: "smooth" });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const userCards = new Map(
      Array.from(document.querySelectorAll(".user-card[data-extension]")).map((card) => [
        String(card.dataset.extension),
        card,
      ])
    );

    function statusClass(status) {
      if (status === "Online") return "online";
      if (status === "On Call") return "on-call";
      if (status === "Ringing") return "ringing";
      if (status === "Offline") return "offline";
      return "unknown";
    }

    function updateDashboardUsers(users) {
      users.forEach((user) => {
        const card = userCards.get(String(user.extension));
        if (!card) return;
        const dot = card.querySelector(".status-dot");
        const label = card.querySelector("[data-user-status]");
        if (dot) {
          dot.className = `status-dot ${statusClass(user.status)}`;
        }
        if (label) {
          label.textContent = user.status;
        }
      });
    }

    function formatPercent(value) {
      const number = Number(value || 0);
      return `${number.toFixed(1).replace(/\.0$/, "")}%`;
    }

    async function refreshSystemUsage() {
      const response = await fetch("/status/usage", {cache: "no-store"});
      if (!response.ok) return;
      const data = await response.json();
      ["cpu", "ram", "disk"].forEach((key) => {
        const card = document.querySelector(`[data-usage-card="${key}"]`);
        if (!card) return;
        const value = Number(data[key] || 0);
        card.style.setProperty("--value", String(value));
        const label = card.querySelector("[data-usage-value]");
        if (label) label.textContent = formatPercent(value);
      });
      const ram = document.querySelector('[data-usage-meta="ram"]');
      const disk = document.querySelector('[data-usage-meta="disk"]');
      const pressure = document.querySelector('[data-usage-meta="pressure"]');
      if (ram) ram.textContent = `RAM ${data.ram_used} / ${data.ram_total}`;
      if (disk) disk.textContent = `Disk free ${data.disk_free}`;
      if (pressure) pressure.textContent = `System ${data.system_pressure || "Normal"}`;
    }

    if (window.EventSource) {
      const source = new EventSource("/live-overview/events");
      window.addEventListener("pagehide", function () {
        source.close();
      });
      source.onmessage = function (event) {
        const data = JSON.parse(event.data);
        updateDashboardUsers(data.active_users || []);
      };
    } else {
      const intervalId = window.setInterval(async function () {
        const response = await fetch("/live-overview/data", {headers: {"Accept": "application/json"}});
        if (!response.ok) return;
        const data = await response.json();
        updateDashboardUsers(data.active_users || []);
      }, 5000);
      window.addEventListener("pagehide", function () {
        window.clearInterval(intervalId);
      });
    }
    refreshSystemUsage();
    const usageIntervalId = window.setInterval(refreshSystemUsage, 4000);
    window.addEventListener("pagehide", function () {
      window.clearInterval(usageIntervalId);
    });
  });
