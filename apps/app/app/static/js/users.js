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
    const userCards = new Map(
      Array.from(document.querySelectorAll(".user-management-card[data-extension]")).map((card) => [
        String(card.dataset.extension),
        card,
      ])
    );
    let activeTab = "users";

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
        actionPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }

    function closePanel() {
      if (actionPanel) {
        actionPanel.hidden = true;
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
        openPanel(activeTab);
      });
    }

    if (closeActionPanel) {
      closeActionPanel.addEventListener("click", closePanel);
    }

    document.querySelectorAll(".cancel-action").forEach((button) => {
      button.addEventListener("click", closePanel);
    });

    document.querySelectorAll(".edit-user-action").forEach((button) => {
      button.addEventListener("click", function () {
        const extension = button.dataset.extension;
        if (editUserForm) {
          editUserForm.action = `/extensions/${extension}/update`;
          document.getElementById("edit_display_name").value = button.dataset.name || "";
          document.getElementById("edit_extension").value = extension || "";
          document.getElementById("edit_email").value = button.dataset.email || "";
          document.getElementById("edit_secret").value = "";
          document.getElementById("edit_photo").value = "";
          document.getElementById("edit_group").value = button.dataset.group || document.getElementById("edit_group").value;
          document.getElementById("edit_transport").value = button.dataset.transport || "transport-udp";
          document.getElementById("edit_call_recording").checked = button.dataset.callRecording === "1";
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
        document.getElementById("permission_features").value = button.dataset.features || "";
        activeTab = "permissions";
        openPanel("permissions", "Edit Permission");
      });
    });

    function statusClass(status) {
      if (status === "Online") return "online";
      if (status === "On Call") return "on-call";
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

    if (window.EventSource) {
      const source = new EventSource("/live-overview/events");
      window.addEventListener("pagehide", function () {
        source.close();
      });
      source.onmessage = function (event) {
        const data = JSON.parse(event.data);
        updateUserCards(data.active_users || []);
      };
    } else {
      const intervalId = window.setInterval(async function () {
        const response = await fetch("/live-overview/data", {headers: {"Accept": "application/json"}});
        if (!response.ok) return;
        const data = await response.json();
        updateUserCards(data.active_users || []);
      }, 5000);
      window.addEventListener("pagehide", function () {
        window.clearInterval(intervalId);
      });
    }
  });
