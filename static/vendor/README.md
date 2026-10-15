# Bundled browser assets

These upstream MIT-licensed assets are served locally. Preserve the accompanying
licenses when updating or distributing them.

| Asset | Version | Source |
| --- | --- | --- |
| Bootstrap CSS and JS bundle | 5.3.0 | https://www.npmjs.com/package/bootstrap/v/5.3.0 |
| Bootstrap Icons CSS and WOFF/WOFF2 fonts | 1.11.3 | https://www.npmjs.com/package/bootstrap-icons/v/1.11.3 |
| Chart.js UMD build | 4.4.0 | https://www.npmjs.com/package/chart.js/v/4.4.0 |

Files were downloaded from the corresponding pinned npm package paths on
https://cdn.jsdelivr.net. That service is used at development time only, not by
visitors' browsers. Keep the icons CSS and its relative `fonts/` directory together.
Flask-Admin serves its own bundled assets from the installed Python package.

The main app uses system fonts; no Google Fonts stylesheet is loaded.
When upgrading assets, exercise dropdowns, modals, icons and each chart page,
and check browser network requests for accidental external dependencies.
