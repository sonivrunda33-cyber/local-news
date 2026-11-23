/* Light / Night mode. The server renders data-theme from the user's saved setting;
   this file lets the Settings page switch it and persists it to the database. */
(function () {
  "use strict";
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-theme-choice]");
    if (!btn) return;
    const theme = btn.dataset.themeChoice;
    const previous = document.documentElement.dataset.theme;
    document.documentElement.dataset.theme = theme;      // instant feedback
    try {
      await window.LN.api("/settings/theme", { body: { theme } });
      document.querySelectorAll("[data-theme-choice]").forEach((b) => {
        const on = b.dataset.themeChoice === theme;
        b.classList.toggle("is-on", on);
        b.setAttribute("aria-checked", on ? "true" : "false");
      });
    } catch (err) {
      document.documentElement.dataset.theme = previous;  // roll back if not saved
      window.LN.toast(err.message, "error");
    }
  });
})();
