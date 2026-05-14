(function () {
  const DATA_URL = "./data/outages.json";
  const VIC_CENTER = [-37.4713, 144.7852];
  const VIC_ZOOM = 7;

  const state = {
    all: [], filtered: [],
    filters: { unplanned: true, planned: true, restored: false, distributor: "", window: "now" },
    map: null, layer: null, markers: new Map(), lastUpdated: null,
  };

  const $ = (s, r) => (r || document).querySelector(s);
  const fmt = (dt) => {
    if (!dt) return "—";
    try { return new Date(dt).toLocaleString("en-AU", { dateStyle: "medium", timeStyle: "short" }); }
    catch { return dt; }
  };
  const pillClass = (t) => t === "planned" ? "planned" : t === "restored" ? "restored" : "unplanned";
  const bullIcon = (t) => L.divIcon({
    className: "",
    html: `<div class="nx-bull ${pillClass(t)}"></div>`,
    iconSize: [22, 22], iconAnchor: [11, 11],
  });

  function popupHtml(o) {
    return `
      <h4>${o.distributor || "Unknown distributor"} — ${o.suburb || o.areaDescription || "Area"}</h4>
      <span class="nx-pill ${pillClass(o.type)}">${o.type || "unknown"}</span>
      <dl>
        <dt>Area</dt><dd>${o.areaDescription || o.suburb || "—"}${o.postcode ? " " + o.postcode : ""}</dd>
        <dt>Customers</dt><dd>${o.customersAffected ?? "—"}</dd>
        <dt>Reported</dt><dd>${fmt(o.reportedAt)}</dd>
        <dt>Status</dt><dd>${o.status || "—"}</dd>
                  <dt>${o.source === "AusNet" ? "Est. power on" : "Estimated Time Restored"}</dt><dd>${fmt(o.estimatedRestoration)}</dd>
        <dt>Updated</dt><dd>${fmt(o.lastUpdated)}</dd>
      </dl>
      <p style="margin:8px 0 0"><a href="${o.sourceUrl}" target="_blank" rel="noopener">View on ${o.source}</a></p>`;
  }

  function cardHtml(o) {
    return `
      <article class="nx-card" data-id="${o.id}">
        <div class="row"><span class="nx-pill ${pillClass(o.type)}">${o.type || "unknown"}</span><span>${o.distributor || ""}</span></div>
        <h3>${o.suburb || o.areaDescription || "Unknown area"}${o.postcode ? " " + o.postcode : ""}</h3>
        <div class="row"><span>${o.customersAffected ?? "—"} customers</span><span>Restored ${fmt(o.estimatedRestoration)}</span></div>
      </article>`;
  }

  function withinWindow(o, win) {
    if (win === "now") return o.type !== "restored";
    const ms = win === "24h" ? 86400e3 : 7 * 86400e3;
    const t = o.estimatedRestoration ? new Date(o.estimatedRestoration).getTime() : null;
    return !t || (t - Date.now() <= ms);
  }

  function computeSummary(list) {
    return {
      unplanned: list.filter(o => o.type === "unplanned").length,
      planned: list.filter(o => o.type === "planned").length,
      customers: list.reduce((s, o) => s + (Number(o.customersAffected) || 0), 0),
      lastUpdated: state.lastUpdated,
    };
  }

  function applyFilters() {
    const f = state.filters;
    state.filtered = state.all.filter(o => {
      if (o.type === "unplanned" && !f.unplanned) return false;
      if (o.type === "planned" && !f.planned) return false;
      if (o.type === "restored" && !f.restored) return false;
      if (f.distributor && (o.distributor || "") !== f.distributor) return false;
      if (!withinWindow(o, f.window)) return false;
      return true;
    });
    renderMarkers(); renderResults(); renderStats();
  }

  function renderMarkers() {
    if (!state.layer) state.layer = L.layerGroup().addTo(state.map);
    state.layer.clearLayers();
    state.markers.clear();
    state.filtered.forEach(o => {
      if (typeof o.latitude !== "number" || typeof o.longitude !== "number") return;
      const m = L.marker([o.latitude, o.longitude], { icon: bullIcon(o.type) }).bindPopup(popupHtml(o));
      m.addTo(state.layer);
      state.markers.set(o.id, m);
    });
  }

  function renderResults(items) {
    const el = $("#nx-results");
    const list = items || state.filtered.slice(0, 50);
    if (!list.length) {
      el.innerHTML = `<div class="nx-empty">
        No current outage found for this area from the available distributor data.
        Check your electricity distributor or call them to report a fault.<br><br>
        <a href="https://nexusenergy.au/contact/">Need backup power?</a>
      </div>`;
      return;
    }
    el.innerHTML = list.map(cardHtml).join("");
    el.querySelectorAll(".nx-card").forEach(c => {
      c.addEventListener("click", () => {
        const m = state.markers.get(c.getAttribute("data-id"));
        if (m) { state.map.setView(m.getLatLng(), 12, { animate: true }); m.openPopup(); }
      });
    });
  }

  function renderStats() {
    const s = computeSummary(state.filtered);
    $('[data-stat="unplanned"]').textContent = s.unplanned;
    $('[data-stat="planned"]').textContent = s.planned;
    $('[data-stat="customers"]').textContent = s.customers.toLocaleString("en-AU");
    $('[data-stat="updated"]').textContent = fmt(s.lastUpdated);
  }

  const VIC_SUBURBS = {
    "melbourne": [-37.8136, 144.9631], "geelong": [-38.1499, 144.3617],
    "ballarat": [-37.5622, 143.8503], "bendigo": [-36.7570, 144.2794],
    "shepparton": [-36.3805, 145.3989], "warrnambool": [-38.3825, 142.4836],
    "mildura": [-34.2080, 142.1246], "wodonga": [-36.1214, 146.8881],
    "traralgon": [-38.1953, 146.5413], "frankston": [-38.1413, 145.1228],
    "dandenong": [-37.9874, 145.2149], "werribee": [-37.9007, 144.6597],
    "sunbury": [-37.5829, 144.7280], "pakenham": [-38.0703, 145.4844],
    "cranbourne": [-38.1110, 145.2830], "hoppers crossing": [-37.8810, 144.7000],
    "st albans": [-37.7444, 144.7984], "port melbourne": [-37.8400, 144.9400],
    "south melbourne": [-37.8323, 144.9580], "freshwater creek": [-38.2750, 144.2730],
  };
  const POSTCODES = {
    "3000": [-37.8136, 144.9631], "3220": [-38.1499, 144.3617],
    "3350": [-37.5622, 143.8503], "3550": [-36.7570, 144.2794],
    "3030": [-37.9007, 144.6597], "3199": [-38.1413, 145.1228],
    "3175": [-37.9874, 145.2149], "3021": [-37.7444, 144.7984],
    "3207": [-37.8400, 144.9400], "3205": [-37.8323, 144.9580],
  };

  async function geocode(q) {
    const key = q.trim().toLowerCase();
    if (/^\d{4}$/.test(key) && POSTCODES[key]) return POSTCODES[key];
    if (VIC_SUBURBS[key]) return VIC_SUBURBS[key];
    try {
      const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=au&q=${encodeURIComponent(q + ", Victoria, Australia")}`;
      const r = await fetch(url, { headers: { "Accept": "application/json" } });
      const j = await r.json();
      if (j && j[0]) return [parseFloat(j[0].lat), parseFloat(j[0].lon)];
    } catch (_) {}
    return null;
  }

  async function handleSearch(e) {
    e.preventDefault();
    const q = $("#nx-q").value.trim();
    if (!q) { applyFilters(); return; }
    const ll = await geocode(q);
    if (!ll) { renderResults([]); return; }
    state.map.setView(ll, 12, { animate: true });
    const near = state.filtered.filter(o => {
      if (typeof o.latitude !== "number") return false;
      const dx = (o.latitude - ll[0]) * 111;
      const dy = (o.longitude - ll[1]) * 88;
      return Math.hypot(dx, dy) <= 10;
    });
    renderResults(near);
  }

  function bindFilters() {
    document.querySelectorAll('.nx-chk input[type=checkbox]').forEach(cb => {
      cb.addEventListener('change', () => {
        state.filters[cb.getAttribute('data-f')] = cb.checked;
        applyFilters();
      });
    });
    $("#nx-distributor").addEventListener('change', e => { state.filters.distributor = e.target.value; applyFilters(); });
    $("#nx-window").addEventListener('change', e => { state.filters.window = e.target.value; applyFilters(); });
    $("#nx-search").addEventListener('submit', handleSearch);
  }

  async function loadData() {
    try {
      const r = await fetch(DATA_URL, { cache: "no-store" });
      const j = await r.json();
      state.all = Array.isArray(j) ? j : (j.outages || []);
      state.lastUpdated = (Array.isArray(j) ? null : j.generatedAt) || new Date().toISOString();
    } catch (err) {
      state.all = [];
      state.lastUpdated = null;
      console.warn("Outage feed unavailable:", err);
    }
    applyFilters();
  }

  function initMap() {
    state.map = L.map("nx-map", { zoomControl: true }).setView(VIC_CENTER, VIC_ZOOM);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(state.map);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    bindFilters();
    loadData();
    setInterval(loadData, 5 * 60 * 1000);
  });
})();
