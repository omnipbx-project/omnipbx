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
  });
