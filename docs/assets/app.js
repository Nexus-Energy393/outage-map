(function () {
  const DATA_URL = "./data/outages.json";
  const VIC_CENTER = [-37.4713, 144.7852];
  const VIC_ZOOM = 7;
  const LOCAL_RADIUS_KM = 10;

  const state = {
    all: [], filtered: [], visible: [],
    filters: { unplanned: true, planned: true, restored: false, distributor: "", window: "now" },
    map: null, layer: null, markers: new Map(), lastUpdated: null,
    mode: "bounds",
    userLoc: null,
    userMarker: null,
    userCircle: null,
    selectedId: null,
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
    html: '<div class="nx-bull ' + pillClass(t) + '"></div>',
    iconSize: [22, 22], iconAnchor: [11, 11],
  });
  const userIcon = () => L.divIcon({
    className: "",
    html: '<div class="nx-userdot"></div>',
    iconSize: [18, 18], iconAnchor: [9, 9],
  });

  function distanceKm(a, b) {
    const R = 6371;
    const toRad = (d) => d * Math.PI / 180;
    const dLat = toRad(b[0] - a[0]);
    const dLng = toRad(b[1] - a[1]);
    const lat1 = toRad(a[0]);
    const lat2 = toRad(b[0]);
    const x = Math.sin(dLat/2)**2 + Math.sin(dLng/2)**2 * Math.cos(lat1) * Math.cos(lat2);
    return 2 * R * Math.asin(Math.sqrt(x));
  }

  function debounce(fn, ms) {
    let t = null;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), ms);
    };
  }

  function popupHtml(o) {
    const etrLabel = o.source === "AusNet" ? "Est. power on" : "Estimated Time Restored";
    return ''
      + '<h4>' + (o.distributor || "Unknown distributor") + ' — ' + (o.suburb || o.areaDescription || "Area") + '</h4>'
      + '<span class="nx-pill ' + pillClass(o.type) + '">' + (o.type || "unknown") + '</span>'
      + '<dl>'
      + '<dt>Area</dt><dd>' + (o.areaDescription || o.suburb || "—") + (o.postcode ? " " + o.postcode : "") + '</dd>'
      + '<dt>Customers</dt><dd>' + (o.customersAffected ?? "—") + '</dd>'
      + '<dt>Reported</dt><dd>' + fmt(o.reportedAt) + '</dd>'
      + '<dt>Status</dt><dd>' + (o.status || "—") + '</dd>'
      + '<dt>' + etrLabel + '</dt><dd>' + fmt(o.estimatedRestoration) + '</dd>'
      + '<dt>Updated</dt><dd>' + fmt(o.lastUpdated) + '</dd>'
      + '</dl>'
      + '<p style="margin:8px 0 0"><a href="' + o.sourceUrl + '" target="_blank" rel="noopener">View on ' + o.source + '</a></p>';
  }

  function cardHtml(o) {
    const selected = state.selectedId === o.id ? " nx-card--selected" : "";
    const etrLabel = o.source === "AusNet" ? "Est. power on" : "Restored";
    return ''
      + '<article class="nx-card' + selected + '" data-id="' + o.id + '">'
      + '<div class="row"><span class="nx-pill ' + pillClass(o.type) + '">' + (o.type || "unknown") + '</span><span>' + (o.distributor || "") + '</span></div>'
      + '<h3>' + (o.suburb || o.areaDescription || "Unknown area") + (o.postcode ? " " + o.postcode : "") + '</h3>'
      + '<div class="row"><span>' + (o.customersAffected ?? "—") + ' customers</span><span>Reported ' + fmt(o.reportedAt) + '</span></div>'
      + '<div class="row"><span>' + (o.status || "—") + '</span><span>' + etrLabel + ' ' + fmt(o.estimatedRestoration) + '</span></div>'
      + '</article>';
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
    renderMarkers();
    refreshVisible();
  }

  function refreshVisible() {
    if (state.mode === "radius" && state.userLoc) {
      state.visible = state.filtered.filter(o => {
        if (typeof o.latitude !== "number" || typeof o.longitude !== "number") return false;
        return distanceKm(state.userLoc, [o.latitude, o.longitude]) <= LOCAL_RADIUS_KM;
      });
    } else {
      const b = state.map && state.map.getBounds();
      if (!b) { state.visible = state.filtered.slice(); }
      else {
        state.visible = state.filtered.filter(o => {
          if (typeof o.latitude !== "number" || typeof o.longitude !== "number") return false;
          return b.contains([o.latitude, o.longitude]);
        });
      }
    }
    renderResults();
    renderListHeader();
    renderStats();
  }

  function renderListHeader() {
    const el = $("#nx-list-header");
    if (!el) return;
    el.textContent = state.mode === "radius"
      ? "Outages within " + LOCAL_RADIUS_KM + " km of your location"
      : "Outages shown in current map view";
  }

  function renderMarkers() {
    if (!state.layer) state.layer = L.layerGroup().addTo(state.map);
    state.layer.clearLayers();
    state.markers.clear();
    state.filtered.forEach(o => {
      if (typeof o.latitude !== "number" || typeof o.longitude !== "number") return;
      const m = L.marker([o.latitude, o.longitude], { icon: bullIcon(o.type) }).bindPopup(popupHtml(o));
      m.on("popupopen", () => selectOutage(o.id, false));
      m.addTo(state.layer);
      state.markers.set(o.id, m);
    });
  }

  function renderResults(items) {
    const el = $("#nx-results");
    const list = items || state.visible;
    if (!list.length) {
      const msg = state.mode === "radius"
        ? "No reported outages within " + LOCAL_RADIUS_KM + " km of your location. Zoom out or search another suburb."
        : "No reported outages in this map area. Zoom out or search another suburb.";
      el.innerHTML = '<div class="nx-empty">' + msg + '<br><br><a href="https://nexusenergy.au/contact/">Need backup power?</a></div>';
      return;
    }
    el.innerHTML = list.map(cardHtml).join("");
    el.querySelectorAll(".nx-card").forEach(card => {
      card.addEventListener("click", () => {
        const id = card.getAttribute("data-id");
        const o = state.filtered.find(x => String(x.id) === String(id));
        if (!o) return;
        selectOutage(o.id, true);
      });
    });
  }

  function selectOutage(id, panAndOpen) {
    state.selectedId = id;
    const m = state.markers.get(id);
    if (m && panAndOpen) {
      state.map.setView(m.getLatLng(), Math.max(state.map.getZoom(), 13), { animate: true });
      m.openPopup();
    }
    const el = $("#nx-results");
    if (!el) return;
    el.querySelectorAll(".nx-card").forEach(c => {
      c.classList.toggle("nx-card--selected", String(c.getAttribute("data-id")) === String(id));
    });
    const sel = el.querySelector(".nx-card--selected");
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function renderStats() {
    const s = computeSummary(state.visible);
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
      const url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=au&q=" + encodeURIComponent(q + ", Victoria, Australia");
      const r = await fetch(url, { headers: { "Accept": "application/json" } });
      const j = await r.json();
      if (j && j[0]) return [parseFloat(j[0].lat), parseFloat(j[0].lon)];
    } catch (_) {}
    return null;
  }

  async function handleSearch(e) {
    e.preventDefault();
    const q = $("#nx-q").value.trim();
    if (!q) { state.mode = "bounds"; refreshVisible(); return; }
    const ll = await geocode(q);
    if (!ll) {
      state.mode = "bounds";
      state.visible = [];
      renderResults();
      renderListHeader();
      return;
    }
    state.mode = "bounds";
    state.map.setView(ll, 12, { animate: true });
  }

  function clearLocationMode() {
    if (state.userMarker) { state.map.removeLayer(state.userMarker); state.userMarker = null; }
    if (state.userCircle) { state.map.removeLayer(state.userCircle); state.userCircle = null; }
    state.userLoc = null;
  }

  function showLocStatus(msg) {
    const el = $("#nx-loc-status");
    if (!el) return;
    el.textContent = msg || "";
    el.style.display = msg ? "block" : "none";
  }

  function handleUseMyLocation() {
    if (!("geolocation" in navigator)) {
      showLocStatus("We could not detect your location. Please search by suburb or postcode.");
      return;
    }
    showLocStatus("Detecting your location…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const ll = [pos.coords.latitude, pos.coords.longitude];
        clearLocationMode();
        state.userLoc = ll;
        state.mode = "radius";
        state.map.setView(ll, 12, { animate: true });
        state.userMarker = L.marker(ll, { icon: userIcon(), interactive: false, keyboard: false }).addTo(state.map);
        state.userCircle = L.circle(ll, {
          radius: LOCAL_RADIUS_KM * 1000,
          color: "#0bbf64", weight: 2, fillColor: "#0bbf64", fillOpacity: 0.06, interactive: false,
        }).addTo(state.map);
        refreshVisible();
        showLocStatus("");
      },
      (err) => {
        if (err && err.code === 1) {
          showLocStatus("Location access was not allowed. You can still search by suburb or postcode.");
        } else {
          showLocStatus("We could not detect your location. Please search by suburb or postcode.");
        }
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 }
    );
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
    const locBtn = $("#nx-use-location");
    if (locBtn) locBtn.addEventListener("click", handleUseMyLocation);
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

    const onMapChange = debounce(() => {
      if (state.mode === "radius") {
        state.mode = "bounds";
      }
      refreshVisible();
    }, 200);

    state.map.on("moveend", onMapChange);
    state.map.on("zoomend", onMapChange);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    bindFilters();
    loadData();
    setInterval(loadData, 5 * 60 * 1000);
  });
})();
