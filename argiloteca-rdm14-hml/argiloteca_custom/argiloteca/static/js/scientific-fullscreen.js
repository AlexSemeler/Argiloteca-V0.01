/* Keep the scientific workspace expanded across page loads and file dialogs.
 * Native fullscreen is best effort: browsers may leave it for navigation,
 * another window or a file picker. The CSS workspace remains until explicit exit.
 */
(function () {
  'use strict';
  const key = 'argiloteca-scientific-expanded-v1';
  const root = document.querySelector('[data-role="drx-fullscreen-section"], [data-role="analysis-fullscreen-section"], .argilo-package');
  const selector = '[data-role="drx-header-fullscreen"], [data-role="mineral-panel-fullscreen"], [data-role="analysis-fullscreen"], [data-role="package-fullscreen"]';
  const config = document.currentScript.dataset;
  function remember(active) {
    try {
      if (active) sessionStorage.setItem(key, 'true');
      else sessionStorage.removeItem(key);
    } catch (_) { /* This page remains usable without session storage. */ }
  }
  if (!root) { remember(false); return; }
  const className = root.classList.contains('argilo-drx__main') ? 'argilo-drx__main--fullscreen' : 'argilo-package--fullscreen';
  const originalOverflow = document.body.style.overflow;
  let expanded = false;
  function render() {
    root.classList.toggle(className, expanded);
    document.body.style.overflow = expanded ? 'hidden' : originalOverflow;
    document.querySelectorAll(selector).forEach(function (button) {
      const label = expanded ? config.exitLabel : config.enterLabel;
      (button.querySelector('[data-button-label]') || button).textContent = label;
      button.setAttribute('aria-pressed', String(expanded));
    });
  }
  try { expanded = sessionStorage.getItem(key) === 'true'; } catch (_) { /* No persisted preference. */ }
  render();
  // Capture only these controls; the legacy page controllers remain a fallback
  // if this shared script cannot load, without running a second toggle here.
  document.addEventListener('click', function (event) {
    const button = event.target.closest(selector);
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    expanded = !expanded;
    remember(expanded);
    render();
    if (expanded && !document.fullscreenElement && root.requestFullscreen) {
      root.requestFullscreen().catch(render);
    } else if (!expanded && document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(render);
    }
  }, true);
  document.addEventListener('fullscreenchange', function () {
    // Do not collapse when Firefox leaves native fullscreen for a file dialog.
    if (document.fullscreenElement === root) { expanded = true; remember(true); }
    render();
  });
})();
