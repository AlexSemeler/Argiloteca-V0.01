/* Argiloteca UI messages. Catalogs contain interface text only, never record data. */
(function () {
  "use strict";
  const messages = window.ArgilotecaMessages || {};
  window.argiloLocale = document.documentElement.lang.startsWith("pt") ? "pt-BR" : "en";
  window.argiloT = function (message, values) {
    if (typeof message !== "string") return message;
    const translated = Object.prototype.hasOwnProperty.call(messages, message)
      ? messages[message] : message;
    return values ? translated.replace(/\{(\d+)\}/g, function (match, index) {
      return index < values.length ? String(values[index]) : match;
    }) : translated;
  };
  window.argiloTranslateError = function (message) { return window.argiloT(message); };
  function localizeVisualizationControls() {
    if (window.Plotly && window.argiloLocale === "pt-BR") {
      window.Plotly.register({
        moduleType: "locale", name: "pt-BR",
        dictionary: {
          "Download plot as a png": "Baixar gráfico como PNG",
          "Zoom": "Zoom", "Pan": "Mover", "Zoom in": "Ampliar",
          "Zoom out": "Reduzir", "Autoscale": "Ajustar escala",
          "Reset axes": "Restaurar eixos", "Box Select": "Seleção retangular",
          "Lasso Select": "Seleção livre", "Toggle Spike Lines": "Alternar linhas-guia",
          "Show closest data on hover": "Mostrar o dado mais próximo",
          "Compare data on hover": "Comparar dados ao passar o cursor",
          "Double-click to zoom back out": "Clique duas vezes para restaurar o zoom"
        },
        format: { decimal: ",", thousands: "." }
      });
      window.Plotly.setPlotConfig({ locale: "pt-BR" });
    }
    if (window.L && window.L.Control && window.L.Control.Zoom && window.argiloLocale === "pt-BR") {
      window.L.Control.Zoom.mergeOptions({ zoomInTitle: "Ampliar", zoomOutTitle: "Reduzir" });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", localizeVisualizationControls, { once: true });
  } else {
    localizeVisualizationControls();
  }
}());
