/* Poll only while a background task runs; never replace an active review form. */
(() => {
  'use strict';
  if (document.querySelector('[data-oa-poll]')) {
    window.setTimeout(() => {
      if (document.visibilityState === 'visible') window.location.reload();
      else document.addEventListener('visibilitychange', () => window.location.reload(), {once: true});
    }, 10000);
  }
  document.querySelectorAll('.oa-workspace form[method="post"]').forEach(form => {
    form.addEventListener('submit', event => {
      // Disabled submit buttons are omitted from the POST body. Preserve the
      // clicked action before preventing double submission.
      if (event.submitter && event.submitter.name) {
        const action = document.createElement('input');
        action.type = 'hidden';
        action.name = event.submitter.name;
        action.value = event.submitter.value;
        form.appendChild(action);
      }
      form.querySelectorAll('button[type="submit"]').forEach(button => {
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
      });
    });
  });
})();
