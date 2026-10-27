/* Sirens MGRS grid for the offline map (local file, no network).
   - utmToLonLat / lonLatToUtm: WGS84 transverse Mercator (Krueger series).
   - gridFeatures(bounds, spacing): grid lines for UTM zones 36 and 37 inside the
     view, clipped at each zone's edge, so the grid visibly jumps at 36 E (correct:
     standard zones meet there), plus 100 km square labels.
   - format(ref): "36SYC311527" -> "36S YC 311 527".
   MGRS references themselves come from the vendored mgrs library (static/vendor/mgrs). */
(function (global) {
  'use strict';
  var a = 6378137, f = 1 / 298.257223563, k0 = 0.9996, n = f / (2 - f);
  var A = a / (1 + n) * (1 + n * n / 4 + Math.pow(n, 4) / 64);
  var alpha = [n / 2 - 2 * n * n / 3 + 5 * Math.pow(n, 3) / 16, 13 * n * n / 48 - 3 * Math.pow(n, 3) / 5, 61 * Math.pow(n, 3) / 240];
  var beta = [n / 2 - 2 * n * n / 3 + 37 * Math.pow(n, 3) / 96, n * n / 48 + Math.pow(n, 3) / 15, 17 * Math.pow(n, 3) / 480];
  var delta = [2 * n - 2 * n * n / 3 - 2 * Math.pow(n, 3), 7 * n * n / 3 - 8 * Math.pow(n, 3) / 5, 56 * Math.pow(n, 3) / 15];
  var e = Math.sqrt(f * (2 - f)), D = Math.PI / 180;

  function zoneOf(lon) { return Math.floor((lon + 180) / 6) % 60 + 1; }
  function lon0(zone) { return (zone - 1) * 6 - 180 + 3; }

  function lonLatToUtm(lon, lat, zone) {
    zone = zone || zoneOf(lon);
    var phi = lat * D, lam = (lon - lon0(zone)) * D;
    var t = Math.sinh(Math.atanh(Math.sin(phi)) - e * Math.atanh(e * Math.sin(phi)));
    var xi = Math.atan2(t, Math.cos(lam)), eta = Math.atanh(Math.sin(lam) / Math.sqrt(1 + t * t));
    var x = eta, y = xi;
    for (var j = 1; j <= 3; j++) {
      x += alpha[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
      y += alpha[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
    }
    return [500000 + k0 * A * x, k0 * A * y];          // northern hemisphere
  }

  function utmToLonLat(zone, E, N) {
    var xi = N / (k0 * A), eta = (E - 500000) / (k0 * A), xp = xi, ep = eta;
    for (var j = 1; j <= 3; j++) {
      xp -= beta[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
      ep -= beta[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
    }
    var chi = Math.asin(Math.sin(xp) / Math.cosh(ep)), phi = chi;
    for (j = 1; j <= 3; j++) phi += delta[j - 1] * Math.sin(2 * j * chi);
    return [lon0(zone) + Math.atan2(Math.sinh(ep), Math.cos(xp)) / D, phi / D];
  }

  // Keep only the part of a polyline inside [lo, hi] longitude, cutting exactly at the edge.
  function clipLon(pts, lo, hi) {
    var out = [], cur = [];
    function edge(p, q, x) { var t = (x - p[0]) / (q[0] - p[0]); return [x, p[1] + t * (q[1] - p[1])]; }
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i], inside = p[0] >= lo && p[0] <= hi;
      if (i > 0) {
        var q = pts[i - 1], qin = q[0] >= lo && q[0] <= hi;
        if (inside && !qin) cur.push(edge(q, p, q[0] < lo ? lo : hi));
        if (!inside && qin) { cur.push(edge(q, p, p[0] < lo ? lo : hi)); out.push(cur); cur = []; }
      }
      if (inside) cur.push(p);
    }
    if (cur.length > 1) out.push(cur);
    return out.filter(function (l) { return l.length > 1; });
  }

  function lineLabel(value, spacing) {
    var inSquare = ((value % 100000) + 100000) % 100000;
    if (spacing >= 100000) return '';
    if (spacing >= 10000) return String(Math.floor(inSquare / 10000));           // 10 km digit
    return String(Math.floor(inSquare / 1000)).padStart(2, '0');                 // 1 km: two digits
  }

  // bounds: [west, south, east, north]; spacing in metres (100000, 10000 or 1000).
  function gridFeatures(bounds, spacing, mgrsLib) {
    var feats = [], W = bounds[0], S = bounds[1], E_ = bounds[2], N_ = bounds[3];
    [36, 37].forEach(function (zone) {
      var lo = (zone - 1) * 6 - 180, hi = lo + 6, w = Math.max(W, lo), ea = Math.min(E_, hi);
      if (w >= ea) return;
      var cs = [[w, S], [ea, S], [w, N_], [ea, N_], [(w + ea) / 2, S], [(w + ea) / 2, N_]].map(function (p) { return lonLatToUtm(p[0], p[1], zone); });
      var Emin = Math.min.apply(null, cs.map(function (c) { return c[0]; })), Emax = Math.max.apply(null, cs.map(function (c) { return c[0]; }));
      var Nmin = Math.min.apply(null, cs.map(function (c) { return c[1]; })), Nmax = Math.max.apply(null, cs.map(function (c) { return c[1]; }));
      var steps = 32, x, y, k, pts;
      for (x = Math.ceil(Emin / spacing) * spacing; x <= Emax; x += spacing) {
        pts = []; for (k = 0; k <= steps; k++) pts.push(utmToLonLat(zone, x, Nmin + (Nmax - Nmin) * k / steps));
        clipLon(pts, lo, hi).forEach(function (l) {
          feats.push({type: 'Feature', properties: {zone: zone, major: x % 100000 === 0, label: lineLabel(x, spacing)}, geometry: {type: 'LineString', coordinates: l}});
        });
      }
      for (y = Math.ceil(Nmin / spacing) * spacing; y <= Nmax; y += spacing) {
        pts = []; for (k = 0; k <= steps; k++) pts.push(utmToLonLat(zone, Emin + (Emax - Emin) * k / steps, y));
        clipLon(pts, lo, hi).forEach(function (l) {
          feats.push({type: 'Feature', properties: {zone: zone, major: y % 100000 === 0, label: lineLabel(y, spacing)}, geometry: {type: 'LineString', coordinates: l}});
        });
      }
      // 100 km square labels ("36S YC") at the centre of the visible part of each square.
      if (mgrsLib) for (x = Math.floor(Emin / 1e5) * 1e5; x < Emax; x += 1e5) for (y = Math.floor(Nmin / 1e5) * 1e5; y < Nmax; y += 1e5) {
        var c = utmToLonLat(zone, (Math.max(x, Emin) + Math.min(x + 1e5, Emax)) / 2, (Math.max(y, Nmin) + Math.min(y + 1e5, Nmax)) / 2);
        if (c[0] < lo || c[0] > hi || c[0] < W || c[0] > E_ || c[1] < S || c[1] > N_) continue;
        var ref = mgrsLib.forward(c, 0);                                      // "36SYC"
        feats.push({type: 'Feature', properties: {square: ref.slice(0, 3) + ' ' + ref.slice(3, 5)}, geometry: {type: 'Point', coordinates: c}});
      }
    });
    return {type: 'FeatureCollection', features: feats};
  }

  function format(ref) {
    var m = /^(\d{1,2}[A-Z])([A-Z]{2})(\d*)$/.exec(ref || '');
    if (!m) return ref || '';
    var d = m[3], h = d.length / 2;
    return m[1] + ' ' + m[2] + (d ? ' ' + d.slice(0, h) + ' ' + d.slice(h) : '');
  }

  var api = {utmToLonLat: utmToLonLat, lonLatToUtm: lonLatToUtm, zoneOf: zoneOf, gridFeatures: gridFeatures, format: format};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else global.SirensMGRS = api;
})(this);
