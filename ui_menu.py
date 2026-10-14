"""Shared top menu: the same grouped drop-down menus on every page.

register(app) makes `sirens_menu(active)` available in every Jinja template;
pages that build HTML without Jinja (linker/report.py) receive the rendered
string instead. `active` is the page key below, so the current page and its
group are highlighted.

The menu carries its own scoped styles (class prefix "sm-") so each page's
existing CSS cannot change how it looks. It opens on hover, click or keyboard
focus and closes with Escape or a click elsewhere. No network, no build step.
"""
from __future__ import annotations

from flask import url_for
from markupsafe import Markup, escape

# (group, [(page key, label, endpoint, one-line description), ...])
MENU = [
    ("Reports", [
        ("console", "New report", "index", "Paste, analyse and file an incident report"),
        ("brief", "Pre-arrival brief", "brief.brief_page", "What past reporting says about a place"),
    ]),
    ("Analysis", [
        ("dashboard", "Dashboard", "dashboard.dashboard_page", "Statistics and charts over the record"),
        ("review", "Review links", "review.review_page", "Confirm, reject or flag each link"),
        ("tree", "Link tree", "link_tree", "Graph of linked incidents and networks"),
        ("map", "Map", "incident_map", "Offline street map, incidents and MGRS grid"),
    ]),
    ("Data", [
        ("demo", "Load demo data", "demo.demo_page", "40 fabricated sample incidents"),
        ("vendor", "Offline check", "vendor.vendor_check", "Proves the page libraries load without internet"),
    ]),
]

PAGES = {key for _, items in MENU for key, *_ in items}

_STYLE = """<style>
.sm{display:flex;gap:6px;align-items:center;position:relative;z-index:50;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.sm .sm-group{position:relative}
.sm .sm-head{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:11.5px;letter-spacing:.04em;
  color:#cdd8e0;background:transparent;border:1px solid #2c3c4a;border-radius:3px;padding:6px 11px;cursor:pointer;
  display:flex;align-items:center;gap:6px;line-height:1.2}
.sm .sm-head:hover,.sm .sm-group.open .sm-head,.sm .sm-group:focus-within .sm-head{border-color:#5b6b78;color:#fff}
.sm .sm-head.on{border-color:#a8703a;color:#fff}
.sm .sm-caret{font-size:9px;opacity:.8}
.sm .sm-panel{display:none;position:absolute;left:0;top:100%;padding-top:8px;min-width:280px}
.sm .sm-group:hover .sm-panel,.sm .sm-group.open .sm-panel,.sm .sm-group:focus-within .sm-panel{display:block}
.sm .sm-group.shut .sm-panel{display:none}
.sm .sm-card{background:#fff;border:1px solid #e2e6e3;border-radius:8px;padding:6px;
  box-shadow:0 2px 6px rgba(22,32,43,.08),0 12px 32px rgba(22,32,43,.14)}
.sm .sm-panel a.sm-item{display:block;margin:0;border:0;border-left:3px solid transparent;border-radius:5px;
  padding:9px 12px;text-decoration:none;color:#16202b;background:transparent;font-family:inherit;font-size:14px;line-height:1.3}
.sm .sm-panel a.sm-item:hover,.sm .sm-panel a.sm-item:focus{background:#f4f6f3;outline:none}
.sm .sm-panel a.sm-item.on{border-left-color:#a8703a;background:#f0e6d4}
.sm .sm-panel a.sm-item strong{display:block;font-weight:600}
.sm .sm-panel a.sm-item span{display:block;font-size:12px;color:#7a8791;margin-top:2px}
.sm .sm-panel a.sm-item.on span{color:#7a4e12}
.sm-host{transition:box-shadow .2s ease}
.sm-host.sm-scrolled{box-shadow:0 2px 10px rgba(22,32,43,.18)}
</style>"""

_SCRIPT = """<script>
(function(){
  // .open = opened by click/keyboard; .shut = closed on purpose, so hover
  // does not reopen it until the pointer leaves.
  var groups = document.querySelectorAll('.sm .sm-group');
  // Pin the bar holding the menu to the top of the page (sticky keeps it in the
  // page flow, so no content hides under it) and lift it above the page body,
  // so an open panel is never covered by content sharing the bar's layer.
  document.querySelectorAll('.sm').forEach(function(nav){
    var host = nav.parentElement;
    host.classList.add('sm-host');
    host.style.position = 'sticky';
    host.style.top = '0';
    host.style.zIndex = '40';
    function fit(){   // anchors (#section links) land just below the pinned bar
      document.documentElement.style.scrollPaddingTop = (host.offsetHeight + 12) + 'px'; }
    function shade(){ host.classList.toggle('sm-scrolled', window.scrollY > 4); }
    fit(); shade();
    window.addEventListener('resize', fit);
    window.addEventListener('scroll', shade, {passive: true});
  });
  function set(g, open){ g.classList.toggle('open', open); g.classList.toggle('shut', !open);
    g.querySelector('.sm-head').setAttribute('aria-expanded', open ? 'true' : 'false'); }
  groups.forEach(function(g){
    g.querySelector('.sm-head').addEventListener('click', function(e){
      e.preventDefault(); var open = !g.classList.contains('open');
      groups.forEach(function(o){ if (o !== g) set(o, false); }); set(g, open); });
    g.addEventListener('mouseleave', function(){ g.classList.remove('shut'); });
  });
  document.addEventListener('click', function(e){ if (!e.target.closest('.sm')) groups.forEach(function(g){ set(g, false); }); });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape'){ groups.forEach(function(g){ set(g, false); });
    if (document.activeElement && document.activeElement.closest('.sm')) document.activeElement.blur(); } });
})();
</script>"""


def menu(active: str = "") -> Markup:
    """The grouped menu as HTML, with `active` (a key from MENU) highlighted."""
    parts = [_STYLE, '<nav class="sm" aria-label="Sirens pages">']
    for gi, (group, items) in enumerate(MENU):
        on = any(key == active for key, *_ in items)
        parts.append(
            f'<div class="sm-group"><button type="button" class="sm-head{" on" if on else ""}" '
            f'aria-haspopup="true" aria-expanded="false" aria-controls="sm-p{gi}">{escape(group)}'
            f'<span class="sm-caret" aria-hidden="true">&#9662;</span></button>'
            f'<div class="sm-panel" id="sm-p{gi}"><div class="sm-card">')
        for key, label, endpoint, desc in items:
            cur = ' class="sm-item on" aria-current="page"' if key == active else ' class="sm-item"'
            parts.append(f'<a{cur} href="{escape(url_for(endpoint))}">'
                         f'<strong>{escape(label)}</strong><span>{escape(desc)}</span></a>')
        parts.append("</div></div></div>")
    parts.append("</nav>")
    parts.append(_SCRIPT)
    return Markup("".join(parts))


def register(app) -> None:
    app.jinja_env.globals["sirens_menu"] = menu
