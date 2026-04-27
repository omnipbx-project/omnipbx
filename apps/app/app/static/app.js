(function () {
  const storageKey = "omnipbx-theme";
  const root = document.documentElement;

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
  }

  function preferredTheme() {
    const stored = window.localStorage.getItem(storageKey);
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function toggleTheme() {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    window.localStorage.setItem(storageKey, next);
    applyTheme(next);
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(preferredTheme());
    document.querySelectorAll("#theme-toggle").forEach((button) => {
      button.addEventListener("click", toggleTheme);
    });
  });
})();
