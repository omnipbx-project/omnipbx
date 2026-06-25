document.addEventListener("DOMContentLoaded", function () {
    const labels = {
      users: "+ Add User",
      groups: "+ Add Group",
      permissions: "+ Add Permission",
    };
    const tabs = document.querySelectorAll(".users-tab");
    const panels = document.querySelectorAll(".tab-panel");
    const action = document.getElementById("users-primary-action");
    const actionPanel = document.getElementById("users-action-panel");
    const actionPanelTitle = document.getElementById("action-panel-title");
    const closeActionPanel = document.getElementById("close-action-panel");
    const actionForms = document.querySelectorAll(".action-form");
    const editUserForm = document.getElementById("edit-user-form");
    const searchInput = document.querySelector(".topbar-search input");
    const permissionFeaturesInput = document.getElementById("permission_features");
    const permissionFeatureChecks = Array.from(document.querySelectorAll("[data-permission-feature]"));
    const permissionTemplateRadios = Array.from(document.querySelectorAll("[data-permission-template]"));
    const userCards = new Map(
      Array.from(document.querySelectorAll(".user-management-card[data-extension]")).map((card) => [
        String(card.dataset.extension),
        card,
      ])
    );
    let activeTab = "users";

    const permissionTemplates = {
      read_only: [
        "dashboard:view",
        "users:view",
        "groups:view",
        "permissions:view",
        "live_overview:view",
        "trunks:view",
        "call_routing:view",
        "inbound_routes:view",
        "ring_groups:view",
        "queues:view",
        "ivrs:view",
        "working_hours:view",
        "call_logs:view",
        "callbacks:view",
        "call_records:view",
        "voicemail:view",
        "reports:view",
        "softphone:view",
        "settings:view",
        "status:view",
        "backup_restore:view",
        "api_push:view",
        "audit_log:view",
        "admin_accounts:view",
      ],
      operator: [
        "dashboard:view",
        "users:view",
        "groups:view",
        "live_overview:view",
        "live_overview:supervise",
        "call_logs:view",
        "call_logs:recordings",
        "callbacks:view",
        "callbacks:take",
        "callbacks:complete",
        "call_records:view",
        "voicemail:view",
        "voicemail:manage",
        "softphone:view",
        "softphone:provision",
        "reports:view",
        "status:view",
      ],
      manager: [
        "dashboard:view",
        "users:view",
        "users:create",
        "users:edit",
        "groups:view",
        "groups:manage",
        "permissions:view",
        "live_overview:view",
        "live_overview:supervise",
        "trunks:view",
        "call_routing:view",
        "call_routing:manage",
        "inbound_routes:view",
        "inbound_routes:manage",
        "ring_groups:view",
        "ring_groups:manage",
        "queues:view",
        "queues:manage",
        "ivrs:view",
        "ivrs:manage",
        "working_hours:view",
        "working_hours:manage",
        "call_logs:view",
        "call_logs:export",
        "call_logs:recordings",
        "callbacks:view",
        "callbacks:take",
        "callbacks:complete",
        "call_records:view",
        "call_records:download",
        "voicemail:view",
        "voicemail:manage",
        "reports:view",
        "reports:export",
        "softphone:view",
        "softphone:configure",
        "softphone:provision",
        "settings:view",
        "status:view",
        "status:run_checks",
        "backup_restore:view",
        "api_push:view",
        "audit_log:view",
      ],
    };

    function selectedPermissionFeatures() {
      return permissionFeatureChecks.filter((input) => input.checked).map((input) => input.value);
    }

    function syncPermissionFeaturesInput() {
      if (permissionFeaturesInput) {
        permissionFeaturesInput.value = selectedPermissionFeatures().join(",");
      }
    }

    function setPermissionTemplate(template) {
      const values = new Set(permissionTemplates[template] || []);
      permissionFeatureChecks.forEach((input) => {
        input.checked = values.has(input.value);
      });
      syncPermissionFeaturesInput();
    }

    function setPermissionFeatures(values) {
      const selected = new Set(values);
      permissionFeatureChecks.forEach((input) => {
        input.checked = selected.has(input.value);
      });
      const custom = permissionTemplateRadios.find((input) => input.value === "custom");
      if (custom) {
        custom.checked = true;
      }
      syncPermissionFeaturesInput();
    }

    function resetPermissionForm() {
      const nameInput = document.getElementById("permission_name");
      const descriptionInput = document.getElementById("permission_description");
      if (nameInput) nameInput.value = "";
      if (descriptionInput) descriptionInput.value = "";
      setPermissionFeatures([]);
    }

    permissionFeatureChecks.forEach((input) => {
      input.addEventListener("change", function () {
        const custom = permissionTemplateRadios.find((radio) => radio.value === "custom");
        if (custom) {
          custom.checked = true;
        }
        syncPermissionFeaturesInput();
      });
    });

    permissionTemplateRadios.forEach((input) => {
      input.addEventListener("change", function () {
        if (input.checked && input.value !== "custom") {
          setPermissionTemplate(input.value);
        }
        if (input.checked && input.value === "custom") {
          syncPermissionFeaturesInput();
        }
      });
    });

    syncPermissionFeaturesInput();

    function setActiveForm(target, title) {
      actionForms.forEach((form) => {
        form.classList.toggle("active", form.dataset.form === target);
      });
      if (actionPanelTitle) {
        actionPanelTitle.textContent = title || labels[target].replace("+ ", "");
      }
    }

    function openPanel(target, title) {
      setActiveForm(target, title);
      if (actionPanel) {
        actionPanel.hidden = false;
        actionPanel.scrollTop = 0;
        document.body.classList.add("users-dialog-open");
        document.querySelectorAll(".card-menu[open]").forEach((menu) => {
          menu.open = false;
        });
        window.requestAnimationFrame(function () {
          actionPanelTitle?.focus({preventScroll: true});
        });
      }
    }

    function closePanel() {
      if (actionPanel) {
        actionPanel.hidden = true;
        document.body.classList.remove("users-dialog-open");
      }
    }

    tabs.forEach((tab) => {
      tab.addEventListener("click", function () {
        const target = tab.dataset.tab;
        activeTab = target;
        tabs.forEach((item) => {
          const selected = item === tab;
          item.classList.toggle("active", selected);
          item.setAttribute("aria-selected", String(selected));
        });
        panels.forEach((panel) => {
          panel.classList.toggle("active", panel.dataset.panel === target);
        });
        if (action) {
          action.textContent = labels[target] || labels.users;
        }
        setActiveForm(target);
      });
    });

    if (action) {
      action.addEventListener("click", function () {
        if (activeTab === "permissions") {
          resetPermissionForm();
        }
        openPanel(activeTab);
      });
    }

    if (closeActionPanel) {
      closeActionPanel.addEventListener("click", closePanel);
    }

    document.querySelectorAll(".cancel-action").forEach((button) => {
      button.addEventListener("click", closePanel);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && actionPanel && !actionPanel.hidden) {
        closePanel();
      }
    });

    document.querySelectorAll(".edit-user-action").forEach((button) => {
      button.addEventListener("click", function () {
        const extension = button.dataset.extension;
        if (editUserForm) {
          const extensionInput = document.getElementById("edit_extension");
          const isAdminExtension = extension === "10000";
          editUserForm.action = `/extensions/${extension}/update`;
          document.getElementById("edit_display_name").value = button.dataset.name || "";
          extensionInput.value = extension || "";
          extensionInput.readOnly = isAdminExtension;
          extensionInput.title = isAdminExtension ? "Admin extension 10000 cannot be changed." : "";
          document.getElementById("edit_email").value = button.dataset.email || "";
          document.getElementById("edit_secret").value = "";
          document.getElementById("edit_photo").value = "";
          document.getElementById("edit_group").value = button.dataset.group || document.getElementById("edit_group").value;
          document.getElementById("edit_transport").value = button.dataset.transport || "transport-udp";
          document.getElementById("edit_call_recording").checked = button.dataset.callRecording === "1";
          document.getElementById("edit_simultaneous_device_limit").value = button.dataset.deviceLimit || "1";
        }
        openPanel("edit-user", "Edit User");
      });
    });

    document.querySelectorAll(".edit-group-action").forEach((button) => {
      button.addEventListener("click", function () {
        document.getElementById("group_name").value = button.dataset.name || "";
        document.getElementById("group_description").value = button.dataset.description || "";
        document.getElementById("group_permission").value = button.dataset.permission || document.getElementById("group_permission").value;
        activeTab = "groups";
        openPanel("groups", "Edit Group");
      });
    });

    document.querySelectorAll(".edit-permission-action").forEach((button) => {
      button.addEventListener("click", function () {
        document.getElementById("permission_name").value = button.dataset.name || "";
        document.getElementById("permission_description").value = button.dataset.description || "";
        setPermissionFeatures(
          (button.dataset.features || "")
            .split(",")
            .map((feature) => feature.trim())
            .filter(Boolean)
        );
        activeTab = "permissions";
        openPanel("permissions", "Edit Permission");
      });
    });

    function statusClass(status) {
      if (status === "Online") return "online";
      if (status === "On Call") return "on-call";
      if (status === "Ringing") return "ringing";
      if (status === "Offline") return "offline";
      return "unknown";
    }

    function updateUserCards(users) {
      users.forEach((user) => {
        const card = userCards.get(String(user.extension));
        if (!card) return;
        const dot = card.querySelector(".user-status-dot");
        const label = card.querySelector("[data-user-status]");
        if (dot) {
          dot.className = `user-status-dot ${statusClass(user.status)}`;
        }
        if (label) {
          label.textContent = user.status;
        }
      });
    }

    function applySearch() {
      const query = (searchInput?.value || "").trim().toLowerCase();
      document.querySelectorAll(".user-management-card").forEach((card) => {
        card.style.display = !query || card.textContent.toLowerCase().includes(query) ? "" : "none";
      });
    }

    if (searchInput) {
      searchInput.addEventListener("input", applySearch);
    }

    let statusPollId = null;

    function startStatusPolling() {
      if (statusPollId) return;
      async function refreshStatuses() {
        const response = await fetch("/live-overview/data", {headers: {"Accept": "application/json"}});
        if (!response.ok) return;
        const data = await response.json();
        updateUserCards(data.active_users || []);
      }
      refreshStatuses();
      statusPollId = window.setInterval(refreshStatuses, 1000);
    }

    function stopStatusPolling() {
      if (!statusPollId) return;
      window.clearInterval(statusPollId);
      statusPollId = null;
    }

    if (window.EventSource) {
      const source = new EventSource("/live-overview/events");
      window.addEventListener("pagehide", function () {
        source.close();
        stopStatusPolling();
      });
      source.onopen = stopStatusPolling;
      source.onmessage = function (event) {
        const data = JSON.parse(event.data);
        updateUserCards(data.active_users || []);
      };
      source.onerror = startStatusPolling;
    } else {
      startStatusPolling();
      window.addEventListener("pagehide", function () {
        stopStatusPolling();
      });
    }
  });
