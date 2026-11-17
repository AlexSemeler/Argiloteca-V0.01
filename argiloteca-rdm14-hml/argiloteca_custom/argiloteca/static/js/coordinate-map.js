/* Map choices are proposals. Only the existing revision-checked forms publish. */
(() => {
  'use strict';
  const configNode = document.getElementById('cm-config');
  if (!configNode) return;
  const config = JSON.parse(configNode.textContent), text = config.text;
  const byId = id => document.getElementById(id);
  const status = byId('cm-search-status'), results = byId('cm-results');
  const target = byId('cm-target'), apply = byId('cm-apply');
  const forms = Array.from(document.querySelectorAll('[data-coordinate-target]'));
  const currentForm = () => target && forms.find(form => form.dataset.coordinateTarget === target.value);
  const coordinates = value => Number.isFinite(value.lat) && Number.isFinite(value.lon) && Math.abs(value.lat) <= 90 && Math.abs(value.lon) <= 180;
  const format = value => new Intl.NumberFormat(config.locale, {maximumFractionDigits:6}).format(value);
  const pair = value => `${format(value.lat)} / ${format(value.lon)}`;
  let map, pointLayer, proposalMarker, proposal, busy = false;
  function report(message, error = false) {
    status.textContent = message;
    if (error) status.dataset.error = 'true'; else delete status.dataset.error;
  }
  function fit() {
    if (!map || !pointLayer.getLayers().length) return;
    map.fitBounds(pointLayer.getBounds(), {padding:[28,28],maxZoom:13,animate:false});
  }
  function renderProposal() {
    if (proposalMarker) { proposalMarker.remove(); proposalMarker = null; }
    if (!map || !proposal) return;
    proposalMarker = L.marker([proposal.lat,proposal.lon], {
      draggable:true, title:text.proposal, alt:text.proposal,
      icon:L.divIcon({className:'cm-proposed-marker',html:'<span></span>',iconSize:[22,22],iconAnchor:[11,11]})
    }).addTo(map);
    proposalMarker.on('dragend', () => {
      const position = proposalMarker.getLatLng();
      propose({lat:position.lat,lon:position.lng});
    });
  }
  function propose(value) {
    if (!coordinates(value)) return;
    proposal = value;
    byId('cm-proposal').textContent = `${text.proposal}: ${pair(value)}`;
    apply.disabled = !currentForm();
    renderProposal();
  }
  function load() {
    if (map) return true;
    if (typeof L === 'undefined') { report(text.unavailable,true); return false; }
    byId('cm-map').replaceChildren();
    map = L.map('cm-map', {worldCopyJump:true,scrollWheelZoom:false,zoomAnimation:false,fadeAnimation:false,markerZoomAnimation:false}).setView([-15.8,-47.9],4);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).on('tileerror', () => report(text.tiles,true)).addTo(map);
    pointLayer = L.featureGroup().addTo(map);
    config.points.forEach(point => {
      if (!coordinates(point)) return;
      const popup = document.createElement('div'); popup.className = 'cm-record-popup';
      const title = document.createElement('strong'); title.textContent = point.title;
      const label = document.createElement('p'); label.textContent = `${point.label} · ${pair(point)}`;
      const link = document.createElement('a'); link.textContent = text.review; link.href = point.href;
      popup.append(title,label,link);
      L.circleMarker([point.lat,point.lon], {radius:6,color:'#fff',weight:2,fillColor:'#245e78',fillOpacity:1,bubblingMouseEvents:false})
        .bindPopup(popup).addTo(pointLayer);
    });
    map.on('click', event => propose({lat:event.latlng.lat,lon:event.latlng.lng}));
    byId('cm-fit').disabled = !pointLayer.getLayers().length;
    fit(); renderProposal();
    return true;
  }
  byId('cm-load').addEventListener('click', load);
  byId('cm-fit').addEventListener('click', fit);
  if (target) target.addEventListener('change', () => {
    proposal = null; apply.disabled = true; byId('cm-proposal').textContent = text.none; renderProposal();
    const form = currentForm(), lat = form.elements.latitude.value, lon = form.elements.longitude.value;
    if (map && lat !== '' && lon !== '' && coordinates({lat:Number(lat),lon:Number(lon)})) map.setView([Number(lat),Number(lon)],12,{animate:false});
  });
  apply.addEventListener('click', () => {
    const form = currentForm();
    if (!form || !proposal) return;
    form.elements.latitude.value = Number(proposal.lat.toFixed(6));
    form.elements.longitude.value = Number(proposal.lon.toFixed(6));
    forms.forEach(row => row.classList.remove('cm-filled'));
    form.classList.add('cm-filled');
    byId('cm-proposal').textContent = text.filled;
    form.scrollIntoView({block:'center',behavior:'auto'});
    form.elements.latitude.focus({preventScroll:true});
  });
  byId('cm-place-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    busy = true; byId('cm-search').disabled = true; byId('cm-search').setAttribute('aria-busy','true');
    results.replaceChildren(); report(text.loading);
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(),18000);
    try {
      const response = await fetch(config.geocode, {method:'POST',body:new URLSearchParams(new FormData(event.currentTarget)),
        credentials:'same-origin',headers:{Accept:'application/json'},signal:controller.signal});
      const body = await response.json();
      if (!response.ok) { report(text[body.error] || text.unavailable,true); return; }
      if (!body.results.length) { report(text.empty); return; }
      report(`${body.results.length} ${text.found}`);
      body.results.forEach(candidate => {
        const position = {lat:candidate.latitude,lon:candidate.longitude};
        if (!coordinates(position)) return;
        const li = document.createElement('li'), button = document.createElement('button'), numeric = document.createElement('small');
        button.type = 'button'; button.setAttribute('aria-pressed','false');
        button.append(document.createTextNode(candidate.label)); numeric.textContent = pair(position); button.append(numeric);
        button.addEventListener('click', () => {
          results.querySelectorAll('button').forEach(row => row.setAttribute('aria-pressed','false'));
          button.setAttribute('aria-pressed','true');
          if (load()) map.setView([position.lat,position.lon],12,{animate:false});
          propose(position);
        });
        li.append(button); results.append(li);
      });
    } catch (_) { report(text.unavailable,true); }
    finally { clearTimeout(timer); busy = false; byId('cm-search').disabled = false; byId('cm-search').removeAttribute('aria-busy'); }
  });
})();
