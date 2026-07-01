document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("dialog[open]").forEach((dialog) => {
    if (typeof dialog.showModal !== "function") return;
    dialog.removeAttribute("open");
    dialog.showModal();
  });

  document.querySelectorAll("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", function () {
      const dialog = document.getElementById(button.dataset.openDialog || "");
      if (dialog && typeof dialog.showModal === "function") {
        const form = dialog.querySelector("form");
        if (form && button.dataset.uploadAction) {
          form.action = button.dataset.uploadAction;
          form.reset();
        }
        const campaignLabel = dialog.querySelector("[data-upload-campaign-label]");
        if (campaignLabel && button.dataset.uploadCampaign) {
          campaignLabel.textContent = button.dataset.uploadCampaign;
        }
        if (dialog.open) dialog.close();
        dialog.showModal();
      }
    });
  });

  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", function () {
      button.closest("dialog")?.close();
      if (window.location.search.includes("edit_id=")) {
        window.location.href = "/call-routing/auto-dialer/campaigns";
      }
    });
  });

  const waitField = document.querySelector("[data-auto-wait-field]");
  const modeInputs = document.querySelectorAll('input[name="dialing_mode"]');
  function syncWaitField() {
    const selected = document.querySelector('input[name="dialing_mode"]:checked');
    if (!waitField) return;
    const showWaitField = selected && selected.value === "auto";
    waitField.classList.toggle("is-hidden", !showWaitField);
    waitField.style.display = showWaitField ? "" : "none";
  }
  modeInputs.forEach((input) => input.addEventListener("change", syncWaitField));
  syncWaitField();
});
