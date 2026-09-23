# JonesHQ Finance — Agent Instructions

Flask + SQLAlchemy family finance tracker. See [docs/](../docs/) (DATABASE_SCHEMA.md,
DIRECTORY_STRUCTURE.md) and [services/README.md](../services/README.md) for the service map.

## Architecture

- **Routes are thin.** `blueprints/*/routes.py` only parses the request, calls a service,
  flashes/redirects. All business logic lives in `services/<domain>/*_service.py` as static
  methods on a `<Thing>Service` class.
- Service methods take a plain `data` dict (`Service.create_x(data)`, reading `data.get(...)`)
  so both `request.form` and tests can call them directly.
- Services raise `ValueError`/`TypeError` with a user-facing message; routes catch and
  `flash(str(error) or '<fallback>', 'danger')`.
- Templates mirror blueprints 1:1 (`templates/<blueprint_name>/`).
- Page-specific CSS/JS goes in `{% block extra_css %}` / `{% block extra_js %}` (defined in
  `base.html`), never as a bare `<script>`/`<style>` in `{% block content %}`.
- `static/css/`, `static/js/`: put shared/reusable code here (e.g. `theme.css`, `main.js`).
  Page-only CSS/JS stays inline in that page's `extra_css`/`extra_js` block; only promote it to
  a dedicated `static/` file once it's reused across pages or big enough to need its own file.

## Multi-tenancy vs. privacy

Two separate layers — see `utils/db_helpers.py`.

- **`family_id`** — hard security boundary. Family A must never see Family B's data. All
  queries go through `family_query()` / `family_get()` / `family_get_or_404()`, never raw
  `Model.query`.
- **`owner_id`** — optional soft privacy *within* a family. Nullable FK to `users.id`; `NULL`
  = shared with the family, set = visible only to that user. Implemented on Account, Income/
  RecurringIncome, Pension, Loan, CreditCard, Vehicle, Expense, Plan. Child records without
  their own `owner_id` (`LoanPayment`, `PensionSnapshot`, `Transaction`, etc.) inherit
  visibility from a parent via `_inherited_visibility_models()`.
- Privacy on a source record never cascades to its linked bank `Transaction` if that
  transaction's `Account` is shared — shared accounts always show all their transactions to
  the family. Only cascade within the same domain (e.g. `LoanPayment` from `Loan`).
- New privacy field checklist: nullable `owner_id` column → register child models in
  `_inherited_visibility_models()` → wire `visibility` into the create/update service →
  Visibility `<select>` in the template → migrate → test.

## Migrations

SQLite `flask db migrate` always adds unrelated index/constraint noise. Trim `upgrade()`/
`downgrade()` down to only the intended table before running `flask db upgrade`. Validate with
`python -c "import ast; ast.parse(open('path').read())"`.

`family_id` must be set explicitly in service code, not left to the `before_flush` auto-stamp
in `app.py` (which only fires inside a real logged-in request).

## Tests

Run: `venv\Scripts\python.exe -m pytest -q`

- Fixtures in `tests/conftest.py`: `app`, `family`, `user`. `clean_db` autoclears tables.
- Scoping tests use monkeypatch, not real login:
  `monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)` /
  `get_current_user_id`.
- `test_credit_card_service.py` has its own local `family_id`/`card` fixtures — don't mix with
  conftest's `family`/`user` in that file.
