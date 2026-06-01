document.addEventListener("DOMContentLoaded", function () {
  const searchInput = document.querySelector(".topbar-search input");
  document.querySelectorAll('select[name="source_type"], select[name="destination_type"]').forEach((typeSelect) => {
    const targetName = typeSelect.name === "source_type" ? "source_values" : "destination_values";
    const targetSelect = document.querySelector(`[data-routing-target-select="${targetName}"]`);
    if (!targetSelect) return;

    function syncTargetOptions() {
      const selectedKind = typeSelect.value;
      targetSelect.querySelectorAll("optgroup").forEach((group) => {
        const hidden = group.dataset.targetKind !== selectedKind;
        group.hidden = hidden;
        if (hidden) {
          group.querySelectorAll("option").forEach((option) => {
            option.selected = false;
          });
        }
      });
    }

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
