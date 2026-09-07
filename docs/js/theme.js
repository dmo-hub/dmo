/* DMO Tracker — theme toggle
 * Sets [data-theme="light"|"dark"] on <html>, persists choice in localStorage,
 * injects a sun/moon button into .site-nav-inner. Loaded synchronously in
 * <head> BEFORE the stylesheet so the theme applies before first paint. */
(function () {
  var STORAGE_KEY = 'dmo-theme';
  var root = document.documentElement;

  function getInitial() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved === 'dark' || saved === 'light') return saved;
    } catch (e) { /* localStorage may be unavailable */ }
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  }

  function setTheme(theme, persist) {
    root.setAttribute('data-theme', theme);
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) {}
    }
    var btn = document.querySelector('.theme-toggle');
    if (btn) {
      btn.setAttribute('data-current', theme);
      btn.setAttribute('aria-label',
        theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    }
  }

  // Apply immediately (runs before stylesheet renders → no FOUC)
  setTheme(getInitial(), false);

  function init() {
    var nav = document.querySelector('.site-nav-inner');
    if (!nav || nav.querySelector('.theme-toggle')) return;

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-toggle';
    btn.innerHTML =
      '<svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<circle cx="12" cy="12" r="4"/>' +
        '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>' +
      '</svg>' +
      '<svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>' +
      '</svg>';
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      setTheme(next, true);
    });
    nav.appendChild(btn);
    setTheme(root.getAttribute('data-theme') || 'light', false);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Follow OS-level changes if the user hasn't pinned a choice
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener && mq.addEventListener('change', function (e) {
      var saved;
      try { saved = localStorage.getItem(STORAGE_KEY); } catch (err) {}
      if (saved !== 'dark' && saved !== 'light') {
        setTheme(e.matches ? 'dark' : 'light', false);
      }
    });
  }
})();

/* Bring the current page's nav link into view.
 * Under 720px the nav row scrolls sideways, so on a page whose link sits late
 * in the list -- Gear Optimizer is 500px in at 360px wide -- the reader opens
 * the page and cannot see which one they are on. Scrolling the row is enough;
 * the page itself never moves. */
(function () {
  /* The fade on the right edge means the last link is never fully visible.
     Drop it once there is nothing further to scroll to. */
  function markEnd(nav) {
    var atEnd = nav.scrollLeft >= nav.scrollWidth - nav.clientWidth - 1;
    nav.classList.toggle('is-scroll-end', atEnd);
  }

  function reveal() {
    var nav = document.querySelector('.site-nav nav');
    if (!nav || nav.scrollWidth <= nav.clientWidth) return;
    var active = nav.querySelector('.is-active');
    if (!active) return;
    var navBox = nav.getBoundingClientRect();
    var box = active.getBoundingClientRect();
    if (box.left >= navBox.left && box.right <= navBox.right) return;
    /* offsetLeft is measured from offsetParent, which is not this nav (it is
       not positioned), so it cannot be used here. The distance from the row's
       current scroll position is what actually moves it. */
    var delta = box.left - navBox.left;
    var want = nav.scrollLeft + delta - (nav.clientWidth - box.width) / 2;
    nav.scrollLeft = Math.max(0, Math.min(want, nav.scrollWidth - nav.clientWidth));
    markEnd(nav);
  }
  function bind() {
    var nav = document.querySelector('.site-nav nav');
    if (!nav) return;
    reveal();
    /* Link widths are not final until the webfont lands, and a first pass
       measured against fallback metrics lands short of the end. */
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(reveal);
    }
    window.addEventListener('resize', reveal);
    nav.addEventListener('scroll', function () { markEnd(nav); }, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
