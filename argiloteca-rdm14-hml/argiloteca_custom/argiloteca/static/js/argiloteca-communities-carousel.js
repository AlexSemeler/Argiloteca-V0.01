/* Public community carousel. No new dependency or changes to native permissions. */
(function () {
  'use strict';
  const root = document.querySelector('[data-community-carousel]');
  if (!root) return;
  const track = root.querySelector('#argilo-community-track');
  const controls = root.querySelector('.argilo-community-carousel__controls');
  const toggle = root.querySelector('[data-carousel-toggle]');
  const position = root.querySelector('[data-carousel-position]');
  const status = root.querySelector('[data-carousel-status]');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false, hovered = false, visible = false, timer, items = [];
  function index() {
    if (!items.length) return 0;
    const gap = parseFloat(getComputedStyle(track).gap) || 0;
    return Math.round(track.scrollLeft / (items[0].getBoundingClientRect().width + gap));
  }
  function schedule() {
    clearTimeout(timer);
    if (!paused && !hovered && visible && !document.hidden && !reduced.matches && items.length > 1) {
      timer = setTimeout(function () { move(1); schedule(); }, 6000);
    }
  }
  function state() {
    toggle.querySelector('[data-carousel-toggle-label]').textContent = paused ? root.dataset.play : root.dataset.pause;
    toggle.setAttribute('aria-pressed', String(paused));
    toggle.hidden = reduced.matches;
    schedule();
  }
  function move(direction) {
    if (!items.length) return;
    const maximum = track.scrollWidth - track.clientWidth;
    const atEnd = track.scrollLeft >= maximum - 2;
    const atStart = track.scrollLeft < 2;
    const gap = parseFloat(getComputedStyle(track).gap) || 0;
    const stride = items[0].getBoundingClientRect().width + gap;
    const wrap = direction > 0 ? atEnd : atStart;
    const left = wrap ? (direction > 0 ? 0 : maximum) : Math.min(maximum, Math.max(0, (index() + direction) * stride));
    track.scrollTo({ left: left, behavior: reduced.matches || wrap ? 'auto' : 'smooth' });
  }
  function stop() { paused = true; state(); }
  root.querySelector('[data-carousel-prev]').addEventListener('click', function () { stop(); move(-1); });
  root.querySelector('[data-carousel-next]').addEventListener('click', function () { stop(); move(1); });
  toggle.addEventListener('click', function () { paused = !paused; state(); });
  root.addEventListener('focusin', function (event) { if (event.target !== toggle) stop(); });
  root.addEventListener('pointerenter', function (event) { if (event.pointerType === 'mouse') { hovered = true; schedule(); } });
  root.addEventListener('pointerleave', function () { hovered = false; schedule(); });
  track.addEventListener('pointerdown', stop);
  track.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault(); stop(); move(event.key === 'ArrowRight' ? 1 : -1);
    }
  });
  track.addEventListener('scroll', function () {
    position.textContent = root.dataset.position.replace('{0}', index() + 1).replace('{1}', items.length);
  }, { passive: true });
  document.addEventListener('visibilitychange', schedule);
  reduced.addEventListener('change', state);
  new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; schedule(); }).observe(root);
  const controller = new AbortController();
  const timeout = setTimeout(function () { controller.abort(); }, 15000);
  fetch('/api/communities?size=100&sort=newest', { headers: { Accept: 'application/json' }, signal: controller.signal })
    .then(function (response) { if (!response.ok) throw Error(response.status); return response.json(); })
    .then(function (payload) {
      const communities = payload.hits.hits;
      if (!communities.length) { status.textContent = root.dataset.empty; return; }
      communities.forEach(function (community) {
        const item = document.createElement('article'); item.className = 'argilo-community-carousel__item';
        const link = document.createElement('a'); link.href = '/communities/' + encodeURIComponent(community.slug) + '/';
        const image = document.createElement('img');
        image.src = new URL(community.links.logo, location.origin).pathname;
        image.alt = ''; image.width = 480; image.height = 300; image.loading = 'lazy';
        const heading = document.createElement('h3'); heading.textContent = community.metadata.title;
        link.append(image, heading);
        const description = document.createElement('p');
        description.textContent = new DOMParser().parseFromString(community.metadata.description || '', 'text/html').body.textContent;
        item.append(link, description); track.append(item);
      });
      items = Array.from(track.children);
      status.hidden = true; controls.hidden = items.length < 2;
      position.textContent = root.dataset.position.replace('{0}', 1).replace('{1}', items.length);
      state();
    })
    .catch(function () { status.textContent = root.dataset.error; })
    .finally(function () { clearTimeout(timeout); });
})();
