# Wind operations theme

The main screen is a dense operational workspace. Forecast data has priority over branding and navigation. Design references: [Tomorrow.io](https://www.tomorrow.io/) for operational weather intelligence, [Linear](https://linear.app/) for restrained dark UI, and [Windy](https://www.windy.com/) for wind and weather interpretation. The composition and components are original to this project.

The application has two workspaces: **Explore** for geographic asset selection and **Forecast** for operational analysis. First visits open Explore; subsequent visits restore the last workspace. The information hierarchy below applies to Forecast.

## Tokens

The shared CSS variables in `frontend/src/styles.css` and `frontend/src/themes.css` are the design system for both workspaces. **General** preserves the original palette below. **Light** uses pale surfaces and a darker teal accent for legibility; **Black** uses neutral charcoal surfaces. Profile preferences set `data-theme` on the document and persist locally, with a prepaint initializer. Chart series, globe materials, tables, warnings, and forms all follow the chosen appearance.

| Token | Value | Purpose |
| --- | --- | --- |
| `--page` | `#07111F` | Application background |
| `--card` | `#0D1929` | Dashboard panels |
| `--elevated` | `#111F31` | Controls and elevated surfaces |
| `--border` | `#1C2A3A` | Dividers and card outlines |
| `--text` | `#F4F7FA` | Primary text |
| `--text-muted` | `#8996A8` | Secondary text |
| `--accent` | `#2DE2C5` | Actions, selected state, primary forecast series |
| `--warning` | `#F4B860` | Warnings only |
| `--error` | `#EF6A6A` | Errors and failed operations |

Use Inter Variable, bundled through `@fontsource-variable/inter`. It is served by the application, without a font CDN dependency. Headings are compact (12–16px), body/control text 11–13px, and KPI numbers 23–30px. Numeric readings use tabular figures. Panels have 10–12px corners, thin borders, 14–18px padding, and 12–14px gaps. Avoid gradients, glass effects, glow, large shadows, and marketing-style hero blocks.

## Information hierarchy

1. Compact connection header and forecast configuration.
2. Forecast KPIs, explicitly labelled normalized output and input weather.
3. The large hourly power chart, with the weather panel immediately alongside it.
4. Station locations and the agent's decision log.
5. Persistent, filterable hourly table with CSV export.
6. Historical replay metrics and expandable model/weather provenance.

The chart uses turquoise and blue for turbine series. Amber is never used as an ordinary chart series. There is no uncertainty band until the backend supplies calibrated intervals. Chart coordinates resize to the card so axis labels remain readable on mobile. Pointer inspection and an accessible hour slider update the adjacent weather panel; hourly table timestamps can select the same hour.

The forecast's small map remains a labelled coordinate schematic. Explore uses the geographic globe with locally bundled Natural Earth boundaries and configured asset coordinates. World/country/site transitions are short, globe rotation stops on interaction, and manual camera input cancels an active flight. Site groups come from explicit registry metadata. The station directory provides equivalent country/site/turbine selection without WebGL.

## State and accessibility

- Preserve demo labels and unavailable values. No invented metrics, turbine capacities, locations, weather, or confidence intervals.
- The displayed result retains its own issue time and horizon. Changing form controls shows a pending-input notice until a new run is requested.
- Job status, retry/failure events, offline errors, and refresh feedback are visible.
- Keyboard focus, an hour range control, chart series toggles, labelled controls, a skip link, and reduced-motion preferences are supported.
- On narrow screens, cards stack and the navigation rail becomes a bottom bar. Tables scroll horizontally instead of compressing numerical columns.

## Main files

- `App.tsx`: overall composition, controls, and forecast KPIs.
- `useDashboard.ts`: API state, polling, history, and actions.
- `ForecastChart.tsx`: responsive series and hour inspection.
- `components/WeatherPanel.tsx`: weather at the selected forecast hour.
- `components/StationMap.tsx`: station coordinates and asset selection.
- `components/AgentPanel.tsx`: workflow stages and events.
- `components/ForecastTable.tsx`: filtered/paginated hourly values.
- `components/ReplayPanel.tsx`: actuals selection and per-horizon metrics.
- `components/Icon.tsx`: consistent local SVG icons.
