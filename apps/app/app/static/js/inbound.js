document.addEventListener("DOMContentLoaded", function () {
  const typeSelect = document.querySelector("[data-inbound-destination-type]");
  const picker = document.querySelector("[data-inbound-destination-picker]");
  if (!typeSelect || !picker) return;

  const trigger = picker.querySelector("[data-inbound-destination-trigger]");
  const menu = picker.querySelector("[data-inbound-destination-menu]");
  const label = picker.querySelector("[data-inbound-destination-label]");

  function activeOptions() {
    return picker.querySelector(`.routing-target-options[data-destination-kind="${typeSelect.value}"]`);
  }

  function selectedLabels() {
    const group = activeOptions();
    if (!group) return [];
    return Array.from(group.querySelectorAll('input[type="checkbox"]:checked'))
      .map((input) => input.dataset.label || input.value)
      .filter(Boolean);
  }

  function updateLabel() {
    if (!label) return;
    const values = selectedLabels();
    label.textContent = values.length ? values.join(", ") : "Select destination";
  }

  function syncDestinationOptions() {
    const selectedType = typeSelect.value;

    picker.querySelectorAll(".routing-target-options").forEach((group) => {
      const visible = group.dataset.destinationKind === selectedType;
      group.hidden = !visible;
      group.classList.toggle("active", visible);
      if (!visible) {
        group.querySelectorAll('input[type="checkbox"]').forEach((input) => {
          input.checked = false;
          input.closest(".routing-target-option")?.classList.remove("selected");
        });
      }
    });
    updateLabel();
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

  picker.querySelector("[data-inbound-destination-ok]")?.addEventListener("click", closeMenu);
  picker.querySelector("[data-inbound-destination-clear]")?.addEventListener("click", function () {
    const group = activeOptions();
    if (!group) return;
    group.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = false;
      input.closest(".routing-target-option")?.classList.remove("selected");
    });
    updateLabel();
  });

  picker.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener("change", function () {
      input.closest(".routing-target-option")?.classList.toggle("selected", input.checked);
      updateLabel();
    });
  });

  document.addEventListener("click", function (event) {
    if (picker.contains(event.target)) return;
    closeMenu();
  });

  typeSelect.addEventListener("change", syncDestinationOptions);
  syncDestinationOptions();
});
