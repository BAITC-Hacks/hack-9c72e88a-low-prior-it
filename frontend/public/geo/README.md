# Explore country boundaries

`countries.geojson` is a compact, locally served Natural Earth **1:110m Admin 0 countries** layer. It contains 177 country/territory features, including Antarctica, and does not require a map service or API key at runtime.

## Source and license

- Dataset: [Natural Earth Admin 0 countries, 1:110m](https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/).
- License: [Natural Earth public domain terms](https://www.naturalearthdata.com/about/terms-of-use/). The source represents Natural Earth's cartographic boundaries and disputed areas; it is a navigation overview, not a survey or a statement about sovereignty.
- Upstream repository: [`nvkelso/natural-earth-vector`](https://github.com/nvkelso/natural-earth-vector).
- Pinned source commit: `9380cca83db5f9aef52d5e762765100745f84b27`.
- Exact source: [ne_110m_admin_0_countries.geojson](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/9380cca83db5f9aef52d5e762765100745f84b27/geojson/ne_110m_admin_0_countries.geojson).
- Source SHA-256: `6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`.
- Bundled SHA-256: `37e64baf21d67fc5e965cf06c074f6dd20bada0ab457fa4d355ce24d9ecb100e`.
- Bundled size: **200,965 bytes**.

## Reproduce

From the repository root, using Python 3.12 or newer:

```sh
python scripts/prepare_globe_map.py
```

The script uses only Python's standard library. It downloads the pinned source, verifies its SHA-256, and writes the same UTF-8 GeoJSON bytes. For an already downloaded source, use `--source path/to/ne_110m_admin_0_countries.geojson`; the same checksum requirement applies. `--output path/to/countries.geojson` selects another output file.

## Transform and frontend contract

The original Polygon/MultiPolygon geometry is retained, with coordinates rounded to three decimal places and all unused source properties removed. No further geometry simplification or territory exclusion is applied. This resolution is for a world/country overview; station coordinates come from the asset registry.

Each feature has exactly these properties:

| Property | Source / meaning |
| --- | --- |
| `code` | `ISO_A2_EH`, then `ISO_A2`, then stable `ADM0_A3` fallback; missing `-99` values are skipped and all codes are unique. |
| `name` | `NAME_EN`, falling back to `ADMIN`. |
| `lat`, `lng` | Natural Earth `LABEL_Y` and `LABEL_X`, rounded to three decimal places; the intended country camera target. |
| `span` | Camera framing estimate in degrees, clamped to 5–170. It uses the exterior polygon containing the source label, or the largest approximate polygon if no polygon contains it. Longitude is unwrapped relative to the label and its extent scaled by cosine(latitude), then compared with latitude extent. Antarctica is explicitly 170. |

The main-polygon framing avoids zooming France, Norway, and the United States out to include remote territories. Archipelagos likewise focus on the labelled or largest island; their remaining geometry stays visible when zooming out. Two source features without ISO alpha-2 identifiers retain stable three-letter codes: `CYN` (Northern Cyprus) and `SOL` (Somaliland). Country selection should treat codes as opaque strings, not require two letters.

Kazakhstan is `KZ`, with camera target `49.054, 68.686` and span `26.799`.
