# Energy explorer and appearance

Explore provides a geographic entry into the existing forecasting workspace. It does not generate predictions or download weather. The working path is **World → Kazakhstan → Kazakhstan wind site → select turbines → Open forecast**. Select an issue time and run the forecast in the existing dashboard; existing demo and provenance labels remain authoritative.

## Navigation and animation

- First visits open Explore. Rail links and `#explore`, `#forecast`, `#stations`, `#activity`, `#hourly`, `#replay`, and `#data` support direct navigation and browser history. The last workspace is saved locally.
- Country polygons and the searchable country directory select the same state. The camera frames the country's main landmass; outlying territories remain in the geometry.
- Globe rotation is slow and can be paused/resumed. Drag/zoom input stops rotation and cancels a camera flight. Selected countries/sites keep rotation paused; reset returns to World and manual rotation can be resumed.
- Country/site camera flights last about 1.25 seconds; reduced-motion preferences remove these transitions and disable automatic rotation.
- The Explore view and renderer are separate lazy-loaded chunks. The retained renderer pauses while Forecast is visible or the browser tab is hidden. Device pixel ratio is capped at 1.75.
- WebGL2 or chunk/render failures show a usable directory fallback. A missing boundary file still permits selection of countries known to the asset registry. Missing asset data has an explicit retry state.

## Asset and forecast contract

`GET /api/v1/assets` returns `EnergyAsset` records. Current records are derived from the configured wind turbines; optional `country_code`, `country_name`, `site_id`, and `site_name` are stored in turbine configuration. No grouping or country assignment is inferred from proximity. An asset without coordinates remains in the directory and is not plotted.

`energy_type` supports `wind`, `hydro`, `solar`, and `other`. The current endpoint emits only the two configured wind assets. Other categories have honest empty states. Future source integrations must provide real registries, their own input data/models, and an appropriate forecast API. Merely changing an energy-type label does not enable forecasting.

The browser permits forecast handoff only for wind assets with `forecast_supported=true` and `forecast_turbine_id`. It passes those IDs into the existing `ForecastRequest.turbine_ids`. Historical results remain labelled with their original request until a new run is made.

At country scale the two nearby turbines are one explicit site marker. Selecting the site moves the camera closer and exposes individual turbine checkboxes in the directory. The globe is a world/country overview, not a street-level or engineering basemap.

## Appearance

Profile → Appearance offers:

- **General:** original deep navy and cyan.
- **Light:** light surfaces, dark text, and darker teal/chart colors.
- **Black:** neutral black/charcoal surfaces with cyan accents.

`theme.ts` synchronizes `data-theme`, the browser theme color, and the `low-prior-theme` local preference. Invalid or unavailable storage falls back to General. Preferences also synchronize across browser tabs. Profile is a local settings menu; no account or authentication is implied.

## Files and data provenance

| File | Responsibility |
| --- | --- |
| `frontend/src/explore/ExploreView.tsx` | Country/site selection, filters, API registry, directory and fallbacks |
| `frontend/src/explore/GlobeCanvas.tsx` | Three.js/globe.gl rendering, themed materials, camera and lifecycle |
| `frontend/src/explore/catalog.ts` | Explicit grouping, geographic center and allowed forecast IDs |
| `frontend/src/components/ProfileMenu.tsx` | Accessible appearance preferences |
| `frontend/src/theme.ts`, `themes.css` | Theme state and semantic palettes |
| `frontend/public/geo/` | Bundled country GeoJSON and provenance |
| `scripts/prepare_globe_map.py` | Reproducible country layer generation from a pinned, checksum-verified source |

The renderer uses `react-globe.gl` and Three.js. Country geometry uses Natural Earth's public-domain 1:110m country dataset, with 177 features and a roughly 196 KiB bundled file. Full source revision, checksums, transformations, license, and reproduction commands are in [the map README](../frontend/public/geo/README.md). Runtime map navigation needs no external tiles or API key.

## Verification

`npm run check` covers Python APIs, asset capability validation, site grouping, dateline behavior, missing coordinates, wind-only handoff, country framing/data compatibility, TypeScript, and the production build. Check the interactive UI on a WebGL2-capable browser in all three themes, at desktop/mobile widths, with keyboard navigation, reduced motion, and unavailable backend/graphics states. Build and unit checks alone do not establish visual rendering quality.
