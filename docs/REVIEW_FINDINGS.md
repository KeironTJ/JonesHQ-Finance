# Review Findings

Reviewed: 22 October 2026.

This is an actionable record for the cleanup and behavior review, not a claim
that every application path has been audited. Resolve confirmed issues in the
same change where practical; retain an open finding only when its scope or
validation requirements prevent a safe fix.

## Resolved in This Pass

| Area | Finding | Resolution and evidence |
| --- | --- | --- |
| Legacy scripts | Historical imports, completed migrations, ad-hoc tests, hard-coded data repairs, and global destructive resets remained runnable. Some used unscoped model queries or wrote data despite diagnostic names. | Removed the obsolete scripts rather than retaining warning-only wrappers. The retained [diagnostic](../scripts/checks/check_family_id_integrity.py) has automated tests; supported alternatives are in the [script guide](../scripts/README.md). |
| Deployment history | Completed SQLite installation/cutover procedures and their tools remained beside the current production procedure. | Removed the obsolete guides, installer, migration-only tools, and their dedicated tests. Kept the live update/backup dependency chain. The [production runbook](../deployment/README.md) is the sole operational guide. |
| Duplicated documentation | The index copied schema/directory inventories; the payday proposal duplicated implemented behavior; the credit-card guide repeated completion reports and told readers to generate already-existing migrations. | Reduced the [index](README.md) to links, merged payday documentation, and removed historical credit-card status/import/migration instructions. Removed the obsolete provider-specific category-mapping document with the retired imports. |
| Stale instructions | Authentication, cache, and import guides referenced removed scripts. The service guide said signed-in theme choice was browser-local. Cache documentation quoted unverified performance measurements. | Replaced script commands with supported application/CLI flows, corrected appearance persistence, and removed unsupported benchmark claims. |
| Diagnostic coverage | The missing-family-ID check maintained a stale table list and treated global tax defaults as invalid. | Derive tenant tables from registered model metadata and explicitly allow valid household-less records. [Tests](../tests/test_family_id_integrity.py) cover current supporting tables and missing-family rows. |
| Payday validation | The recurring-income form accepted day 0, but date construction did not consistently support it. Numeric 0 could also bypass optional-input validation. Invalid stored days were silently clamped. | New values must be 1-31; legacy stored 0 means month end. Other invalid stored days raise an explicit error. The form uses day 31 for month end. [Regression tests](../tests/test_payday_service.py) reproduced the invalid-input cases before correction. |
| Payday synchronization | Saving payday through household Settings did not refresh stored transaction period labels used by filters and analytics. | [SettingsService](../services/platform/settings_service.py) now re-periods transactions when payday changes. A regression test checks the stored label, not just the setting value. |
| Payday transaction ownership | The re-period helper and its caller both committed, so a single action committed twice. | The helper now stages changes; its service caller owns the commit. A regression test reproduced two commits before the fix and requires one. |
| Payday permissions | A member with income access could change the household payday through the income endpoint even though household Settings are owner-only. | The endpoint now returns 403 for non-owners, and the template hides the control. Tests reproduced the previously accepted POST and visible member control. |
| Dead payday API | Unused calculation implementations duplicated the yearly summary and exposed an ignored `include_unpaid` argument. | Removed the unused methods and ignored argument; updated the dashboard caller. Reference/signature checks cover remaining callers. Forecasting still intentionally includes paid and unpaid transactions, with balance/category regression coverage. |
| F-001: private payday labels | Owner payday changes used `family_query`, so transactions on other members' private accounts kept stale period labels. | [Re-perioding](../services/finance/payday_service.py) is now scoped by `family_id` only (payday is household-wide), raises when no household is selected, and the income route no longer reports a count that would include private records. `family_query` visibility is unchanged. A [regression test](../tests/test_payday_service.py) covers another member's private account and an untouched second household. |
| F-002: balance recalculation scope | [Account](../models/transactions.py) and [card](../models/credit_card_transactions.py) recalculators filtered child rows by household only when request identity existed, so CLI/background calls summed rows from any household referencing that parent. | Child rows are now always restricted to the parent's own `family_id`; in a request the parent must also belong to the current household. The only identity-less caller (`flask maintenance purge-orphan-income-forecasts`) keeps working. [Tests](../tests/test_balance_recalculation.py) cover request and background execution with corrupt cross-household rows and foreign-household IDs; the background case failed before the fix. |
| F-003: SQLite updater branch | `quick_update.sh` still carried a SQLite backup/rollback path, `backup.sh` and `rehearse_update_guard.py` although production is PostgreSQL-only (owner confirmed). The runbook also claimed failed config checks roll back and keep the site up, which was untrue for PostgreSQL. | Removed the SQLite branch, rollback helpers, `backup.sh` and the guard. `postgres_update_backup.py --check` is now the fail-closed preflight before any code pull, and owns the URL parser. Runbook corrected. [Updater tests](../tests/test_postgres_update.py) cover preflight URL validation and every failure stage of the real script. |
| Dead service/model code | 17 functions had no callers in Python, templates, JavaScript or tests, several marked deprecated or "kept for scripts" whose scripts were removed (e.g. `generate_all_future_transactions` and its two batch helpers, `calculate_tax_and_ni`, `sync_transaction_to_snapshot`, `get_mortgage_free_projection`, `TaxSettings.get_current`, `User.update_last_login`). | Removed them and the imports they left unused; corrected the [credit-card](CREDIT_CARD_IMPLEMENTATION.md) and [income](INCOME_PENSION_SYSTEM.md) method lists. Routes and WTForms validators (called implicitly) were excluded. Full suite passes. |

## Open Findings

### F-004: PostgreSQL application-level integration coverage

**Priority:** Medium (validation). **Status:** Open.

The deleted PostgreSQL tests exercised completed migration tooling, not a
general PostgreSQL-backed Flask application suite. The retained
[updater tests](../tests/test_postgres_update.py) exercise operational helpers;
they do not prove backend compatibility for application workflows.

**Required follow-up:** run representative household isolation, financial
writes, constraints, and migration checks against a fresh disposable
PostgreSQL database in CI. Never point tests at production or the database
whose name contains `cutover_rehearsal`.

**Acceptance:** a dedicated isolated job fails on application/backend
incompatibilities and tears down only its own disposable database.

### F-005: Flask-Login uses deprecated UTC date construction

**Priority:** Low (dependency maintenance). **Status:** Open.

The full test run reports `datetime.datetime.utcnow()` deprecation warnings
from Flask-Login's `login_manager.py` while exercising remember-me cookies.
This is third-party code, not a reason to patch the virtual environment.

**Required follow-up:** evaluate an upstream correction when updating the
[pinned dependency](../requirements.txt), and rerun remember-me, passkey,
two-factor, and session-expiry regressions before changing the pin.

## Validation for This Pass

- Full suite: **1,103 passed**, with 15 warnings (count reflects removed SQLite
  updater tests and added payday, recalculation and preflight regressions).
- New regressions were confirmed to fail before their fixes where the bug was
  reproducible (F-002 background recalculation; payday cases noted above).
- Bash syntax check passed for `quick_update.sh`; updater control-flow tests
  execute the real script for every failure stage.
- Relative link targets passed across all 28 Markdown files; no references to
  removed scripts, deployment files or functions remain.
- The warnings comprise the Flask-Login deprecation (F-005) and an intentional
  test exercising the production-on-SQLite configuration warning.
- No production maintenance command, import, or data migration was run.

## Maintenance

For each new finding, record the observed behavior, affected code, reproduction,
impact, next action, and acceptance checks. Distinguish an observed failure
from a suspected issue. Update status when fixed; do not accumulate warnings
for obsolete code that can instead be removed safely.
