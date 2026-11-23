/* LOCAL NEWS - slideshow, Relevant/Fake voting, save/unsave, publish form helpers. */
(function () {
  "use strict";
  const { api, toast } = window.LN;

  /* ---------- Featured slideshow ---------- */
  const show = document.getElementById("slideshow");
  if (show) {
    const slides = [...show.querySelectorAll(".slide")];
    const dots = [...show.querySelectorAll(".dot")];
    let index = 0, timer = null;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function go(n) {
      index = (n + slides.length) % slides.length;
      slides.forEach((s, i) => s.classList.toggle("active", i === index));
      dots.forEach((d, i) => d.classList.toggle("active", i === index));
    }
    function start() {
      stop();
      if (slides.length > 1 && !reduceMotion) timer = setInterval(() => go(index + 1), 5000);
    }
    function stop() { if (timer) clearInterval(timer); timer = null; }

    show.querySelector(".prev")?.addEventListener("click", () => { go(index - 1); start(); });
    show.querySelector(".next")?.addEventListener("click", () => { go(index + 1); start(); });
    dots.forEach((d, i) => d.addEventListener("click", () => { go(i); start(); }));
    show.addEventListener("mouseenter", stop);
    show.addEventListener("mouseleave", start);
    show.addEventListener("focusin", stop);
    show.addEventListener("focusout", start);
    // touch swipe
    let x0 = null;
    show.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; stop(); }, { passive: true });
    show.addEventListener("touchend", (e) => {
      if (x0 !== null) {
        const dx = e.changedTouches[0].clientX - x0;
        if (Math.abs(dx) > 40) go(index + (dx < 0 ? 1 : -1));
      }
      x0 = null; start();
    });
    start();
  }

  /* ---------- Voting & saving (event delegation) ----------
     The "Why is this fake?" popup is an independent overlay: when opened it is moved to
     <body> (so no card / scroll container can clip it or trap it in a stacking context),
     positioned with fixed coordinates next to its button (a bottom sheet on phones),
     and put back into its card when closed. */
  let openPop = null;                       // { pop, bar, home, backdrop }

  function closePops() {
    if (!openPop) return;
    const { pop, home, backdrop, trigger } = openPop;
    pop.hidden = true;
    pop.classList.remove("is-sheet");
    pop.removeAttribute("data-open");
    ["top", "left", "bottom", "right", "maxHeight"].forEach((k) => { pop.style[k] = ""; });
    home.appendChild(pop);                  // back inside its card
    backdrop.remove();
    trigger.setAttribute("aria-expanded", "false");
    openPop = null;
  }

  function placePop(pop, trigger) {
    const isPhone = window.matchMedia("(max-width: 600px)").matches;
    pop.classList.toggle("is-sheet", isPhone);
    ["top", "left", "bottom", "right", "maxHeight"].forEach((k) => { pop.style[k] = ""; });
    if (isPhone) return;                    // CSS pins the sheet to the bottom of the screen
    const margin = 8, r = trigger.getBoundingClientRect();
    const w = pop.offsetWidth, h = pop.offsetHeight;
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    let left = Math.min(Math.max(margin, r.left), Math.max(margin, vw - w - margin));
    const below = vh - r.bottom - margin, above = r.top - margin;
    let top = (below >= h || below >= above) ? r.bottom + 6 : r.top - h - 6;   // flip above if no room
    top = Math.min(Math.max(margin, top), Math.max(margin, vh - h - margin));
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  function openReasonPop(bar, trigger) {
    closePops();
    const pop = bar.querySelector(".reason-pop");
    if (!pop) return;
    const backdrop = document.createElement("div");
    backdrop.className = "reason-backdrop";
    document.body.appendChild(backdrop);
    document.body.appendChild(pop);
    pop.hidden = false;
    pop.dataset.open = "1";
    pop._bar = bar;
    openPop = { pop, bar, home: bar.querySelector(".fake-wrap"), backdrop, trigger };
    trigger.setAttribute("aria-expanded", "true");
    placePop(pop, trigger);
    pop.querySelector("[data-reason]")?.focus({ preventScroll: true });
  }

  function applyVote(bar, result) {
    bar.dataset.myVote = result.my_vote;
    bar.dataset.locked = "1";
    bar.querySelector('[data-count="relevant"]').textContent = result.relevant;
    bar.querySelector('[data-count="fake"]').textContent = result.fake;
    bar.querySelectorAll(".btn-vote").forEach((b) => {
      b.disabled = true;
      b.classList.toggle("is-on", b.dataset.action === result.my_vote);
    });
    closePops();
  }

  let voting = false;                       // blocks repeated clicks while a vote is in flight
  async function sendVote(bar, vote, reason) {
    if (voting) return;
    voting = true;
    try {
      const result = await api(`/api/news/${bar.dataset.postId}/vote`, { body: { vote, reason } });
      applyVote(bar, result);
      toast(vote === "relevant" ? "Marked as relevant." : "Marked as fake (" + reason + ").", "success");
      if (result.status === "hidden") toast("This news is now hidden because of community feedback.", "info");
    } catch (err) {
      closePops();
      toast(err.message, "error");
      if (err.status === 409) location.reload();
    } finally { voting = false; }
  }

  document.addEventListener("click", async (e) => {
    // clicks inside the floating popup (it no longer lives inside .news-actions)
    const inPop = e.target.closest(".reason-pop");
    if (inPop) {
      if (e.target.closest("[data-close-pop]")) { closePops(); return; }
      const rb = e.target.closest("[data-reason]");
      if (rb && inPop._bar) await sendVote(inPop._bar, "fake", rb.dataset.reason);
      return;
    }
    if (e.target.closest(".reason-backdrop")) { closePops(); return; }

    const bar = e.target.closest(".news-actions");
    if (!bar) { closePops(); return; }

    const btn = e.target.closest("[data-action]");
    if (!btn || btn.disabled) return;
    const action = btn.dataset.action;

    if (action === "relevant") { closePops(); await sendVote(bar, "relevant", null); }
    else if (action === "fake") {
      if (openPop && openPop.bar === bar) closePops(); else openReasonPop(bar, btn);
    } else if (action === "save") {
      closePops();
      try {
        const { saved } = await api(`/api/news/${bar.dataset.postId}/save`, {});
        btn.classList.toggle("is-on", saved);
        btn.setAttribute("aria-pressed", saved ? "true" : "false");
        btn.querySelector(".save-label").textContent = saved ? "Saved" : "Save";
        toast(saved ? "Saved to your profile." : "Removed from saved news.", "success");
      } catch (err) { toast(err.message, "error"); }
    }
  });

  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePops(); });
  window.addEventListener("resize", () => { if (openPop) placePop(openPop.pop, openPop.trigger); });
  window.addEventListener("scroll", () => { if (openPop && !openPop.pop.classList.contains("is-sheet")) closePops(); },
    { passive: true, capture: true });

  /* ---------- Unsave from the profile page ---------- */
  document.querySelectorAll("[data-unsave]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/api/news/${btn.dataset.unsave}/save`, {});   // toggles an existing save off
        btn.closest("li").remove();
        toast("Removed from saved news.", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });
  });

  /* ---------- Publish form ---------- */
  const form = document.getElementById("createForm");
  if (form) {
    const desc = document.getElementById("descInput");
    const counter = document.getElementById("descCounter");
    const fileInput = document.getElementById("imageInput");
    const previews = document.getElementById("previews");
    const max = parseInt(desc.getAttribute("maxlength"), 10);
    const updateCount = () => { counter.textContent = desc.value.length + " / " + max; };
    desc.addEventListener("input", updateCount); updateCount();

    function checkFiles() {
      const maxFiles = parseInt(fileInput.dataset.maxFiles, 10);
      const maxBytes = parseInt(fileInput.dataset.maxBytes, 10);
      const files = [...fileInput.files];
      previews.innerHTML = "";
      if (files.length > maxFiles) return `You can upload at most ${maxFiles} images.`;
      for (const f of files) {
        if (!/^image\/(jpeg|png|webp)$/.test(f.type)) return `"${f.name}" is not a JPG, PNG or WEBP image.`;
        if (f.size > maxBytes) return `"${f.name}" is larger than ${Math.round(maxBytes / 1048576)} MB.`;
        const img = document.createElement("img");
        img.alt = "Preview of " + f.name;
        img.src = URL.createObjectURL(f);
        img.onload = () => URL.revokeObjectURL(img.src);
        previews.appendChild(img);
      }
      return "";
    }
    fileInput.addEventListener("change", () => {
      const msg = checkFiles();
      if (msg) { toast(msg, "error"); fileInput.value = ""; previews.innerHTML = ""; }
    });
    form.addEventListener("submit", (e) => {
      const title = form.elements.title.value.trim();
      let msg = "";
      if (title.length < 5) msg = "Title must be at least 5 characters.";
      else if (!desc.value.trim()) msg = "Please write a description.";
      else msg = checkFiles();
      if (msg) { e.preventDefault(); toast(msg, "error"); return; }
      form.querySelector('button[type="submit"]').disabled = true;   // avoid double submit
    });
  }
})();
