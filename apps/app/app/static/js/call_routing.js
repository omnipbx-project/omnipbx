document.addEventListener("DOMContentLoaded", function () {
  const searchInput = document.querySelector(".topbar-search input");
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
