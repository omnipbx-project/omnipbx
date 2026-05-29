document.addEventListener("DOMContentLoaded", function () {
  const modal = document.getElementById("trunk-modal");
  const openButton = document.getElementById("open-trunk-modal");
  const closeButton = document.getElementById("close-trunk-modal");
  const cancelButton = document.getElementById("cancel-trunk-modal");
  const form = document.getElementById("trunk-form");
  const title = document.getElementById("trunk-modal-title");
  const message = document.getElementById("trunk-modal-message");
  const searchInput = document.querySelector(".topbar-search input");
  const mainNumber = document.getElementById("main_number");
  const mainNumberHidden = document.getElementById("main_number_hidden");

  function splitHost(value) {
    const clean = String(value || "").replace(/^sips?:/, "");
    const last = clean.lastIndexOf(":");
    if (last > -1 && /^\d+$/.test(clean.slice(last + 1))) {
      return {host: clean.slice(0, last), port: clean.slice(last + 1)};
    }
    return {host: clean, port: ""};
  }

  function protocolValue(label) {
    const value = String(label || "auto").toLowerCase();
    if (["udp", "tcp", "tls", "wss"].includes(value)) return value;
    return "auto";
  }

  function setMessage(text, ok) {
    if (!message) return;
    message.textContent = text || "";
    message.classList.toggle("success", Boolean(ok));
    message.classList.toggle("error", ok === false);
  }

  function resetForm() {
    form.action = "/trunks/create";
    title.textContent = "Add Trunk";
    form.reset();
    document.getElementById("trunk_name").name = "name";
    setMessage("", null);
  }

  function openModal() {
    modal.hidden = false;
    document.getElementById("trunk_name").focus();
  }

  function closeModal() {
    modal.hidden = true;
  }

  if (openButton) {
    openButton.addEventListener("click", function () {
      resetForm();
      openModal();
    });
  }

  [closeButton, cancelButton].forEach((button) => {
    if (button) button.addEventListener("click", closeModal);
  });

  if (modal) {
    modal.addEventListener("click", function (event) {
      if (event.target === modal) closeModal();
    });
  }

  document.querySelectorAll(".edit-trunk-action").forEach((button) => {
    button.addEventListener("click", function () {
      const hostParts = splitHost(button.dataset.host);
      resetForm();
      title.textContent = "Edit Trunk";
      form.action = `/trunks/${encodeURIComponent(button.dataset.name || "")}/update`;
      document.getElementById("trunk_name").name = "new_name";
      document.getElementById("trunk_name").value = button.dataset.name || "";
      document.getElementById("provider_name").value = button.dataset.provider || "";
      document.getElementById("main_number").value = button.dataset.mainNumber || "";
      document.getElementById("host").value = hostParts.host;
      document.getElementById("port").value = hostParts.port;
      document.getElementById("username").value = button.dataset.username || "";
      document.getElementById("password").value = "";
      document.getElementById("protocol").value = protocolValue(button.dataset.protocol);
      openModal();
    });
  });

  async function testConnection(formData) {
    setMessage("Testing connection...", null);
    try {
      const response = await fetch("/trunks/test", {
        method: "POST",
        body: formData,
        headers: {"Accept": "application/json"},
      });
      const data = await response.json();
      setMessage(data.message || "Connection test finished.", Boolean(data.ok));
    } catch (error) {
      setMessage("Could not test this trunk right now.", false);
    }
  }

  document.getElementById("test-trunk-modal")?.addEventListener("click", function () {
    testConnection(new FormData(form));
  });

  document.querySelectorAll(".test-trunk-action").forEach((button) => {
    button.addEventListener("click", async function () {
      button.disabled = true;
      try {
        const response = await fetch(`/trunks/${encodeURIComponent(button.dataset.name || "")}/test`, {
          method: "POST",
          headers: {"Accept": "application/json"},
        });
        const data = await response.json();
        alert(data.message || "Connection test finished.");
      } catch (error) {
        alert("Could not test this trunk right now.");
      } finally {
        button.disabled = false;
      }
    });
  });

  if (form) {
    form.addEventListener("submit", function () {
      mainNumberHidden.value = mainNumber.value.trim();
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      const query = searchInput.value.trim().toLowerCase();
      document.querySelectorAll("[data-trunk-card]").forEach((card) => {
        card.style.display = !query || card.textContent.toLowerCase().includes(query) ? "" : "none";
      });
    });
  }

  function statusClass(status) {
    if (status === "Online") return "online";
    if (status === "Offline") return "offline";
    return "warn";
  }

  function updateTrunks(trunks) {
    trunks.forEach((trunk) => {
      const card = Array.from(document.querySelectorAll("[data-trunk-card]")).find(
        (item) => item.dataset.trunk === String(trunk.name)
      );
      if (!card) return;
      const dot = card.querySelector(".trunk-status-dot");
      const badge = card.querySelector("[data-trunk-status]");
      const className = statusClass(trunk.status);
      if (dot) dot.className = `trunk-status-dot ${className}`;
      if (badge) {
        badge.className = `status-pill ${className}`;
        badge.textContent = trunk.status || "Warning";
      }
    });
  }

  if (window.EventSource) {
    const source = new EventSource("/live-overview/events");
    source.onmessage = function (event) {
      const data = JSON.parse(event.data);
      updateTrunks(data.trunks || []);
    };
  } else {
    window.setInterval(async function () {
      const response = await fetch("/live-overview/data", {headers: {"Accept": "application/json"}});
      if (!response.ok) return;
      const data = await response.json();
      updateTrunks(data.trunks || []);
    }, 5000);
  }
});
