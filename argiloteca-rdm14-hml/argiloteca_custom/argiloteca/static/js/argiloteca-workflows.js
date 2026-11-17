/* Progressive mobile navigation; resource actions remain native. */
/* Native resource templates replace admin_main_column; retain the shell's target. */
(() => {
  const main = document.querySelector('.argilo-admin-shell main');
  if (main && !main.id) {
    main.id = 'admin-main-content';
    main.tabIndex = -1;
  }
})();
(() => {
  const button = document.getElementById('argilo-admin-toggle');
  const menu = document.getElementById('admin-side-menu');
  if (!button || !menu) return;
  const mobile = matchMedia('(max-width: 991px)');
  const setOpen = open => { menu.hidden = !open; button.setAttribute('aria-expanded', String(open)); };
  const adapt = () => setOpen(!mobile.matches);
  button.addEventListener('click', () => setOpen(menu.hidden));
  button.addEventListener('keydown', event => { if (event.key === 'Escape') setOpen(false); });
  menu.addEventListener('keydown', event => { if (event.key === 'Escape' && mobile.matches) { setOpen(false); button.focus(); } });
  mobile.addEventListener('change', adapt);
  adapt();
})();

/* Native search facets mount after the shell; name both publication-year sliders. */
(() => {
  const root = document.querySelector('.argilo-admin-shell #admin-main-content');
  if (!root) return;
  const portuguese = document.documentElement.lang.toLowerCase().startsWith('pt');
  const labels = [
    ['.searchkit-daterange-thumb-left', portuguese ? 'Ano inicial de publicação' : 'Publication start year'],
    ['.searchkit-daterange-thumb-right', portuguese ? 'Ano final de publicação' : 'Publication end year']
  ];
  const labelRanges = () => {
    for (const [selector, label] of labels) {
      for (const input of root.querySelectorAll(selector)) {
        if (!input.hasAttribute('aria-label') && !input.hasAttribute('aria-labelledby')) input.setAttribute('aria-label', label);
      }
    }
  };
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; labelRanges(); });
  }).observe(root, {childList: true, subtree: true});
  labelRanges();
})();

/* Close the native account menu through its own toggle, including on mobile. */
(() => {
  const account = document.querySelector('.argilo-admin-utilities #user-profile-dropdown');
  const button = account?.querySelector('#user-profile-dropdown-btn');
  if (!account || !button) return;
  account.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || button.getAttribute('aria-expanded') !== 'true') return;
    event.preventDefault();
    event.stopPropagation();
    button.click();
    button.focus();
  });
})();
