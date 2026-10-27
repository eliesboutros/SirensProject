/* Sirens shared form behaviour (local file, no network):
   - (i) help: opens on hover, tap or keyboard focus; Escape or a click elsewhere closes it.
   - Checks each field as the analyst leaves it, using only the rules that exist today
     (data-rules="required number range:a,b pair:<id>"), plus two notes that never block
     saving: date format advice and "not a known place".
   - On submit: blocks only on real errors, opens "More details" if an error is inside,
     and shows "Saving…" on the button that was pressed. */
(function () {
  'use strict';

  // ---------------------------------------------------------------- help (i)
  var openTip = null, pinned = false;
  function tipFor(btn) { return document.getElementById(btn.getAttribute('aria-controls')); }
  function show(btn, pin) {
    if (openTip && openTip !== btn) hide(openTip);
    var tip = tipFor(btn); if (!tip) return;
    tip.hidden = false; btn.setAttribute('aria-expanded', 'true'); openTip = btn; pinned = !!pin;
    tip.style.left = '0px';
    var r = tip.getBoundingClientRect();
    if (r.right > window.innerWidth - 8) tip.style.left = (window.innerWidth - 8 - r.right) + 'px';
  }
  function hide(btn) {
    var tip = tipFor(btn); if (tip) tip.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    if (openTip === btn) { openTip = null; pinned = false; }
  }
  document.addEventListener('mouseover', function (e) {
    var b = e.target.closest && e.target.closest('.f-help'); if (b && !pinned) show(b, false);
  });
  document.addEventListener('mouseout', function (e) {
    var b = e.target.closest && e.target.closest('.f-help');
    if (b && !pinned && !b.contains(e.relatedTarget)) hide(b);
  });
  document.addEventListener('focusin', function (e) {
    if (e.target.classList && e.target.classList.contains('f-help')) show(e.target, false);
  });
  document.addEventListener('focusout', function (e) {
    if (e.target.classList && e.target.classList.contains('f-help') && !pinned) hide(e.target);
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.f-help');
    if (b) { e.preventDefault(); if (openTip === b && pinned) hide(b); else show(b, true); return; }
    if (openTip && !(e.target.closest && e.target.closest('.f-tip'))) hide(openTip);
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && openTip) { var b = openTip; hide(b); b.focus(); } });

  // ---------------------------------------------------------------- checks
  function labelOf(el) {
    var l = document.querySelector('label[for="' + el.id + '"]');
    return l ? l.childNodes[0].textContent.trim() : 'This field';
  }
  // A field counts unless something around it is switched off (display:none), e.g. the
  // UTM row while Lat/Lon is chosen. Fields inside a closed "More details" still count.
  function visible(el) {
    for (var n = el; n && n !== document.body; n = n.parentElement) {
      if (n.tagName === 'DETAILS') return true;
      if (getComputedStyle(n).display === 'none') return false;
    }
    return true;
  }
  function slot(el) { return document.getElementById('e-' + el.id); }
  function setMsg(el, msg, blocking) {
    var s = slot(el); if (!s) return;
    s.textContent = msg || '';
    s.classList.toggle('f-note', !!msg && !blocking);
    s.classList.toggle('f-error', !msg || blocking);
    if (blocking && msg) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid');
    if (msg && blocking) { var d = el.closest('details'); if (d) d.open = true; }
  }
  function num(v) { return v.trim() !== '' && !isNaN(Number(v.trim().replace(',', '.'))); }

  // Returns [message, blocking] for one field.
  function check(el) {
    var rules = (el.getAttribute('data-rules') || '').split(/\s+/).filter(Boolean);
    var v = (el.value || '').trim();
    if (!visible(el)) return ['', false];
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (r === 'required' && !v) return [el.getAttribute('data-required-msg') || (labelOf(el) + ' is required.'), true];
      if (r === 'number' && v && !num(v)) return ['Enter a number (digits only).', true];
      if (r.indexOf('range:') === 0 && v && num(v)) {
        var mm = r.slice(6).split(','), x = Number(v.replace(',', '.'));
        if (x < Number(mm[0]) || x > Number(mm[1])) return ['Must be between ' + mm[0] + ' and ' + mm[1] + '.', true];
      }
      if (r.indexOf('pair:') === 0) {
        var other = document.getElementById(r.slice(5));
        if (other && visible(other) && !v && other.value.trim())
          return ['Fill in ' + labelOf(el).toLowerCase() + ' too, or leave both empty.', true];
      }
    }
    for (var j = 0; j < rules.length; j++) {
      var a = rules[j];
      if (a === 'date-advisory' && v && !/^\d{4}-\d{2}-\d{2}$/.test(v))
        return ['This does not look like YYYY-MM-DD. It will be kept exactly as written.', false];
      if (a.indexOf('place:') === 0 && v) {
        var parts = a.slice(6).split(':'), list = document.getElementById(parts[0]);
        var caza = parts[1] ? document.getElementById(parts[1]) : null;
        var known = false;
        if (list) for (var k = 0; k < list.options.length; k++)
          if (list.options[k].value.toLowerCase() === v.toLowerCase()) { known = true; break; }
        if (!known && !(caza && caza.value))
          return [el.getAttribute('data-place-msg') || 'Not a known place; it may not appear on the map.', false];
      }
    }
    return ['', false];
  }
  function run(el) { var res = check(el); setMsg(el, res[0], res[1]); return res; }

  document.addEventListener('focusout', function (e) {
    var el = e.target;
    if (!el.getAttribute || !el.getAttribute('data-rules')) return;
    run(el);
    // re-check the partner of a pair so its message clears or appears too
    (el.getAttribute('data-rules').match(/pair:(\S+)/) || []).slice(1).forEach(function (id) {
      var o = document.getElementById(id); if (o) run(o);
    });
  });
  document.addEventListener('input', function (e) {
    var el = e.target;
    if (el.getAttribute && el.getAttribute('aria-invalid') === 'true') run(el);
  });
  document.addEventListener('change', function (e) {   // caza chosen -> place note may no longer apply
    if (e.target.tagName === 'SELECT') document.querySelectorAll('[data-rules*="place:"]').forEach(function (el) {
      if (el.value) run(el);
    });
  });

  // ---------------------------------------------------------------- submit
  // Capture phase, so an invalid htmx form never sends a request.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.classList || !form.classList.contains('f-form')) return;
    var first = null;
    form.querySelectorAll('[data-rules]').forEach(function (el) {
      var res = run(el);
      if (res[0] && res[1] && !first) first = el;
    });
    if (first) { e.preventDefault(); e.stopImmediatePropagation(); first.focus(); return; }
    if (form.dataset.busy === '1') { e.preventDefault(); e.stopImmediatePropagation(); return; }
    var btn = e.submitter;
    if (btn && btn.hasAttribute('data-busy-text')) {
      btn.dataset.idle = btn.textContent; btn.textContent = btn.getAttribute('data-busy-text');
      btn.setAttribute('aria-busy', 'true'); form.dataset.busy = '1';
    }
  }, true);
  // htmx forms: restore the button when the request finishes (the card is usually swapped anyway).
  document.addEventListener('htmx:afterRequest', function (e) {
    var form = e.target.closest && e.target.closest('form.f-form'); if (!form) return;
    form.dataset.busy = '';
    form.querySelectorAll('[aria-busy="true"]').forEach(function (b) {
      b.textContent = b.dataset.idle || b.textContent; b.removeAttribute('aria-busy');
    });
  });
  // Back/forward cache: never leave a button stuck on "Saving…".
  window.addEventListener('pageshow', function () {
    document.querySelectorAll('form.f-form').forEach(function (f) { f.dataset.busy = ''; });
    document.querySelectorAll('[aria-busy="true"]').forEach(function (b) {
      b.textContent = b.dataset.idle || b.textContent; b.removeAttribute('aria-busy');
    });
  });
})();
