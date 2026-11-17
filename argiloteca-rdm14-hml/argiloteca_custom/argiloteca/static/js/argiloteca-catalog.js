/* Shared map data, matched only to explicit authorized mineral names. */
(function () {
  "use strict";

  function translate(value) {
    return typeof window !== "undefined" && typeof window.argiloT === "function" ? window.argiloT(value) : value;
  }

  function key(value) {
    return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  function coordinate(value, limit) {
    if (value === null || value === undefined || String(value).trim() === "") return null;
    const result = Number(String(value).replace(",", "."));
    return Number.isFinite(result) && Math.abs(result) <= limit ? result : null;
  }

  function pointNames(point) {
    const names = Array.isArray(point.argilominerais) ? point.argilominerais.slice() : [];
    if (point.kind === "argilomineral") names.push(point.label || point.nome);
    return names;
  }

  function filterMineralPoints(points, names) {
    const aliases = new Set(names.map(key).filter(Boolean));
    return points.filter(function (point) {
      return pointNames(point).some(function (name) { return aliases.has(key(name)); });
    });
  }

  function summarizePoints(points, minerals) {
    const aliases = new Map();
    const summaries = new Map();
    minerals.forEach(function (mineral) {
      summaries.set(mineral.slug, { records: new Set(), points: new Map() });
      mineral.names.forEach(function (name) {
        if (key(name)) aliases.set(key(name), mineral.slug);
      });
    });
    const records = new Set();
    const positions = new Set();
    points.forEach(function (point) {
      const latitude = coordinate(point.latitude ?? point.lat, 90);
      const longitude = coordinate(point.longitude ?? point.lon, 180);
      const record = String(point.record_id || point.id || "");
      if (latitude === null || longitude === null || !record) return;
      const identity = JSON.stringify([record, latitude, longitude]);
      records.add(record);
      positions.add(identity);
      const names = pointNames(point);
      const matched = new Set(names.map(function (name) { return aliases.get(key(name)); }).filter(Boolean));
      matched.forEach(function (slug) {
        const summary = summaries.get(slug);
        summary.records.add(record);
        summary.points.set(identity, {
          record: record,
          latitude: latitude,
          longitude: longitude,
          title: point.title || record,
          location: (point.sample_locations || []).join("; ") || point.sample_location || translate("Localidade não informada"),
          source: point.dataset_source || translate("Registro da Argiloteca")
        });
      });
    });
    return { summaries: summaries, records: records.size, points: positions.size };
  }

  // Keep the aggregation independently testable without a browser or network.
  const api = { summarizePoints: summarizePoints, filterMineralPoints: filterMineralPoints };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.ArgilotecaGeoreferences = api;
  if (typeof document === "undefined") return;

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function showImageFailure(img) {
    if (img.dataset.failed) return;
    img.dataset.failed = "true";
    const figure = img.closest("figure");
    const caption = figure.querySelector("[data-image-scope]");
    const unavailable = element("span", window.argiloT("Imagem indisponível"), "argilo-catalog-image-empty");
    img.replaceWith(unavailable);
    if (caption) caption.textContent = window.argiloT("A imagem não carregou. Consulte a fonte abaixo.");
  }

  function renderSummary(container, summary, mapUrl) {
    container.replaceChildren();
    const points = Array.from(summary.points.values());
    if (!points.length) {
      container.append(element("p", window.argiloT("Sem coordenadas associadas a este termo no acervo atual.")));
      return;
    }
    const details = element("details");
    details.append(element("summary", summary.records.size + window.argiloT(" registro(s) georreferenciado(s) · ") + points.length + " ponto(s) — consultar coordenadas"));
    const list = element("ul", undefined, "argilo-catalog-locations");
    points.slice(0, 5).forEach(function (point) {
      const row = element("li");
      const link = element("a", point.title);
      link.href = "/records/" + encodeURIComponent(point.record);
      row.append(link);
      row.append(element("p", "Latitude " + point.latitude.toFixed(5) + " · Longitude " + point.longitude.toFixed(5)));
      row.append(element("p", point.location + " · Fonte: " + point.source));
      list.append(row);
    });
    details.append(list);
    if (points.length > 5) details.append(element("p", window.argiloT("Exibindo 5 de ") + points.length + " pontos."));
    const mapLink = element("a", "Consultar todos os pontos deste mineral no mapa");
    mapLink.href = mapUrl;
    details.append(mapLink);
    container.append(details);
  }

  function boot() {
    const root = document.querySelector("[data-catalog-points-url]");
    if (!root) return;
    root.querySelectorAll(".argilo-catalog-item-media img").forEach(function (img) {
      img.addEventListener("error", function () { showImageFailure(img); }, { once: true });
      if (img.complete && !img.naturalWidth) showImageFailure(img);
    });
    const cards = Array.from(root.querySelectorAll("[data-mineral-slug]"));
    const minerals = cards.map(function (card) {
      return { slug: card.dataset.mineralSlug, names: JSON.parse(card.dataset.mineralNames) };
    });
    const status = root.querySelector("[data-catalog-geo-status]");
    const retry = root.querySelector("[data-catalog-geo-retry]");
    async function load() {
      retry.hidden = true;
      status.textContent = window.argiloT("Carregando dados georreferenciados do mapa…");
      const controller = new AbortController();
      const timer = setTimeout(function () { controller.abort(); }, 45000);
      try {
        const response = await fetch(root.dataset.catalogPointsUrl, {
          headers: { Accept: "application/json" }, signal: controller.signal
        });
        if (!response.ok) throw new Error(window.argiloTranslateError("HTTP " + response.status));
        const payload = await response.json();
        if (!payload.success || !Array.isArray(payload.points)) throw new Error(window.argiloT("Dados indisponíveis"));
        const result = summarizePoints(payload.points, minerals);
        status.textContent = result.records + window.argiloT(" registros georreferenciados · ") + result.points + " pontos no mapa.";
        cards.forEach(function (card) {
          renderSummary(card.querySelector("[data-mineral-geo]"), result.summaries.get(card.dataset.mineralSlug), card.dataset.mapUrl);
        });
      } catch (error) {
        status.textContent = window.argiloT("Não foi possível carregar os dados georreferenciados. Tente novamente.");
        retry.hidden = false;
        cards.forEach(function (card) {
          card.querySelector("[data-mineral-geo]").textContent = window.argiloT("Consulta de coordenadas indisponível no momento.");
        });
      } finally {
        clearTimeout(timer);
      }
    }
    retry.addEventListener("click", load);
    load();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
