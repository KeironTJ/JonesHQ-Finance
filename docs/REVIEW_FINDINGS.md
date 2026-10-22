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
| Route balance orchestration | Transaction, credit-card and loan routes directly invoked model-level recalculation, with repeated loops, conditionals, and separate commits. | Centralized account/card calculations and combined commits in [BalanceService](../services/finance/balance_service.py). The three routes now pass affected IDs to the service; model methods remain compatibility wrappers for existing service callers. Regression tests verify deduplication, household scope and a single combined commit. |
| F-003: SQLite updater branch | `quick_update.sh` still carried a SQLite backup/rollback path, `backup.sh` and `rehearse_update_guard.py` although production is PostgreSQL-only (owner confirmed). The runbook also claimed failed config checks roll back and keep the site up, which was untrue for PostgreSQL. | Removed the SQLite branch, rollback helpers, `backup.sh` and the guard. `postgres_update_backup.py --check` is now the fail-closed preflight before any code pull, and owns the URL parser. Runbook corrected. [Updater tests](../tests/test_postgres_update.py) cover preflight URL validation and every failure stage of the real script. |
| Dead service/model code | 17 functions had no callers in Python, templates, JavaScript or tests, several marked deprecated or "kept for scripts" whose scripts were removed (e.g. `generate_all_future_transactions` and its two batch helpers, `calculate_tax_and_ni`, `sync_transaction_to_snapshot`, `get_mortgage_free_projection`, `TaxSettings.get_current`, `User.update_last_login`). | Removed them and the imports they left unused; corrected the [credit-card](CREDIT_CARD_IMPLEMENTATION.md) and [income](INCOME_PENSION_SYSTEM.md) method lists. Routes and WTForms validators (called implicitly) were excluded. Full suite passes. |

## Follow-up Findings

### F-004: PostgreSQL application-level integration coverage

**Priority:** Medium (validation). **Status:** Resolved.

The deleted PostgreSQL tests exercised completed migration tooling, not a
general PostgreSQL-backed Flask application suite. The retained
[updater tests](../tests/test_postgres_update.py) exercise operational helpers;
they do not prove backend compatibility for application workflows.

The [CI workflow](../.github/workflows/tests.yml) now has a separate PostgreSQL 17
service and application job. It runs household isolation (including route sweeps),
credit-card and expense writes, payday and balance calculations, decimal/FK
checks, the current release migration upgrade/downgrade, and a real dump/restore
that verifies records, sequences and preservation of the failed database.
The SQLite job still runs the full suite. The historical migration chain assumes
a pre-Alembic schema; this does not claim a from-empty replay of every old migration.

[Test fixtures](../tests/conftest.py) accept only a local `joneshq_ci_*` database,
create a unique schema and remove only that schema. The recovery regression
creates/removes only its own uniquely named recovery database. No production
database or database named `cutover_rehearsal` is used.

This coverage reproduced two PostgreSQL errors hidden by SQLite: request IDs were
bound as VARCHAR when compared to integer keys. The shared
[lookup helpers](../utils/db_helpers.py) now normalize valid form/query IDs to
integers and explicitly reject invalid IDs. Both backends exercise this regression.

### F-005: Flask-Login uses deprecated UTC date construction

**Priority:** Low (dependency maintenance). **Status:** Accepted/deferred by owner.

The full test run reports `datetime.datetime.utcnow()` deprecation warnings
from Flask-Login's `login_manager.py` while exercising remember-me cookies.
This is third-party code, not a reason to patch the virtual environment.

**Required follow-up:** evaluate an upstream correction when updating the
[pinned dependency](../requirements.txt), and rerun remember-me, passkey,
two-factor, and session-expiry regressions before changing the pin.

### F-006: Update failures required manual recovery even before public writes

**Priority:** High (operational reliability). **Status:** Resolved.

The owner approved automatic recovery while writers remain stopped, including
creation of a new recovery database via the local `postgres` administrator.
[The updater](../deployment/quick_update.sh) snapshots code identity, environment,
virtual environment and recovery helpers. Before public startup, failures restore
the old code/dependencies; once migrations start, a confirmed dump is restored
into a new database without modifying the failed one. A private Unix-socket probe
tests candidate startup before public traffic can resume.

Automatic restore is deliberately disabled once public startup is attempted:
writes may have resumed. Failed recovery, interruption that bypasses shell traps,
or unsupported database configurations retain the manual-recovery marker.
External writers must be stopped by the operator. See the
[runbook](../deployment/README.md) for bootstrap, disk-space and recovery requirements.

[Control-flow tests](../tests/test_postgres_update.py) execute the real shell
script across update and recovery failures; [helper tests](../tests/test_postgres_recovery.py)
verify that configuration changes only after successful restore, failures are
redacted, and remote targets are rejected.

### F-007: Large financial services have mixed responsibilities

**Priority:** Low (maintainability). **Status:** Open; no behavior defect
confirmed in this structural review.

`income_service.py` (about 1,600 lines), `credit_card_service.py` (about 1,400)
and `expense_sync_service.py` (about 1,350) contain multiple workflows. A
repository-wide reference screen found no uncalled public methods in these
services, and the reviewed expense purchase-vs-reimbursement paths have distinct
financial semantics rather than being duplicate implementations. The size alone
does not justify moving methods: service methods call across these workflows and
are referenced by routes, jobs and tests.

**Suggested follow-up:** map the public call graph and identify a cohesive
boundary—income forecast generation is a candidate—before extracting a new
service. Preserve current imports until callers are migrated intentionally.

**Acceptance:** each extraction has unchanged financial results, household and
privacy scoping, and regression coverage for all existing callers; do not add
compatibility wrappers that only preserve a retired API.

## Validation for This Pass

- Full SQLite CI suite after recovery/CI changes: **1,119 passed, 3 skipped**,
  with 15 warnings. PostgreSQL-only integration tests are skipped on SQLite.
- PostgreSQL 17 CI suite: **56 passed**, including real dump/restore, preserved
  failed-database contents, sequence continuity, constraints and migration round-trip.
  Both jobs passed in [CI run 39755403685](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/39755403685).
  This run exposed a deprecated Alembic `db.get_engine()` compatibility branch;
  replaced it with `db.engine`, supported by the pinned Flask-SQLAlchemy version.
- Windows Application Control blocked local `psql`; real recovery was verified
  in Linux CI without bypassing that restriction.
- New regressions were confirmed to fail before their fixes where the bug was
  reproducible (F-002 background recalculation; payday cases noted above).
- The balance-service extraction passed **74 focused tests** across recalculation,
  transaction, credit-card, loan and household-isolation workflows.
- All balance recalculation calls were removed from the transaction,
  credit-card and loan route modules; service compatibility entry points still
  pass the existing service and model tests.
- Full local SQLite suite after the balance-service extraction: **1,120 passed,
  3 skipped**, with 15 warnings. PostgreSQL integration will be rerun by CI for
  this commit.
- Bash syntax check passed for `quick_update.sh`; updater control-flow tests
  execute the real script for every failure stage.
- Relative link targets passed across all 28 Markdown files; no operational
  references to removed scripts, deployment files or functions remain.
- The warnings comprise the Flask-Login deprecation (F-005) and an intentional
  test exercising the production-on-SQLite configuration warning.
- No production maintenance command, import, or data migration was run.

## Maintenance

For each new finding, record the observed behavior, affected code, reproduction,
impact, next action, and acceptance checks. Distinguish an observed failure
from a suspected issue. Update status when fixed; do not accumulate warnings
for obsolete code that can instead be removed safely.
