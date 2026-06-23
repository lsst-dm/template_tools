# Altitude-vs-time panel for nexp_coverage.html

**Date:** 2026-06-23
**Status:** Approved (design)

## Goal

Add a second panel below the existing sky plot in
`web/nexp_coverage.html`. The panel is an altitude-vs-time plot for the sky
position of the tract the user clicks in the sky plot, computed for Rubin
Observatory. It defaults to tonight and has a date picker for other nights.

All work is confined to `web/nexp_coverage.html`. No Python or data-generation
changes are required — the tract polygons already carry `corners` (arrays of
`[ra, dec]`) and an `id`, which is all the panel needs.

## Constants

Rubin Observatory location:

- latitude  −30.2446°
- longitude −70.7494°
- height     2663 m

Chile timezone: `America/Santiago` (CLT/CLST, handled via the browser's
`Intl` time-zone support).

## Tract selection

- Register a `footprintClicked` handler on the Aladin tract overlay. Clicking a
  tract polygon pins it as the selected target and triggers a redraw of the
  altitude panel.
- Target RA/Dec = mean of the clicked tract's `corners`. This is a rough
  center; high precision is explicitly not required.
- The selected tract is visually distinguished in the sky plot (e.g. a thicker
  / brighter outline) so it is clear which tract is plotted.
- Selection persists across band / threshold / min-coverage redraws of the sky
  plot. Those redraws must not clear the selection or the altitude panel.
- Before any tract is clicked, the panel shows a placeholder message
  ("Click a tract to see its visibility").

## Layout

A new `.plot-container` block is added below the existing Aladin container:

- a `<canvas>` for the altitude plot,
- a date control (`<input type="date">`) defaulting to the current date at
  Rubin,
- a caption line showing the selected tract id, its RA/Dec, and the Moon's
  illuminated fraction for the night.

## Astronomy (Astronomy Engine, jsDelivr CDN)

Astronomy Engine (Don Cross, MIT) is loaded from jsDelivr via a `<script>` tag
next to the existing Aladin Lite tag. It provides horizontal-coordinate,
sun/moon position, and moon-illumination functions with no other dependencies.

Night definition and sampling:

- The date picker value `D` is interpreted as the Chile-local calendar date of
  the **evening**. The plotted night runs from sunset on `D` to sunrise on
  `D+1`. Default `D` = today at Rubin.
- Sample ~100–200 evenly spaced time steps across the night window. At each
  step compute, via Astronomy Engine (`Equator` / `Horizon`):
  - target altitude (from the tract RA/Dec),
  - Sun altitude (drives twilight shading),
  - Moon altitude.
- Compute the Moon's illuminated fraction once for the night
  (`Illumination`), shown in the caption.

## Canvas rendering

- **Bottom X-axis:** time in Chile local time (CLT/CLST).
- **Top X-axis:** the same time span labeled in UTC.
- **Left Y-axis:** altitude, 0–90°.
- **Right Y-axis:** airmass (sec z), ticked at altitudes matching round airmass
  values (e.g. 1.0, 1.2, 1.5, 2.0, 3.0).
- **Twilight shading:** background bands by Sun altitude — day, civil
  (0 to −6°), nautical (−6 to −12°), astronomical (−12 to −18°), night
  (< −18°) — darkening progressively so the observable window is obvious.
- **Curves:** target altitude (clear accent / band color) and Moon altitude
  (dashed grey). Horizon reference line at altitude 0°.
- **Caption:** tract id, RA/Dec, Moon illumination %.

## Data flow / wiring

- A `selectedTract` state variable and a `drawAltitudePlot()` function.
- `drawAltitudePlot()` is invoked on: tract click and date-picker change.
- It is independent of the band / threshold / min-coverage redraw path, so
  changing those controls does not disturb the altitude panel or the
  selection.
- Astronomy Engine `<script>` tag added beside the Aladin tag.

## Edge cases

- **Target never rises:** the altitude curve simply stays at/below 0°; the plot
  still renders. No special handling.
- **No true night:** does not occur at Rubin's latitude (astronomical night
  always exists), so no special handling.
- **Astronomy Engine fails to load:** the panel shows an error message; the
  rest of the dashboard (sky plot, controls) is unaffected.
