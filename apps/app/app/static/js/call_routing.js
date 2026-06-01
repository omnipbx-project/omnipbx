document.addEventListener("DOMContentLoaded", function () {
  const searchInput = document.querySelector(".topbar-search input");
  document.querySelectorAll('select[name="source_type"], select[name="destination_type"]').forEach((typeSelect) => {
    const targetName = typeSelect.name === "source_type" ? "source_values" : "destination_values";
    const targetPicker = document.querySelector(`[data-routing-target-select="${targetName}"]`);
    if (!targetPicker) return;
    const trigger = targetPicker.querySelector("[data-routing-target-trigger]");
    const menu = targetPicker.querySelector("[data-routing-target-menu]");
    const label = targetPicker.querySelector("[data-routing-target-label]");

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
      updateTargetLabel();
    }

    function selectedLabels() {
      return Array.from(targetPicker.querySelectorAll('.routing-target-options:not([hidden]) input[type="checkbox"]:checked'))
        .map((input) => input.dataset.label || input.value)
        .filter(Boolean);
    }

    function updateTargetLabel() {
      const values = selectedLabels();
      if (!label) return;
      label.textContent = values.length ? values.join(", ") : `Select ${targetName === "source_values" ? "source" : "destination"}`;
    }

    function closeMenu() {
      if (!menu || !trigger) return;
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }

    trigger?.addEventListener("click", function () {
      if (!menu) return;
      const open = menu.hidden;
      menu.hidden = !open;
      trigger.setAttribute("aria-expanded", String(open));
    });

    targetPicker.querySelector("[data-routing-target-ok]")?.addEventListener("click", closeMenu);
    targetPicker.querySelector("[data-routing-target-clear]")?.addEventListener("click", function () {
      targetPicker.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.checked = false;
        input.closest(".routing-target-option")?.classList.remove("selected");
      });
      updateTargetLabel();
    });

    targetPicker.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.addEventListener("change", function () {
        input.closest(".routing-target-option")?.classList.toggle("selected", input.checked);
        updateTargetLabel();
      });
    });

    typeSelect.addEventListener("change", syncTargetOptions);
    syncTargetOptions();
  });

  document.addEventListener("click", function (event) {
    document.querySelectorAll("[data-routing-target-select]").forEach((picker) => {
      if (picker.contains(event.target)) return;
      const menu = picker.querySelector("[data-routing-target-menu]");
      const trigger = picker.querySelector("[data-routing-target-trigger]");
      if (menu) menu.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
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
