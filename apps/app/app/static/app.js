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
      document.querySelectorAll(".provision-panel.open").forEach((panel) => {
        panel.classList.remove("open");
      });
      document.querySelectorAll(".provision-trigger[aria-expanded='true']").forEach((trigger) => {
        trigger.setAttribute("aria-expanded", "false");
      });
      closeCardMenus();
      setSidebarOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      document.querySelectorAll(".notification-panel.open, .profile-panel.open, .provision-panel.open").forEach((panel) => {
        panel.classList.remove("open");
      });
      document.querySelectorAll(".notification-trigger[aria-expanded='true'], .topbar-profile[aria-expanded='true'], .provision-trigger[aria-expanded='true']").forEach((trigger) => {
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

    document.querySelectorAll(".provision-menu").forEach((menu) => {
      const trigger = menu.querySelector("#provision-trigger");
      const panel = menu.querySelector("#provision-panel");
      const status = menu.querySelector("#provision-status");
      const desktopSettings = menu.querySelector("#desktop-softphone-settings");
      const desktopButton = menu.querySelector("#desktop-softphone-provision");
      const webExtensionButton = menu.querySelector("#webphone-provision");
      if (!trigger || !panel) return;

      function setProvisionOpen(isOpen) {
        panel.classList.toggle("open", isOpen);
        trigger.setAttribute("aria-expanded", String(isOpen));
      }

      function setProvisionStatus(message, tone) {
        if (!status) return;
        status.textContent = message || "";
        status.dataset.tone = tone || "";
      }

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

      async function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(text);
          return true;
        }
        return false;
      }

      function desktopSettingsText(config) {
        return [
          "OmniPBX desktop softphone settings",
          `Extension: ${config.extension || ""}`,
          `Display name: ${config.display_name || ""}`,
          `SIP server: ${config.server || config.sip_domain || ""}`,
          `Username: ${config.username || ""}`,
          `Auth user: ${config.auth_user || config.username || ""}`,
          `Password: ${config.password || ""}`,
          `Transport: ${config.transport || "udp"}`
        ].join("\n");
      }

      trigger.addEventListener("click", function (event) {
        event.stopPropagation();
        setProvisionOpen(!panel.classList.contains("open"));
      });
      panel.addEventListener("click", function (event) {
        event.stopPropagation();
      });

      desktopButton?.addEventListener("click", async function () {
        desktopButton.disabled = true;
        setProvisionStatus("Preparing desktop softphone settings...", "busy");
        try {
          const response = await fetch("/api/softphone/desktop/current", {cache: "no-store"});
          if (!response.ok) throw new Error("Unable to load desktop softphone settings.");
          const data = await response.json();
          if (!data.available || !data.config) throw new Error(data.message || "Desktop softphone settings are not ready.");
          const settingsText = desktopSettingsText(data.config);
          if (desktopSettings) {
            desktopSettings.textContent = settingsText;
            desktopSettings.hidden = false;
          }
          const copied = await copyText(settingsText);
          setProvisionStatus(copied ? "SIP settings copied. Paste them into your desktop softphone." : "SIP settings shown below. Copy is available over HTTPS.", copied ? "ok" : "warn");
        } catch (error) {
          setProvisionStatus(error.message || "Desktop softphone provisioning failed.", "bad");
        } finally {
          desktopButton.disabled = false;
        }
      });

      webExtensionButton?.addEventListener("click", async function () {
        webExtensionButton.disabled = true;
        setProvisionStatus("Sending settings to browser extension...", "busy");
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
          setProvisionStatus("Web extension provisioned and registration started.", "ok");
        } catch (error) {
          setProvisionStatus(error.message || "Web extension provisioning failed.", "bad");
        } finally {
          webExtensionButton.disabled = false;
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
