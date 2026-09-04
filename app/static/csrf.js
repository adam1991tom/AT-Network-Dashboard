(function () {
  // Attaches the CSRF cookie to every same-origin state-changing fetch() call,
  // so individual pages/scripts don't each need to remember to do it.
  function readCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : null;
  }
  const originalFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const method = ((init && init.method) || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      const token = readCookie('at_csrf');
      if (token) {
        init = init || {};
        const headers = new Headers(init.headers || (typeof input === 'object' ? input.headers : undefined));
        headers.set('X-CSRF-Token', token);
        init = Object.assign({}, init, { headers });
      }
    }
    return originalFetch(input, init);
  };
})();
