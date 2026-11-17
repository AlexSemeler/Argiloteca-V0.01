/* User-initiated window, with an ordinary link as fallback. */
(function () {
  'use strict';
  let assistantWindow = null;
  const baseUrl = new URL('/argiloclay', location.origin);
  function contextUrl() {
    const url = new URL(baseUrl);
    url.searchParams.set('source', location.pathname);
    const pathRecord = location.pathname.match(/^\/(?:records|analises)\/([A-Za-z0-9_-]+)\/?$/);
    const record = pathRecord?.[1] || new URLSearchParams(location.search).get('record_id');
    if (record && /^[A-Za-z0-9_-]{1,100}$/.test(record)) url.searchParams.set('record_id', record);
    const mineral = location.pathname.match(/^\/argilominerais\/([a-z0-9_-]+)\/?$/);
    if (mineral) url.searchParams.set('term', mineral[1]);
    if (window.BroadcastChannel) {
      const token = crypto.randomUUID(); url.searchParams.set('context', token);
      const channel = new BroadcastChannel('argiloclay-context-' + token);
      channel.onmessage = function (event) {
        if (event.data?.type !== 'request-context') return;
        const selection = typeof window.ArgiloClaySelectionContext === 'function' ? window.ArgiloClaySelectionContext() : [];
        channel.postMessage({type:'page-context', context:{selection:selection.slice(0,6)}});
      };
      setTimeout(function () { channel.close(); }, 30000);
    }
    return url.href;
  }
  const fullscreenPanels = Array.from(document.querySelectorAll('.argilo-drx__main, .argilo-package'));
  document.querySelectorAll('.argilo-robo-launcher').forEach(function (link) {
    // Native fullscreen only renders descendants of its target. Move the same
    // launcher (and its event handlers) rather than cloning an inaccessible copy.
    const home = document.createComment('ArgiloClay launcher position');
    link.before(home);
    function syncFullscreen() {
      const target = document.fullscreenElement || fullscreenPanels.find(function (panel) {
        return panel.classList.contains('argilo-drx__main--fullscreen') || panel.classList.contains('argilo-package--fullscreen');
      });
      const dock = (target || document).querySelector('.argilo-workbench .awb-dock, .awb-dock');
      const parent = dock || target || home.parentNode;
      if (!parent || link.parentNode === parent) return;
      const focused = document.activeElement === link;
      if (dock || target) parent.appendChild(link);
      else home.after(link);
      if (focused) link.focus({ preventScroll: true });
    }
    document.addEventListener('fullscreenchange', syncFullscreen);
    // Panels also support a CSS fallback when native fullscreen is unavailable.
    const observer = new MutationObserver(syncFullscreen);
    fullscreenPanels.forEach(function (panel) {
      observer.observe(panel, { attributes: true, attributeFilter: ['class'] });
    });
    syncFullscreen();
    function openAssistant() {
      if (assistantWindow && !assistantWindow.closed) {
        assistantWindow.location.href = link.href;
        assistantWindow.focus();
        return true;
      }
      // A named target can reuse an old browser tab instead of a popup window.
      assistantWindow = window.open(link.href, '_blank', 'popup=yes,width=1280,height=860,resizable=yes,scrollbars=yes');
      if (assistantWindow) { assistantWindow.opener = null; assistantWindow.focus(); }
      return Boolean(assistantWindow);
    }
    link.addEventListener('click', function (event) {
      // Modified clicks retain an ordinary, contextual same-origin link.
      link.href = contextUrl();
      if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      if (document.fullscreenElement && document.exitFullscreen) {
        // Firefox may send a new window behind the native fullscreen space.
        // Keep the scientific CSS workspace expanded while opening the chat.
        event.preventDefault();
        document.exitFullscreen().then(function () {
          if (!openAssistant()) window.open(link.href, 'ArgiloClayRobo', 'noopener');
        }).catch(openAssistant);
        return;
      }
      if (openAssistant()) event.preventDefault();
    });
  });
})();
