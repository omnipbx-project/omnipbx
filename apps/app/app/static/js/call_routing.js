document.addEventListener("DOMContentLoaded", function () {
  const searchInput = document.querySelector(".topbar-search input");
  document.querySelectorAll('select[name="source_type"], select[name="destination_type"]').forEach((typeSelect) => {
    const targetName = typeSelect.name === "source_type" ? "source_values" : "destination_values";
    const targetPicker = document.querySelector(`[data-routing-target-select="${targetName}"]`);
    if (!targetPicker) return;

    function syncTargetOptions() {
      const selectedKind = typeSelect.value;
      targetPicker.querySelectorAll(".routing-target-options").forEach((group) => {
        const active = group.dataset.targetKind === selectedKind;
        group.hidden = !active;
        group.classList.toggle("active", active);
        if (!active) {
          group.querySelectorAll('input[type="checkbox"]').forEach((input) => {
            input.checked = false;
            input.closest(".routing-target-option")?.classList.remove("selected");
          });
        }
      });
    }

    targetPicker.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.addEventListener("change", function () {
        input.closest(".routing-target-option")?.classList.toggle("selected", input.checked);
      });
    });

    typeSelect.addEventListener("change", syncTargetOptions);
    syncTargetOptions();
  });

  if (!searchInput) return;

  searchInput.addEventListener("input", function () {
    const query = searchInput.value.trim().toLowerCase();
    document.querySelectorAll("[data-routing-card]").forEach((card) => {
      card.style.display = !query || card.textContent.toLowerCase().includes(query) ? "" : "none";
    });
    document.querySelectorAll("[data-routing-section]").forEach((section) => {
      const hasVisibleCard = Array.from(section.querySelectorAll("[data-routing-card]")).some(
        (card) => card.style.display !== "none"
      );
      section.style.display = hasVisibleCard ? "" : "none";
    });
  });
});
