# Altitude-vs-time Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an altitude-vs-time panel below the sky plot in `web/nexp_coverage.html` that plots the visibility of a clicked tract from Rubin Observatory, with twilight shading, an airmass axis, a Moon overlay, dual UTC/Chile time axes, and a date picker.

**Architecture:** All changes live in the single static file `web/nexp_coverage.html`. Astronomy Engine is loaded from the jsDelivr CDN (same pattern as Aladin Lite). Pure helper functions compute the night window and per-sample sun/moon/target altitudes; a `drawAltitudePlot()` function renders everything onto a `<canvas>` with custom axes and shading. Tract selection is driven by an Aladin `footprintClicked` handler that reuses the existing `tractFootprintData` polygon→tract map.

**Tech Stack:** Vanilla JS, HTML5 canvas, Astronomy Engine 2.1.19 (CDN), Aladin Lite v3 (already present). No build step. Served via `python -m http.server` from `web/`.

---

## Testing approach

This repo has no JS test harness (no `package.json`/node tooling) — it is static HTML previewed with `cd web && python -m http.server`. Verification is therefore:

- **Pure math** (airmass, night window, tract center): `console.assert` checks added during the relevant task and observed in the browser devtools console. These asserts stay in the file (cheap, silent on success).
- **Rendering / interaction**: manual browser verification against the documented preview workflow, with explicit expected observations per step.

The local server is started once and reused:

```bash
cd web && python -m http.server 8765
# open http://localhost:8765/nexp_coverage.html in a browser, devtools console open
```

There is no `nexp_dashboard_data.json` regeneration needed; use whatever is already in `web/`. If absent, the panel work can still be verified using the temporary hard-coded target in Task 3.

---

## File structure

- **Modify only:** `web/nexp_coverage.html`
  - `<head>`: one new `<script>` tag (Astronomy Engine) + new CSS rules for the panel.
  - `<body>`: one new `.plot-container` block (canvas + date input + caption + placeholder), placed after the existing Aladin `.plot-container` and before `<p class="generated-at">`.
  - `<script>`: new constants, helper functions, `drawAltitudePlot()`, a `footprintClicked` handler, selected-tract highlighting in `drawTracts()`, and date-picker wiring in `init()`.

No other files change.

---

## Task 1: Scaffold the panel (script tag, CSS, HTML, placeholder)

**Files:**
- Modify: `web/nexp_coverage.html` (head script tag ~line 7; CSS before `</style>` ~line 178; HTML after the Aladin `.plot-container` ~line 214)

- [ ] **Step 1: Add the Astronomy Engine script tag**

In `<head>`, immediately after the existing Aladin `<script>` line (line 7), add:

```html
<script type="text/javascript" src="https://cdn.jsdelivr.net/npm/astronomy-engine@2.1.19/astronomy.browser.min.js" charset="utf-8"></script>
```

- [ ] **Step 2: Add CSS for the panel**

Just before `</style>` (after the `.tooltip` rule, ~line 178), add:

```css
.alt-panel {
  margin-top: 16px;
}
.alt-header {
  display: flex;
  gap: 24px;
  justify-content: center;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.alt-header input[type="date"] {
  background: #021A18;
  color: #DCE0E3;
  border: 2px solid #6A6E6E;
  border-radius: 4px;
  padding: 5px 8px;
  font-size: 0.9em;
}
.alt-caption {
  text-align: center;
  font-size: 0.85em;
  color: #DCE0E3;
  margin-bottom: 8px;
  min-height: 1.2em;
}
.alt-caption span { font-weight: 600; color: #F5F5F5; }
#alt-canvas {
  width: 100%;
  height: 340px;
  display: block;
}
.alt-placeholder {
  text-align: center;
  color: #6A6E6E;
  padding: 60px 0;
  font-size: 1.1em;
}
```

- [ ] **Step 3: Add the panel HTML**

After the closing `</div>` of the Aladin `.plot-container` (the one containing `#aladin-lite-div`, `#legend`, `#colorbar`, ~line 214) and before `<p class="generated-at" ...>`, add:

```html
<div class="plot-container alt-panel">
  <div class="alt-header">
    <div class="control-group">
      <span class="control-label">Night of:</span>
      <input type="date" id="alt-date">
    </div>
  </div>
  <div class="alt-caption" id="alt-caption"></div>
  <div class="alt-placeholder" id="alt-placeholder">Click a tract above to see its visibility from Rubin.</div>
  <canvas id="alt-canvas"></canvas>
</div>
```

- [ ] **Step 4: Verify the page loads with the placeholder**

Start the server (see Testing approach) and open the page. In the devtools console run:

```js
console.log(typeof Astronomy, !!document.getElementById('alt-canvas'));
```

Expected: prints `object true` (Astronomy Engine loaded as a global object; canvas present). The placeholder text "Click a tract above..." is visible below the sky map. The existing sky map still renders normally.

- [ ] **Step 5: Commit**

```bash
git add web/nexp_coverage.html
git commit -m "$(cat <<'EOF'
Scaffold altitude panel in nexp dashboard

Add the Astronomy Engine CDN script, panel CSS, and the static
panel markup (date picker, caption, placeholder, canvas) below the
sky plot. No behavior yet.

Generated with AI

Co-Authored-By: SLAC AI
EOF
)"
```

---

## Task 2: Astronomy + geometry helper functions

**Files:**
- Modify: `web/nexp_coverage.html` (`<script>` block; add near the top after the existing `let minCoverageFrac = 0.25;` ~line 241)

- [ ] **Step 1: Add constants and helpers**

After `let minCoverageFrac = 0.25;` (~line 241), add:

```js
// --- Altitude panel: astronomy helpers ---
const RUBIN = new Astronomy.Observer(-30.2446, -70.7494, 2663);
const RUBIN_TZ = 'America/Santiago';
let selectedTract = null;

// Current calendar date at Rubin, as 'YYYY-MM-DD'.
function rubinToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: RUBIN_TZ }).format(new Date());
}

// Target RA/Dec for a tract. Uses the first corner ([ra, dec]); precision is
// not important here and this sidesteps RA-wrap issues when averaging corners.
function tractTarget(tract) {
  const c = tract.corners[0];
  return { ra: c[0], dec: c[1] };
}

// Night window for the evening of dateStr ('YYYY-MM-DD'): sunset on that date
// to the following sunrise. Noon UTC of dateStr is always morning at Rubin
// (UTC-3/-4), so the next set is that evening's sunset.
function nightWindow(dateStr) {
  const start = new Date(dateStr + 'T12:00:00Z');
  const sunset = Astronomy.SearchRiseSet(Astronomy.Body.Sun, RUBIN, -1, start, 1);
  const sunrise = Astronomy.SearchRiseSet(Astronomy.Body.Sun, RUBIN, +1, sunset.date, 1);
  return { start: sunset.date, end: sunrise.date };
}

// Altitude (deg) of a fixed equatorial target. RA in deg -> sidereal hours.
function targetAltitude(date, target) {
  return Astronomy.Horizon(date, RUBIN, target.ra / 15, target.dec, 'normal').altitude;
}

// Altitude (deg) of a solar-system body (Sun, Moon).
function bodyAltitude(date, body) {
  const eq = Astronomy.Equator(body, date, RUBIN, true, true);
  return Astronomy.Horizon(date, RUBIN, eq.ra, eq.dec, 'normal').altitude;
}

// Sample the night: target/sun/moon altitude at nSteps+1 evenly spaced instants.
function sampleNight(win, target, nSteps = 160) {
  const t0 = win.start.getTime();
  const t1 = win.end.getTime();
  const out = [];
  for (let i = 0; i <= nSteps; i++) {
    const d = new Date(t0 + (t1 - t0) * i / nSteps);
    out.push({
      d,
      tgt: targetAltitude(d, target),
      sunAlt: bodyAltitude(d, Astronomy.Body.Sun),
      moonAlt: bodyAltitude(d, Astronomy.Body.Moon),
    });
  }
  return out;
}

// Airmass (sec z) from altitude in degrees; Infinity at/below horizon.
function airmassFromAlt(altDeg) {
  if (altDeg <= 0) return Infinity;
  return 1 / Math.sin(altDeg * Math.PI / 180);
}

// Altitude (deg) that yields a given airmass; inverse of airmassFromAlt.
function altFromAirmass(X) {
  return Math.asin(1 / X) * 180 / Math.PI;
}

// Format an instant in a given IANA time zone as HH:MM (24h).
function fmtTime(date, tz) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

// Background color for the twilight band at a given Sun altitude (deg).
function twilightColor(sunAlt) {
  if (sunAlt > 0) return '#0a3a38';    // day
  if (sunAlt > -6) return '#08302e';   // civil
  if (sunAlt > -12) return '#062624';  // nautical
  if (sunAlt > -18) return '#041d1b';  // astronomical
  return '#021412';                    // night
}
```

- [ ] **Step 2: Add temporary console.assert sanity checks**

Temporarily append to the same block (these will be removed in Step 4):

```js
// TEMP sanity checks — remove after verifying.
console.assert(Math.abs(airmassFromAlt(90) - 1) < 1e-6, 'airmass at zenith should be 1');
console.assert(Math.abs(airmassFromAlt(30) - 2) < 1e-6, 'airmass at alt=30 should be 2');
console.assert(Math.abs(altFromAirmass(2) - 30) < 1e-6, 'altFromAirmass(2) should be 30');
console.assert(rubinToday().match(/^\d{4}-\d{2}-\d{2}$/), 'rubinToday should be YYYY-MM-DD');
{
  const w = nightWindow(rubinToday());
  console.assert(w.end > w.start, 'sunrise should be after sunset');
  const hrs = (w.end - w.start) / 3.6e6;
  console.assert(hrs > 7 && hrs < 15, 'night length should be 7-15 h, got ' + hrs);
  console.log('nightWindow OK:', w.start.toISOString(), '->', w.end.toISOString(), hrs.toFixed(1), 'h');
}
```

- [ ] **Step 3: Verify the asserts pass**

Reload the page with the devtools console open. Expected: no `Assertion failed` messages, and one log line like `nightWindow OK: ...Z -> ...Z 9.x h`. The night length sanity-checks the sunset/sunrise search.

- [ ] **Step 4: Remove the temporary asserts**

Delete the `// TEMP sanity checks` block added in Step 2 (keep all the helper functions from Step 1). Reload and confirm the console is clean.

- [ ] **Step 5: Commit**

```bash
git add web/nexp_coverage.html
git commit -m "$(cat <<'EOF'
Add astronomy helpers for altitude panel

Add Rubin observer constant and pure helpers for the night window,
per-sample sun/moon/target altitudes, airmass conversion, time-zone
formatting, and twilight band colors.

Generated with AI

Co-Authored-By: SLAC AI
EOF
)"
```

---

## Task 3: Canvas rendering (drawAltitudePlot)

**Files:**
- Modify: `web/nexp_coverage.html` (`<script>` block; add after the helpers from Task 2, and a temporary call inside the `.then(...)` data handler ~line 397)

- [ ] **Step 1: Add the render function**

After the helper functions from Task 2, add:

```js
function showAltPlaceholder(msg) {
  const ph = document.getElementById('alt-placeholder');
  const canvas = document.getElementById('alt-canvas');
  ph.textContent = msg;
  ph.style.display = 'block';
  canvas.style.display = 'none';
  document.getElementById('alt-caption').innerHTML = '';
}

function drawAltitudePlot() {
  const canvas = document.getElementById('alt-canvas');
  const placeholder = document.getElementById('alt-placeholder');
  const caption = document.getElementById('alt-caption');

  if (!selectedTract) {
    showAltPlaceholder('Click a tract above to see its visibility from Rubin.');
    return;
  }
  if (typeof Astronomy === 'undefined') {
    showAltPlaceholder('Astronomy Engine failed to load; altitude plot unavailable.');
    return;
  }

  placeholder.style.display = 'none';
  canvas.style.display = 'block';

  const dateStr = document.getElementById('alt-date').value || rubinToday();
  const target = tractTarget(selectedTract);
  const win = nightWindow(dateStr);
  const samples = sampleNight(win, target);
  const midDate = new Date((win.start.getTime() + win.end.getTime()) / 2);
  const moonIllum = Astronomy.Illumination(Astronomy.Body.Moon, midDate).phase_fraction;

  // High-DPI canvas sizing.
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth;
  const cssH = canvas.clientHeight;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const m = { top: 32, right: 56, bottom: 32, left: 44 };
  const W = cssW - m.left - m.right;
  const H = cssH - m.top - m.bottom;
  const t0 = win.start.getTime();
  const t1 = win.end.getTime();
  const xOf = t => m.left + W * (t - t0) / (t1 - t0);
  const yOf = alt => m.top + H * (1 - alt / 90);  // 0..90 deg

  // Twilight bands: one vertical rect per sample interval, colored by sun alt.
  for (let i = 0; i < samples.length - 1; i++) {
    const x0 = xOf(samples[i].d.getTime());
    const x1 = xOf(samples[i + 1].d.getTime());
    ctx.fillStyle = twilightColor(samples[i].sunAlt);
    ctx.fillRect(x0, m.top, x1 - x0 + 1, H);
  }

  // Plot frame.
  ctx.strokeStyle = '#6A6E6E';
  ctx.lineWidth = 1;
  ctx.strokeRect(m.left, m.top, W, H);

  // Left axis: altitude grid + labels (0..90 every 30).
  ctx.fillStyle = '#6A6E6E';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let alt = 0; alt <= 90; alt += 30) {
    const y = yOf(alt);
    ctx.strokeStyle = '#ffffff22';
    ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + W, y); ctx.stroke();
    ctx.fillStyle = '#6A6E6E';
    ctx.fillText(alt + '°', m.left - 6, y);
  }

  // Right axis: airmass ticks.
  ctx.textAlign = 'left';
  for (const X of [1.0, 1.2, 1.5, 2.0, 3.0]) {
    const y = yOf(altFromAirmass(X));
    ctx.fillStyle = '#6A6E6E';
    ctx.fillText(X.toFixed(1), m.left + W + 6, y);
  }

  // Horizon line at 0 deg.
  ctx.strokeStyle = '#888';
  ctx.beginPath(); ctx.moveTo(m.left, yOf(0)); ctx.lineTo(m.left + W, yOf(0)); ctx.stroke();

  // X ticks at whole UTC hours within the window (also whole Chile hours).
  const tickStart = new Date(Math.ceil(t0 / 3.6e6) * 3.6e6);
  ctx.strokeStyle = '#ffffff22';
  for (let t = tickStart.getTime(); t <= t1; t += 3.6e6) {
    const x = xOf(t);
    ctx.beginPath(); ctx.moveTo(x, m.top); ctx.lineTo(x, m.top + H); ctx.stroke();
    ctx.fillStyle = '#6A6E6E';
    ctx.textBaseline = 'top';
    ctx.textAlign = 'center';
    ctx.fillText(fmtTime(new Date(t), RUBIN_TZ), x, m.top + H + 6);    // bottom: Chile
    ctx.textBaseline = 'bottom';
    ctx.fillText(fmtTime(new Date(t), 'UTC'), x, m.top - 6);          // top: UTC
  }

  // Axis titles.
  ctx.fillStyle = '#6A6E6E';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText('Chile local (CLT/CLST)', m.left + W / 2, cssH - 14);
  ctx.textBaseline = 'bottom';
  ctx.fillText('UTC', m.left + W / 2, 14);

  // Curve helper (clips below-horizon to the frame).
  const drawCurve = (key, color, dash) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    let started = false;
    for (const s of samples) {
      const alt = Math.max(0, Math.min(90, s[key]));
      const x = xOf(s.d.getTime());
      const y = yOf(alt);
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.setLineDash([]);
  };
  drawCurve('moonAlt', '#cfd3d6', [5, 4]);                  // Moon: dashed grey
  drawCurve('tgt', BAND_COLORS[activeBand] || '#00BABC');   // target: band color

  // Caption.
  caption.innerHTML =
    `Tract <span>${selectedTract.id}</span> &mdash; ` +
    `RA <span>${target.ra.toFixed(3)}°</span>, Dec <span>${target.dec.toFixed(3)}°</span> &middot; ` +
    `Moon <span>${Math.round(moonIllum * 100)}%</span> illuminated`;
}
```

- [ ] **Step 2: Add a temporary call to render a known target**

Inside the data `.then(([nexpData, deployedData]) => { ... })` handler (~line 393), after `init();`, temporarily add:

```js
    // TEMP: verify rendering with a fixed southern target. Remove in Task 4.
    selectedTract = { id: 'TEST', corners: [[60.0, -30.0]] };
    document.getElementById('alt-date').value = rubinToday();
    drawAltitudePlot();
```

- [ ] **Step 3: Verify rendering in the browser**

Reload the page. Expected observations below the sky map:
- The placeholder is gone; a plotted panel appears.
- Background shows progressively darker vertical bands from dusk → night → dawn (lightest at the edges, darkest in the middle).
- Left axis labeled `0° 30° 60° 90°`; right axis labeled `1.0 1.2 1.5 2.0 3.0` (airmass).
- Bottom tick labels are Chile local times; top tick labels are the same instants in UTC (offset by 3 or 4 whole hours).
- A band-colored target curve and a dashed grey Moon curve are drawn; a target near Dec −30° (≈ Rubin's latitude) should pass near 90° around local midnight.
- Caption reads `Tract TEST — RA 60.000°, Dec -30.000° · Moon NN% illuminated`.

- [ ] **Step 4: Commit**

```bash
git add web/nexp_coverage.html
git commit -m "$(cat <<'EOF'
Render altitude panel on canvas

Draw twilight shading, altitude and airmass axes, dual UTC/Chile
time axes, horizon line, and the target and Moon altitude curves,
with a caption showing tract, RA/Dec, and Moon illumination.

Generated with AI

Co-Authored-By: SLAC AI
EOF
)"
```

---

## Task 4: Wire tract selection, highlight, and date picker

**Files:**
- Modify: `web/nexp_coverage.html` (`drawTracts()` ~lines 308-341; the `A.init.then(...)` block for the click handler ~lines 376-388; the data `.then(...)` handler ~line 393; `init()` ~lines 404-449)

- [ ] **Step 1: Highlight the selected tract in drawTracts()**

In `drawTracts()`, replace the polygon construction (the `const poly = A.polygon(...)` call, ~lines 327-331) with:

```js
    const isSelected = selectedTract && tract.id === selectedTract.id;
    const poly = A.polygon(tract.corners, {
      color: isSelected ? '#ffffff' : bin.color,
      lineWidth: isSelected ? 4 : 2,
      hoverColor: '#ffffff',
    });
```

- [ ] **Step 2: Add the footprintClicked handler**

In the `A.init.then(() => { ... })` block, after the existing `aladin.on('footprintHovered', ...)` handler (~line 388), add:

```js
  aladin.on('footprintClicked', (footprint) => {
    if (footprint && tractFootprintData.has(footprint)) {
      selectedTract = tractFootprintData.get(footprint);
      drawTracts();        // refresh highlight
      drawAltitudePlot();  // refresh visibility panel
    }
  });
```

- [ ] **Step 3: Remove the temporary render call from Task 3**

In the data `.then(...)` handler, delete the `// TEMP: verify rendering...` block (the `selectedTract = { id: 'TEST', ... }; ... drawAltitudePlot();` lines added in Task 3 Step 2).

- [ ] **Step 4: Initialize the date picker and its change handler in init()**

In `init()`, just before the final `redraw();` (~line 448), add:

```js
  const altDate = document.getElementById('alt-date');
  altDate.value = rubinToday();
  altDate.addEventListener('change', drawAltitudePlot);
  drawAltitudePlot();  // show placeholder until a tract is clicked
```

- [ ] **Step 5: Verify end-to-end interaction**

Reload the page. Expected:
- Initially the panel shows the placeholder "Click a tract above...".
- The date input is pre-filled with today's Chile date.
- Click a tract polygon on the sky map: that tract's outline thickens/turns white, and the panel renders its altitude curve with the correct tract id and RA/Dec in the caption.
- Click a different tract: the highlight moves and the panel updates.
- Change the date in the picker: the curves and twilight shading update for that night; the selected tract stays selected.
- Change band/threshold/min-coverage controls: the sky map updates and the selected tract stays highlighted and plotted (selection is not cleared). Note the target curve color follows the active band.

- [ ] **Step 6: Commit**

```bash
git add web/nexp_coverage.html
git commit -m "$(cat <<'EOF'
Wire tract selection and date picker to altitude panel

Click a tract to pin it as the altitude-plot target and highlight it
on the sky map; default the date picker to tonight at Rubin and
redraw on date change. Selection persists across map redraws.

Generated with AI

Co-Authored-By: SLAC AI
EOF
)"
```

---

## Task 5: Graceful degradation + resize handling

**Files:**
- Modify: `web/nexp_coverage.html` (`<script>` block; the `A.init.then(...)` block ~line 364)

- [ ] **Step 1: Add a resize redraw**

In the `A.init.then(() => { ... })` block, after the `footprintClicked` handler from Task 4, add:

```js
  window.addEventListener('resize', () => { if (selectedTract) drawAltitudePlot(); });
```

- [ ] **Step 2: Verify the missing-library fallback**

`drawAltitudePlot()` already guards on `typeof Astronomy === 'undefined'` (Task 3). To verify the fallback without removing the CDN tag permanently, temporarily edit the Astronomy Engine `<script>` `src` to a bad URL (e.g. append `.broken`), reload, click a tract.

Expected: the panel shows "Astronomy Engine failed to load; altitude plot unavailable." and the rest of the dashboard (sky map, band/threshold controls) still works. Then restore the correct `src`, reload, and confirm the panel works again.

- [ ] **Step 3: Verify resize**

With a tract selected, resize the browser window. Expected: the panel re-renders to the new width without distortion (axes and curves stay crisp, not stretched).

- [ ] **Step 4: Commit**

```bash
git add web/nexp_coverage.html
git commit -m "$(cat <<'EOF'
Handle resize and missing Astronomy Engine for altitude panel

Redraw the altitude panel on window resize and show a clear message
(leaving the rest of the dashboard functional) if Astronomy Engine
fails to load.

Generated with AI

Co-Authored-By: SLAC AI
EOF
)"
```

---

## Final verification checklist

After Task 5, do one clean pass (server running, hard reload):

- [ ] Page loads; placeholder shown; date = today (Chile).
- [ ] Clicking tracts pins/highlights them and plots the correct RA/Dec.
- [ ] Twilight shading darkens dusk→midnight→dawn; horizon line at 0°.
- [ ] Left axis altitude (0–90°), right axis airmass (1.0–3.0), bottom axis Chile time, top axis UTC.
- [ ] Target curve (band color) and Moon curve (dashed grey) present; caption shows Moon illumination %.
- [ ] Date change updates the night; band/threshold/min-coverage changes preserve selection.
- [ ] Devtools console is free of errors/assertion failures.

## Deployment note (not part of this plan)

`deploy/sync_nexp.sh` / `dev_sync_nexp.sh` already ship `web/nexp_coverage.html`. Because Astronomy Engine loads from a CDN (like Aladin), no new asset needs to be added to the sync scripts. Deploying is out of scope here and should be done by the user when ready.
