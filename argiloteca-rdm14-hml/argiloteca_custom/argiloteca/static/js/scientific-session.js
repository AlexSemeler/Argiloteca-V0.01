/* Local scientific workspace, scoped to this tab and account. No record API. */
(function () {
  'use strict';
  if (window.ArgiloScientificSession) return;
  const config = document.currentScript.dataset;
  const tabKey = 'argiloteca-scientific-tab-v1';
  const lifetime = 24 * 60 * 60 * 1000;
  const documentStartedAt = performance.timeOrigin;
  let beforeNavigate = function () { return Promise.resolve(); };
  let navigating = false;
  let scope;
  let notice;
  let queue = Promise.resolve();
  function report() {
    const root = document.querySelector('.argilo-workbench .awb-body') || document.querySelector('.argilo-drx, .argilo-package');
    if (!root) return;
    if (!notice) {
      notice = document.createElement('p');
      notice.className = 'argilo-error-state';
      notice.setAttribute('role', 'status');
      root.prepend(notice);
    }
    notice.textContent = config.saveError;
    notice.hidden = false;
  }
  const database = new Promise(function (resolve, reject) {
    try {
      let tab = sessionStorage.getItem(tabKey);
      if (!tab) {
        tab = crypto.randomUUID();
        sessionStorage.setItem(tabKey, tab);
      }
      scope = config.user + ':' + tab + ':';
      const request = indexedDB.open('argiloteca-scientific-session', 1);
      request.onupgradeneeded = function () { request.result.createObjectStore('states', { keyPath: 'id' }); };
      request.onerror = function () { reject(request.error); };
      request.onblocked = function () { reject(new Error('Session database blocked')); };
      request.onsuccess = function () {
        const db = request.result;
        db.onversionchange = function () { db.close(); };
        // Old closed-tab files are removed without retaining an indefinite archive.
        const tx = db.transaction('states', 'readwrite');
        const cursor = tx.objectStore('states').openCursor();
        cursor.onsuccess = function () {
          const item = cursor.result;
          if (!item) return;
          if (!item.value.id.startsWith(scope) && (!item.value.updatedAt || Date.now() - item.value.updatedAt > lifetime)) item.delete();
          item.continue();
        };
        resolve(db);
      };
    } catch (error) { reject(error); }
  });
  // Keep rejections available to callers, without an unhandled startup rejection.
  database.catch(report);
  function read(section) {
    return database.then(function (db) {
      return new Promise(function (resolve, reject) {
        const tx = db.transaction('states', 'readonly');
        const request = tx.objectStore('states').get(scope + section);
        request.onsuccess = function () {
          const row = request.result;
          resolve(row && row.version === 1 ? row.value : null);
        };
        request.onerror = function () { reject(request.error); };
        tx.onabort = function () { reject(tx.error); };
      });
    });
  }
  function write(section, value) {
    const result = queue.then(function () {
      return database.then(function (db) {
        return new Promise(function (resolve, reject) {
          const tx = db.transaction('states', 'readwrite');
          tx.oncomplete = resolve;
          tx.onabort = function () { reject(tx.error); };
          tx.onerror = function () { reject(tx.error); };
          const store = tx.objectStore('states');
          const current = store.get(scope + section);
          current.onsuccess = function () {
            // A delayed write from an outgoing/cached document cannot replace
            // a newer document's workspace in the same tab.
            if (current.result && current.result.documentStartedAt > documentStartedAt) return;
            try { store.put({ id: scope + section, version: 1, documentStartedAt: documentStartedAt, updatedAt: Date.now(), value: value }); }
            catch (error) { tx.abort(); reject(error); }
          };
        });
      });
    });
    queue = result.catch(function () {});
    result.then(function () { if (notice) notice.hidden = true; }, report);
    return result;
  }
  function navigate(href) {
    if (navigating) return;
    navigating = true;
    return Promise.resolve().then(beforeNavigate).then(function () {
      window.location.assign(href);
    }).catch(function () {
      navigating = false;
      report();
    });
  }
  document.addEventListener('click', function (event) {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/^\/(analises(?:\/|$)|drx\/comparacao(?:\/|$))/.test(url.pathname)) return;
    event.preventDefault();
    navigate(link.href);
  });
  window.addEventListener('pageshow', function (event) {
    navigating = false;
    // Another scientific page may have changed the workspace while this
    // document was in the back/forward cache. Restore the latest local state.
    if (event.persisted) window.location.reload();
  });
  window.ArgiloScientificSession = {
    get: read, put: write, navigate: navigate, report: report,
    beforeNavigate: function (callback) { beforeNavigate = callback; }
  };
})();
