/* LOCAL NEWS - shared helpers: CSRF-aware fetch, toasts, nav, confirmations, form validation */
(function () {
  "use strict";

  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  async function api(url, { method = "POST", body } = {}) {
    const res = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf(),
        "X-Requested-With": "fetch",
        "Accept": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok) {
      const err = new Error(data.error || "Something went wrong.");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function toast(message, kind = "info") {
    const host = document.getElementById("toastHost");
    if (!host) return;
    const el = document.createElement("div");
    el.className = "toast toast-" + kind;
    el.textContent = message;               // textContent: never inject HTML
    host.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 300);
    }, 3500);
  }

  window.LN = { api, toast };

  // Mobile navigation
  const toggle = document.getElementById("navToggle");
  const nav = document.getElementById("mainNav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Confirm dialogs for destructive forms
  document.addEventListener("submit", (e) => {
    const msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Fade flash messages
  document.querySelectorAll(".flash-success").forEach((el) =>
    setTimeout(() => el.classList.add("fade-out"), 5000));

  // Client-side validation for the citizen forms (the server validates again)
  document.querySelectorAll("form[data-validate]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const id = form.elements.citizen_id.value.trim();
      const code = form.elements.citizen_id_code.value.trim();
      let msg = "";
      if (!/^\d{15}$/.test(id)) msg = "Citizen ID must be exactly 15 digits.";
      else if (!/^\d{8}$/.test(code)) msg = "Citizen ID Code must be exactly 8 digits.";
      else if (form.dataset.validate === "register") {
        const state = form.elements.state_id, city = form.elements.city_id, area = form.elements.area_id;
        if (!state.value) msg = "Please select your state or union territory.";
        else if (!city.value) msg = "Please select your city or district.";
        else if (area.options.length > 1 && !area.value) msg = "Please select your locality or area.";
      }
      if (msg) { e.preventDefault(); toast(msg, "error"); }
    });
  });

  // Countdown timers (15-minute deletion window)
  document.querySelectorAll("[data-countdown]").forEach((el) => {
    let left = parseInt(el.dataset.countdown, 10) || 0;
    const render = () => {
      el.textContent = Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0");
    };
    render();
    const t = setInterval(() => {
      left -= 1;
      if (left <= 0) { clearInterval(t); el.textContent = "0:00"; return; }
      render();
    }, 1000);
  });
})();
