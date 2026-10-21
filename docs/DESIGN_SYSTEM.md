# Family HQ design system

The interface uses coordinated navigation, neutral surfaces and restrained semantic
colours. Financial values should be easy to compare; actions and status should be
recognisable without relying on colour alone. All assets and system fonts are local.

## Stylesheet ownership

The shared [base template](../templates/base.html) loads styles in this order:

1. Vendored Bootstrap and Bootstrap Icons.
2. [Tokens](../static/css/system/tokens.css): light/dark colours, typography, spacing
   dimensions, radii, elevation and chart palettes.
3. [Foundation](../static/css/theme.css): base typography, page headers, utilities,
   focus states, reduced-motion support and print layout.
4. [Components](../static/css/system/components.css): cards, metrics, buttons, forms,
   tables, statuses, alerts, dialogs, tabs, pagination and empty states.
5. [Workspace](../static/css/system/workspace.css): desktop sidebar, mobile drawer,
   top bar, navigation search and footer.
6. [Domain patterns](../static/css/system/domain.css): dashboard and finance-oriented
   presentation; [public styles](../static/css/system/public.css): authentication,
   introduction and help pages.
7. The page's `extra_css` block.

The files are separate stylesheet links, not CSS imports, so the browser can request
them in parallel. There is no new asset build pipeline or runtime dependency.

Use `var(--bg-surface)`, `var(--text-primary)`, `var(--border-color)`, `var(--brand)`
and the `--clr-*-bg`/`--clr-*` pairs rather than introducing hex colours in pages.
Buttons use `--action-text` for contrast in both themes. Existing Bootstrap semantic
card classes render as quieter tinted panels; card headers are neutral with an accent
edge. Badges keep explicit text labels and semantic tint pairs.

Page-only styling belongs in `extra_css`. Keep large feature stylesheets alongside
the existing transactions, plans, credit-card and vehicle styles; promote shared
patterns to the system instead of copying them into another page.
The obsolete, unreferenced `style.css` has been removed to avoid maintaining a
second set of conflicting component definitions.

## Reusable Jinja components

Import the [UI macros](../templates/shared/_ui.html):

```jinja
{% from 'shared/_ui.html' import page_header, metric, empty_state %}

{% call page_header('Accounts', 'Money you share, save and spend.', 'Day to day') %}
    <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addModal">
        <i class="bi bi-plus-lg" aria-hidden="true"></i> Add account
    </button>
{% endcall %}

{{ metric('Total balance', '£12,345.67', 'wallet2',
          tone='primary', caption='Paid transactions only') }}
```

`metric` supports `primary`, `success`, `info`, `warning` and `danger` tones, and an
optional `href` to make the entire surface a real link. Put metrics in Bootstrap
`col-6 col-xl-3` columns with `row g-3` for a two-column mobile layout.
`empty_state` accepts a title, explanation, icon and optional caller block for an
action. Macro values remain autoescaped.

## Navigation and interactions

- [Navigation](../templates/shared/_navigation.html) is the source of page-search
  entries. Keep section permissions and owner/site-admin checks here; search must
  never expose links hidden from that user.
- At desktop widths the sidebar is independently scrollable. Below 992px it uses
  Bootstrap's offcanvas focus management, backdrop, Escape handling and scroll lock.
- The search button or **Ctrl/Cmd+K** opens page search. Arrow keys browse results;
  Enter opens a page. It searches page names only, not household financial data,
  and does not add browser storage.
- [Workspace JavaScript](../static/js/workspace.js) adds keyboard operation to legacy
  collapse headers and autofocuses dialog fields. Keep native buttons and links
  wherever possible.
- Tables retain their real tabular structure. Wrap wide tables in `.table-responsive`;
  overflowing wrappers receive keyboard focus and a scroll hint. Existing mobile
  card layouts for transaction and credit-card tables remain in their domain CSS.
- Password fields opt into a labelled visibility toggle with `data-password-toggle`.
  Server-rendered invalid feedback remains outside the generated wrapper.
- [Theme bootstrap](../static/js/theme-init.js) runs before styles to avoid a theme
  flash. [ThemeManager](../static/js/main.js) synchronises both theme attributes,
  appearance radios and system preference changes. Signed-in appearance is rendered
  from `User.preferences` before paint; browser storage never overrides it.

## Personal appearance

Personal preferences offers Blue (the default), Graphite, Green, Pink, Light Blue
(`sky`) and Purple, each with Light, Dark and Follow device modes. The root
`data-palette` and resolved `data-theme` select tokens. Keep financial success and
danger colours semantic, independent of the chosen brand.

Palette and mode previews do not save until **Save appearance** is used. **Undo
preview** restores the last saved choice. The top-bar toggle saves immediately.
Both values are validated and written atomically by
[PreferenceService](../services/platform/preference_service.py) via the CSRF-protected
`POST /preferences/appearance` endpoint. Existing preference keys are preserved;
the JSON user-preferences column needs no schema migration. Save failures display an
error and restore the saved appearance. The form also works without JavaScript.

Signed-out pages default to Blue and retain the browser-local `jhq-theme` display
mode. Blocked storage is reported and page-local switching still works. Signed-in
preferences are not copied into browser storage, preventing shared-browser bleed.

## Charts

Category and vendor analytics share [one chart builder](../static/js/analytics-chart.js)
and a [template include](../templates/shared/_analytics_chart.html). Both retain
positive income and negative expense stacks. Payloads use Jinja's JSON escaping.

`financeChartPalette()` reads theme tokens. Datasets with `financeColour` (palette
index) and optional `financeAlpha` (hex alpha) are recoloured when the theme changes;
`financeColours` supports multi-colour doughnut datasets. Chart text, grids and
tooltips follow the same theme, including charts created after page load. Supply a
canvas description and retain a table or text equivalent for the underlying values.

## Verification

Run the focused shell, permission and local-asset regressions:

```powershell
venv\Scripts\python.exe -m pytest -q tests\test_workspace_ui.py tests\test_settings_navigation.py tests\test_browser_privacy.py
```

For visual changes also check 390px mobile and desktop widths, both themes, keyboard
search, drawer dismissal/focus return, an add/edit dialog and wide-table scrolling.
Core text/status token pairs for all twelve palette/mode combinations are
regression-tested against WCAG AA's 4.5:1 text
contrast threshold; this does not replace a full page-level accessibility audit.
Do not use production household records for screenshots or test mutations.
