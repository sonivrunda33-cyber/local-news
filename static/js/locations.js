/* Cascading State/UT -> City/District -> Locality/Area selectors. */
(function () {
  "use strict";

  async function fetchChildren(parentId) {
    const res = await fetch("/api/locations/children?parent_id=" + encodeURIComponent(parentId),
      { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!res.ok) throw new Error("Could not load locations.");
    const data = await res.json();
    if (!Array.isArray(data)) throw new Error("Invalid locations response.");
    return data;
  }

  function fill(select, items, placeholder) {
    select.replaceChildren();
    const first = document.createElement("option");
    first.value = "";
    first.textContent = placeholder;
    select.appendChild(first);
    items.forEach((it) => {
      const option = document.createElement("option");
      option.value = String(it.id);
      option.textContent = it.name;
      select.appendChild(option);
    });
    select.disabled = items.length === 0;
  }

  function reset(select, placeholder) { fill(select, [], placeholder); }

  function init(box) {
    const state = box.querySelector('[data-level="state"]');
    const city = box.querySelector('[data-level="city"]');
    const area = box.querySelector('[data-level="area"]');
    if (!state || !city || !area) return;
    const initial = box.querySelector("[data-initial-state]") || box.closest("[data-initial-state]");
    let cityRequest = 0, areaRequest = 0;

    async function loadCities(stateId, selectedCity) {
      const requestId = ++cityRequest;
      ++areaRequest;
      reset(area, "Select locality / area");
      if (!stateId) return reset(city, "Select city / district");
      reset(city, "Loading cities...");
      try {
        const items = await fetchChildren(stateId);
        if (requestId !== cityRequest) return;
        fill(city, items, "Select city / district");
        if (selectedCity && items.some((item) => String(item.id) === String(selectedCity))) {
          city.value = String(selectedCity);
        }
        if (!city.value) reset(area, "Select locality / area");
      } catch (e) {
        if (requestId === cityRequest) {
          reset(city, "Could not load cities");
          window.LN && LN.toast(e.message, "error");
        }
      }
    }

    async function loadAreas(cityId, selectedArea) {
      const requestId = ++areaRequest;
      if (!cityId) return reset(area, "Select locality / area");
      reset(area, "Loading areas...");
      try {
        const items = await fetchChildren(cityId);
        if (requestId !== areaRequest) return;
        fill(area, items, items.length ? "Select locality / area" : "No areas listed");
        if (selectedArea && items.some((item) => String(item.id) === String(selectedArea))) {
          area.value = String(selectedArea);
        }
      } catch (e) {
        if (requestId === areaRequest) {
          reset(area, "Could not load areas");
          window.LN && LN.toast(e.message, "error");
        }
      }
    }

    state.addEventListener("change", () => loadCities(state.value));
    city.addEventListener("change", () => loadAreas(city.value));

    if (initial && initial.dataset.initialState) {
      state.value = initial.dataset.initialState;
      loadCities(state.value, initial.dataset.initialCity).then(() => {
        if (initial.dataset.initialCity && city.value) {
          loadAreas(city.value, initial.dataset.initialArea);
        }
      });
    }
  }

  document.querySelectorAll("[data-location-select]").forEach(init);

  document.querySelectorAll("form[data-location-form]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (e.submitter && e.submitter.hasAttribute("data-skip-validate")) return;
      const follow = form.dataset.follow === "1";
      const s = form.elements.state_id, c = form.elements.city_id, a = form.elements.area_id;
      let msg = "";
      if (!s.value) msg = "Please select a state or union territory.";
      else if (!follow && !c.value) msg = "Please select a city or district.";
      else if (!follow && a.options.length > 1 && !a.value) msg = "Please select a locality or area.";
      if (msg) { e.preventDefault(); window.LN.toast(msg, "error"); }
    });
  });
})();
