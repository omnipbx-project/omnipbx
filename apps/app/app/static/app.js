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
    const currentUrl = new URL(window.location.href);
    const hasFlashMessage = currentUrl.searchParams.has("result") || currentUrl.searchParams.has("detail");
    if (hasFlashMessage) {
      const flashNotice = document.querySelector("main .notice.success, main .notice.notice-success");
      currentUrl.searchParams.delete("result");
      currentUrl.searchParams.delete("detail");
      window.history.replaceState({}, "", `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`);
      if (flashNotice) {
        window.setTimeout(function () {
          flashNotice.classList.add("notice-dismissing");
          window.setTimeout(() => flashNotice.remove(), 240);
        }, 4500);
      }
    }
    const mobileNavToggle = document.getElementById("mobile-nav-toggle");
    const sidebar = document.getElementById("primary-sidebar");
    const sidebarClose = document.getElementById("sidebar-close");
    const sidebarBackdrop = document.getElementById("sidebar-backdrop");

    function setSidebarOpen(isOpen) {
      document.body.classList.toggle("sidebar-open", isOpen);
      if (mobileNavToggle) {
        mobileNavToggle.setAttribute("aria-expanded", String(isOpen));
      }
    }

    function closeCardMenus(exceptMenu) {
      document.querySelectorAll(".card-menu[open]").forEach((menu) => {
        if (menu !== exceptMenu) {
          menu.open = false;
        }
      });
    }

    if (mobileNavToggle) {
      mobileNavToggle.addEventListener("click", function (event) {
        event.stopPropagation();
        setSidebarOpen(!document.body.classList.contains("sidebar-open"));
      });
    }

    [sidebarClose, sidebarBackdrop].forEach((element) => {
      if (!element) return;
      element.addEventListener("click", function () {
        setSidebarOpen(false);
      });
    });

    if (sidebar) {
      sidebar.addEventListener("click", function (event) {
        event.stopPropagation();
      });
    }

    document.querySelectorAll(".sidebar .nav-link").forEach((link) => {
      link.addEventListener("click", function () {
        setSidebarOpen(false);
      });
    });

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
      setSidebarOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      document.querySelectorAll(".notification-panel.open, .profile-panel.open").forEach((panel) => {
        panel.classList.remove("open");
      });
      document.querySelectorAll(".notification-trigger[aria-expanded='true'], .topbar-profile[aria-expanded='true']").forEach((trigger) => {
        trigger.setAttribute("aria-expanded", "false");
      });
      closeCardMenus();
      setSidebarOpen(false);
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

    document.querySelectorAll("#webphone-provision").forEach((button) => {
      function waitForProvisionResult(requestId) {
        return new Promise((resolve, reject) => {
          const timeout = window.setTimeout(() => {
            window.removeEventListener("message", onMessage);
            reject(new Error("OmniPBX web extension did not respond. Install or reload the browser extension."));
          }, 4000);
          function onMessage(event) {
            if (event.source !== window || event.origin !== window.location.origin) return;
            const message = event.data || {};
            if (message.source !== "OMNIPBX_EXTENSION" || message.type !== "OMNIPBX_PROVISION_WEB_EXTENSION_RESULT") return;
            if (message.requestId !== requestId) return;
            window.clearTimeout(timeout);
            window.removeEventListener("message", onMessage);
            resolve(message);
          }
          window.addEventListener("message", onMessage);
        });
      }

      button.addEventListener("click", async function (event) {
        event.stopPropagation();
        const originalTitle = button.title;
        button.disabled = true;
        button.title = "Provisioning...";
        try {
          const response = await fetch("/api/softphone/bootstrap/current", {cache: "no-store"});
          if (!response.ok) throw new Error("Unable to load webphone settings.");
          const data = await response.json();
          if (!data.available || !data.config) {
            throw new Error(data.message || "Current user does not have Webphone enabled.");
          }
          if (!data.config.auto_provision_enabled) {
            throw new Error("Auto provision is not enabled for the current Webphone extension.");
          }
          const requestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
          window.postMessage({
            source: "OMNIPBX",
            type: "OMNIPBX_PROVISION_WEB_EXTENSION",
            requestId,
            config: data.config,
          }, window.location.origin);
          const result = await waitForProvisionResult(requestId);
          if (!result.ok) throw new Error(result.error || "Web extension provisioning failed.");
          button.title = "Provision request sent";
          window.setTimeout(() => {
            button.title = originalTitle;
          }, 1800);
        } catch (error) {
          alert(error.message || "Web extension provisioning failed.");
          button.title = originalTitle;
        } finally {
          button.disabled = false;
        }
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
