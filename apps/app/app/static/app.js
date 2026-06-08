(function () {
  const storageKey = "omnipbx-theme";
  const root = document.documentElement;

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
  }

  function preferredTheme() {
    const stored = window.localStorage.getItem(storageKey);
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function toggleTheme() {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    window.localStorage.setItem(storageKey, next);
    applyTheme(next);
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(preferredTheme());

    function closeCardMenus(exceptMenu) {
      document.querySelectorAll(".card-menu[open]").forEach((menu) => {
        if (menu !== exceptMenu) {
          menu.open = false;
        }
      });
    }

    document.querySelectorAll("#theme-toggle").forEach((button) => {
      button.addEventListener("click", toggleTheme);
    });

    document.querySelectorAll(".notification-trigger").forEach((trigger) => {
      const panelId = trigger.getAttribute("aria-controls") || "dashboard-notification-panel";
      const panel = document.getElementById(panelId);
      if (!panel) return;
      trigger.addEventListener("click", function (event) {
        event.stopPropagation();
        const isOpen = panel.classList.toggle("open");
        trigger.setAttribute("aria-expanded", String(isOpen));
      });
      panel.addEventListener("click", function (event) {
        event.stopPropagation();
      });
    });

    document.addEventListener("click", function () {
      document.querySelectorAll(".notification-panel.open").forEach((panel) => {
        panel.classList.remove("open");
      });
      document.querySelectorAll(".notification-trigger[aria-expanded='true']").forEach((trigger) => {
        trigger.setAttribute("aria-expanded", "false");
      });
      document.querySelectorAll(".profile-panel.open").forEach((panel) => {
        panel.classList.remove("open");
      });
      document.querySelectorAll(".topbar-profile[aria-expanded='true']").forEach((trigger) => {
        trigger.setAttribute("aria-expanded", "false");
      });
      closeCardMenus();
    });

    document.querySelectorAll(".topbar-profile").forEach((trigger) => {
      const panel = document.getElementById("profile-menu-panel");
      if (!panel) return;
      trigger.addEventListener("click", function (event) {
        event.stopPropagation();
        const isOpen = panel.classList.toggle("open");
        trigger.setAttribute("aria-expanded", String(isOpen));
      });
      panel.addEventListener("click", function (event) {
        event.stopPropagation();
      });
    });

    document.querySelectorAll(".card-menu").forEach((menu) => {
      menu.addEventListener("toggle", function () {
        if (menu.open) {
          closeCardMenus(menu);
        }
      });
      menu.addEventListener("click", function (event) {
        event.stopPropagation();
      });
    });

    document.querySelectorAll("[data-date-range-filter]").forEach((filter) => {
      const select = filter.querySelector("[data-date-range-select]");
      const custom = filter.querySelector("[data-date-range-custom]");
      if (!select || !custom) return;
      function syncCustomRange() {
        custom.hidden = select.value !== "custom";
      }
      select.addEventListener("change", syncCustomRange);
      syncCustomRange();
    });

    document.querySelectorAll(".topbar-search input").forEach((input) => {
      const customSearchPaths = ["/extensions", "/trunks", "/call-routing", "/live-overview"];
      if (customSearchPaths.some((path) => window.location.pathname.startsWith(path))) {
        return;
      }

      input.addEventListener("input", function () {
        const query = input.value.trim().toLowerCase();
        const content = document.querySelector("main.content");
        if (!content) return;

        const targets = content.querySelectorAll(
          ".panel, .metric-card, .management-card, .call-log-row, .call-row, article, tbody tr"
        );
        targets.forEach((target) => {
          target.style.display = !query || target.textContent.toLowerCase().includes(query) ? "" : "none";
        });
      });
    });

    window.addEventListener("pagehide", function () {
      closeCardMenus();
    });

    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") {
        closeCardMenus();
      }
    });
  });
})();
