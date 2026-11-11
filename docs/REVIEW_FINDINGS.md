# Review Findings

Reviewed: 11 November 2026.

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
| Payday synchronization | Saving payday through household Settings did not refresh stored transaction period labels used by filters and analytics. | [SettingsService](../services/finance/settings_service.py) now re-periods transactions when payday changes. A regression test checks the stored label, not just the setting value. |
| Payday transaction ownership | The re-period helper and its caller both committed, so a single action committed twice. | The helper now stages changes; its service caller owns the commit. A regression test reproduced two commits before the fix and requires one. |
| Payday permissions | A member with income access could change the household payday through the income endpoint even though household Settings are owner-only. | The endpoint now returns 403 for non-owners, and the template hides the control. Tests reproduced the previously accepted POST and visible member control. |
| Dead payday API | Unused calculation implementations duplicated the yearly summary and exposed an ignored `include_unpaid` argument. | Removed the unused methods and ignored argument; updated the dashboard caller. Reference/signature checks cover remaining callers. Forecasting still intentionally includes paid and unpaid transactions, with balance/category regression coverage. |
| F-001: private payday labels | Owner payday changes used `family_query`, so transactions on other members' private accounts kept stale period labels. | [Re-perioding](../services/finance/payday_service.py) is now scoped by `family_id` only (payday is household-wide), raises when no household is selected, and the income route no longer reports a count that would include private records. `family_query` visibility is unchanged. A [regression test](../tests/test_payday_service.py) covers another member's private account and an untouched second household. |
| F-002: balance recalculation scope | [Account](../models/transactions.py) and [card](../models/credit_card_transactions.py) recalculators filtered child rows by household only when request identity existed, so CLI/background calls summed rows from any household referencing that parent. | Child rows are now always restricted to the parent's own `family_id`; in a request the parent must also belong to the current household. The only identity-less caller (`flask maintenance purge-orphan-income-forecasts`) keeps working. [Tests](../tests/test_balance_recalculation.py) cover request and background execution with corrupt cross-household rows and foreign-household IDs; the background case failed before the fix. |
| Route balance orchestration | Transaction, credit-card and loan routes directly invoked model-level recalculation, with repeated loops, conditionals, and separate commits. | Centralized account/card calculations and combined commits in [BalanceService](../services/finance/balance_service.py). The three routes now pass affected IDs to the service; model methods remain compatibility wrappers for existing service callers. Regression tests verify deduplication, household scope and a single combined commit. |
| F-003: SQLite updater branch | `quick_update.sh` still carried a SQLite backup/rollback path, `backup.sh` and `rehearse_update_guard.py` although production is PostgreSQL-only (owner confirmed). The runbook also claimed failed config checks roll back and keep the site up, which was untrue for PostgreSQL. | Removed the SQLite branch, rollback helpers, `backup.sh` and the guard. `postgres_update_backup.py --check` is now the fail-closed preflight before any code pull, and owns the URL parser. Runbook corrected. [Updater tests](../tests/test_postgres_update.py) cover preflight URL validation and every failure stage of the real script. |
| Dead service/model code | 17 functions had no callers in Python, templates, JavaScript or tests, several marked deprecated or "kept for scripts" whose scripts were removed (e.g. `generate_all_future_transactions` and its two batch helpers, `calculate_tax_and_ni`, `sync_transaction_to_snapshot`, `get_mortgage_free_projection`, `TaxSettings.get_current`, `User.update_last_login`). | Removed them and the imports they left unused; corrected the [credit-card](CREDIT_CARD_IMPLEMENTATION.md) and [income](INCOME_PENSION_SYSTEM.md) method lists. Routes and WTForms validators (called implicitly) were excluded. Full suite passes. |
| Bank transaction deletion | Deleting any account transfer failed on PostgreSQL: the two legs reference each other and were deleted without unlinking. Bulk delete ignored the unselected leg entirely. A loan payment, income, fuel record, plan item, mortgage snapshot or childcare summary pointing at the transaction also blocked the delete, and privacy filtering hid other members' private links. Both paths also cleared `Expense.credit_card_transaction_id` whenever a *card* transaction ID equalled the deleted *bank* ID, silently unlinking unrelated expenses. | Single and bulk delete now share [`_delete_with_links`](../services/finance/transaction_service.py): it deletes both transfer legs and linked card payments, unlinks every other household reference regardless of member privacy, and breaks the circular link before deleting. Card-payment plan/expense links are cleared too. [Regression tests](../tests/test_transaction_deletion_links.py) run with foreign keys enforced; all failed before the fix. Documented in [Transaction Editing](TRANSACTION_EDITING.md). |
| Dead credit-card API | `generate_all_monthly_statements`, `delete_non_fixed_future_transactions` and `unlink_payment_and_transaction` had no callers; the module docstring still listed them as blueprint entry points. Removing the unused all-card generator also left `generate_future_monthly_statements` without a caller. Both live delete paths already handle their own links. | Removed the unused methods, corrected the docstring and the [credit-card guide](CREDIT_CARD_IMPLEMENTATION.md). |

## Follow-up Findings

### F-004: PostgreSQL application-level integration coverage

**Priority:** Medium (validation). **Status:** Resolved.

The deleted PostgreSQL tests exercised completed migration tooling, not a
general PostgreSQL-backed Flask application suite. The retained
[updater tests](../tests/test_postgres_update.py) exercise operational helpers;
they do not prove backend compatibility for application workflows.

The [CI workflow](../.github/workflows/tests.yml) now has a separate PostgreSQL 17
service and application job. It runs household isolation (including route sweeps),
credit-card, expense and income/forecast writes, payday and balance calculations, decimal/FK
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
into a new database without modifying the failed one. A private loopback-only
probe tests candidate startup before public traffic can resume.

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

**Priority:** Low (maintainability). **Status:** In progress; income forecast,
credit-card statement lifecycle and card-payment/bank synchronization extracted
and validated. Expense workflow boundaries remain.

`income_service.py` (previously about 1,600 lines), `credit_card_service.py`
(previously about 1,400) and `expense_sync_service.py` (about 1,350) contain multiple
workflows. A repository-wide reference screen found no uncalled public methods
in the income and expense services; the credit-card call-graph mapping found
three, which were removed (see Dead credit-card API). The reviewed expense
purchase-vs-reimbursement paths have distinct financial semantics rather than
being duplicate implementations.

Recurring payslip forecast generation and maintenance have moved into
[IncomeForecastService](../services/finance/income_forecast_service.py). Route,
projection, source-edit and test callers now use the new service directly; the
old forecast API was removed rather than retained as forwarding wrappers.
The focused income/forecast/member-retirement tests pass (**115 passed**), and
two additional maintenance-CLI dispatch regressions pass in the full local suite
(**1,123 passed, 3 skipped**). Forecast range
validation now lives with the forecast service rather than the source-record
service. Shared income-to-bank-transaction formatting remains in `IncomeService`;
a new regression reproduced the extraction's missing-helper error before it was
corrected, and verifies amount/date updates and the caller-owned commit boundary.
The PostgreSQL CI job now includes the migrated income service/forecast tests.

Credit-card statement interest, payment generation and future-chain
regeneration now live in
[CreditCardStatementService](../services/finance/credit_card_statement_service.py).
Both blueprint routes and direct tests use the extracted service. Shared vendor
lookups live in [credit_card_helpers.py](../services/finance/credit_card_helpers.py)
so the statement service and card CRUD/sync service do not depend on each other.
Regression tests cover generated amounts, payment links, replacing unlocked
chains, preserving locked statements and all-card aggregation.

The card-payment/bank-transaction sync pair has moved to
[CreditCardPaymentSyncService](../services/finance/credit_card_payment_sync_service.py).
The transaction and card services call it directly; the synchronization methods
do not commit, preserving the existing caller-owned transaction boundary.
Focused tests cover both directions' date, amount and status propagation,
bank/card refresh behavior, missing and already-paid links, and the no-commit
contract.

`ExpenseSyncService` is not one extraction-sized responsibility. Its immediate
expense reconciliation dispatches to bank, card-purchase or fuel-trip writes;
the separate reimbursement lifecycle handles period grouping, partial claims,
folded recurring-income payslips, and later card payoffs. Those paths share date
and claim helpers, and callers span the expense routes, `ExpenseService`,
`IncomeService` and forecast services. Splitting methods mechanically would
risk changing financial semantics or commit ownership. Keep its distinct
purchase-vs-reimbursement behavior, map the workflow and transaction boundaries
first, then extract a cohesive lifecycle as a unit.

Before this change, expense tests covered basic CRUD, linked-delete ordering,
a credit-card purchase refresh and one folded-payslip flow. New lifecycle tests
now cover cutoff ranges, partial claim reconciliation, same-period idempotence,
multi-period changes, sequential claims against folded payslips and multiple
reimbursement groups. Broader reimbursement update/deletion and full fuel-trip
coverage remain open. The PostgreSQL CI selection now includes the focused
reimbursement lifecycle and folded-payslip tests.

The lifecycle review found a concrete partial-claim defect: after creating
the partial reimbursement, the service called `_create_period_reimbursement`
without its required reimbursement-group argument. The resulting `TypeError`
was swallowed as a non-fatal follow-up failure, leaving the full-period
reimbursement at its pre-partial amount. The follow-up now reruns the normal
reconciliation for each affected expense period (including folded groups), and
logs a failure if that non-blocking correction cannot complete. Regression
tests reproduce the stale amount, verify same-period idempotence, and verify
partial claims crossing periods remove/update the appropriate full claims.

Folded-payslip regressions then found that partial claims could leave the
original folded reimbursement total and expense-to-income links in place. The
fold reconciliation now clears links for expenses moved to partial claims and
resets the folded total when no eligible expenses remain. Tests cover repeated
partial claims and verify that subsequently marking the payslip paid does not
re-mark partially claimed expenses as reimbursed.

The delete/privacy follow-up reproduced a failure path where both single and
bulk delete routes logged linked-cleanup exceptions but continued deleting the
expense. Cleanup also committed independently before expense deletion, so the
two operations did not share a rollback boundary; fuel-trip cleanup failures
were swallowed inside the cleanup service. Both routes now stage linked
transaction, statement, fuel-trip, and expense changes in one transaction and
commit only after all steps succeed. The cleanup service and expense deletion
methods retain their existing commit-by-default behavior for other callers.
Balances are recalculated before that commit so the recalculated state persists.
Late cleanup-failure regressions for both routes verify that the expense and
linked transaction remain intact after rollback. Cleanup queries include
private children within the current family: a visible expense may link to a
transaction private through its account or a generated trip private through its
vehicle. A regression covers deletion of the linked transaction from another
member's private account without exposing it.

Partial-reimbursement aggregation already uses household- and visibility-
scoped `family_query` calls. A regression now verifies that an expense private
to another household member and an expense in another household are excluded
from both the claim amount and claim-group updates.

Expense update also treated an explicitly blank vehicle registration as
"unchanged," despite the edit form offering a blank selection. This prevented
removing a vehicle from a fuel expense and left its generated trip in place.
The update now clears the registration when the submitted field is blank, and
trip reconciliation includes private child trips within the same household so
the stale generated row can be removed without exposing it. A route regression
clears a private vehicle from a shared fuel expense and verifies both the
registration and generated trip are removed.

**Remaining review:** investigate whether date or amount edits can invalidate
or deleting an expense can leave an existing partial reimbursement transaction
stale. `reconcile_periods` only rebuilds full-period claims, while partial
transactions use a distinct payment type; expense update/delete and set-period
routes do not currently reconcile those partial transactions. Before changing
that behavior, choose whether those operations should update unpaid partial
claims or block edits/deletion until the expense is unclaimed. Defer service
extraction until a cohesive boundary and unchanged financial behavior can be
demonstrated.

The lifecycle follow-up now captures the expense's old reimbursement period
before an edit and reconciles both old and new periods. Single and bulk deletion
reconcile affected reimbursement totals, including removing an unpaid
reimbursement when its last expense is deleted. Card payoff reconciliation
updates linked payment amount/date and account balance, and removes stale unpaid
payoffs after their reimbursement or card expenses disappear while preserving
paid transactions. Fuel-expense reconciliation updates an existing generated
trip when its date, vehicle, or mileage changes, and removes stale generated
trips when the expense no longer has a valid vehicle or is no longer a fuel
expense.

**Acceptance:** each extraction has unchanged financial results, household and
privacy scoping, and regression coverage for all existing callers; do not add
compatibility wrappers that only preserve a retired API.

### F-008: Private startup probe failed its proxy guard

**Priority:** High (update reliability). **Status:** Deployed; the operator
reports the latest updates are running without identified issues (11 November
2026).

Three production updates passed tests and migrations but failed the private
probe and automatically recovered to the prior code and a new database each
time. The first three attempts failed with curl exit 7 because `systemd-run`
returns before Gunicorn creates its listener. A bounded readiness retry fixed
that race, but the next attempt returned HTTP 403, exposing a second issue:
Unix-domain-socket requests do not provide the loopback IP that the proxy guard
explicitly permits. The recovered app remained active and returned HTTP 200
from `/healthz`.

The updater now runs the probe on an ephemeral TCP port bound only to
`127.0.0.1`, which the existing middleware allows without trusting forwarded
headers. It polls health for at most 30 attempts, with a two-second request
limit and one-second gaps. Startup output is written to a private recovery-
directory log rather than depending on transient-unit journal retention.

Delayed-listener regressions verify successful startup without recovery,
bounded failure, retained diagnostics, and the real proxy guard accepting the
loopback probe. Existing proxy tests continue to reject non-loopback, untrusted
direct clients. The focused updater/recovery/proxy suite passed (**53 passed**);
the operator now confirms the latest production update is running without
issues identified so far. The runbook's ad-hoc backup command reads the
configured active database instead of assuming the original pre-recovery
database name.

## Validation for This Pass

- Fuel-vehicle update follow-up: **73 focused expense, reimbursement, and
  credit-card tests passed**. The route regression covers clearing a private
  vehicle from a shared fuel expense and removing its generated trip.
- Expense delete-boundary/privacy follow-up: **28 focused route, service, and
  reimbursement tests passed**; the credit-card service suite passed **44
  tests**. Pylance found all 16 call sites compatible with the preserved
  commit-by-default service signatures. A full local suite attempt was not
  counted as passing: it encountered `no such table` errors across unrelated
  later tests after an earlier failure; targeted tests passed in isolation.
  Both CI jobs passed for `ff95b23` in
  [run 43106362538](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/43106362538):
  the full SQLite suite reported **1,746 passed, 3 skipped**, and the PostgreSQL
  17 application/migration regressions passed.
- Partial reimbursement follow-up: a regression reproduced the stale full-period
  amount before the fix. The focused expense/reimbursement/card/transaction
  tests passed (**72 passed**); the full local suite passed (**1,732 passed,
  3 skipped**, 15 warnings). The SQLite and PostgreSQL jobs, including the new
  lifecycle and folded-payslip regressions, passed in
  [CI run 43001275033](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/43001275033).
- Folded reimbursement follow-up: the full local suite passed (**1,734 passed,
  3 skipped**, 15 warnings). Both the full pytest and PostgreSQL jobs passed for
  `49dbe11` in
  [CI run 43052164225](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/43052164225).
- Expense edit/delete and generated-payment/fuel-trip follow-up: focused lifecycle
  and route tests passed (**25 passed**); the full local suite passed (**1,741
  passed, 3 skipped**, 15 warnings). Both the full pytest and PostgreSQL jobs
  passed for `77e8804` in
  [CI run 43059918420](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/43059918420).
- Before the payment-sync extraction (`0904366`): local full suite
  **1,726 passed, 3 skipped**,
  with 15 warnings. The two jobs in the [latest CI run](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/42924793110)
  (SQLite full suite and PostgreSQL 17 application/migration regressions)
  both passed. The operator reports production is running the latest updates
  without identified issues so far; production health was not independently
  queried during this review.
- Private probe readiness: **44 updater/recovery tests passed, 1 skipped**
  locally on Windows; Bash syntax and diff whitespace checks passed. The skip
  is the real Unix-socket/curl regression. Both CI jobs passed for `665f176` in
  [CI run 39772113979](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/39772113979).
  The Linux full suite reported **1,136 passed, 3 skipped**, including the real
  delayed Unix-socket/curl regression.
- Loopback proxy-guard probe: focused local updater/recovery/proxy suite
  **53 passed**; both CI jobs passed for `3c259f5` in
  [CI run 39773858676](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/39773858676).
  The SQLite job reported **1,136 passed, 3 skipped**; the PostgreSQL 17
  application and migration regression job also passed.
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
  3 skipped**, with 15 warnings. Both SQLite and PostgreSQL jobs also passed on
  the pushed commit in [CI run 39758917364](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/39758917364).
- Focused income, forecast, income-route, and member-retirement tests after the
  forecast-service extraction: **115 passed**, plus two maintenance-CLI
  dispatch regressions. Full local SQLite suite after the extraction:
  **1,123 passed, 3 skipped**, with 15 warnings.
- Both CI jobs passed for forecast extraction commit `1176a0d` in
  [CI run 39763724097](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/39763724097).
  The expanded PostgreSQL 17 job passed **154 tests**, including the migrated
  income/forecast tests and new shared-helper/CLI regressions.
- Bank transaction deletion: **7 new regressions** (transfer pair, bulk partial
  transfer, both legs selected, every household reference including private rows,
  and the card/bank ID collision, single and bulk) all failed on the previous
  code under enforced foreign keys and pass after the fix. The transaction
  service and deletion tests now also run in the PostgreSQL CI job. Full local
  SQLite suite: **1,130 passed, 3 skipped**. Both CI jobs passed for commit
  `6bf3b61` in [CI run 39765417373](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/39765417373),
  so the deletion fixes are also verified on PostgreSQL 17.
- Credit-card statement-service extraction: **36 focused tests passed** and
  the full local SQLite suite passed (**1,132 passed, 3 skipped**, 15 warnings).
  Both CI jobs passed for commit `23b5b9c` in
  [CI run 39767135667](https://github.com/KeironTJ/JonesHQ-Finance/actions/runs/39767135667):
  SQLite reported **1,132 passed, 3 skipped** and PostgreSQL 17 reported **170 passed**.
  An AST comparison confirmed the live extracted method bodies match their
  previous implementations; the now-unreferenced monthly helper was removed.
- Pylance resolved forecast callers across the app CLI, income routes, source
  workflows, projection service and tests. An AST comparison verified that the
  moved methods differ only in service references and uncommitted balance-service
  delegation; no forecast APIs remain as forwarding wrappers on `IncomeService`.
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
