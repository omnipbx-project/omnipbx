(function () {
  const modal = document.getElementById("setup-details-modal");
  const openButton = document.getElementById("open-setup-details-modal");
  const closeButton = document.getElementById("close-setup-details-modal");
  const cancelButton = document.getElementById("cancel-setup-details-modal");

  if (!modal || !openButton) return;

  function openModal() {
    modal.hidden = false;
    document.body.classList.add("settings-modal-open");
    const firstInput = modal.querySelector("form input, form select, form button");
    if (firstInput) firstInput.focus();
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("settings-modal-open");
    openButton.focus();
  }

  openButton.addEventListener("click", openModal);
  closeButton?.addEventListener("click", closeModal);
  cancelButton?.addEventListener("click", closeModal);
  modal.addEventListener("click", function (event) {
    if (event.target === modal) closeModal();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });
})();
