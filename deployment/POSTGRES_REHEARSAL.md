# SQLite to PostgreSQL migration (historical record)

> **COMPLETED — DO NOT RE-RUN.** Production was cut over to PostgreSQL in
> October 2026 and has accepted live writes since. The live database is
> `joneshq_finance_cutover_rehearsal` (despite its name). Never drop, clear,
> import into or test against it, and never switch back to the obsolete SQLite
> file. For current operations, updates, backups and recovery see the
> [production runbook](README.md).
>
> The text below is kept as a record of how the migration was prepared and
> validated. Statements such as "production remains on SQLite" describe the
> situation **before** cutover.

**Original guidance (pre-cutover):** do not change production's `DATABASE_URL` yet.
These steps prepare a disposable
database in the same LXC. The running application and maintenance timer stay on
SQLite. Production data-cleanup policy, application validation, LXC restore
coverage and a final cutover plan are still required before switching live.

The transfer tool refuses non-PostgreSQL targets, databases without the
`_rehearsal` suffix, URL query overrides and nonempty target schemas. It never
reads `DATABASE_URL` or `.env.production` to choose its destination.

## 1. Install PostgreSQL and the optional driver

After committing/pushing this preparation and deploying it normally while still
on SQLite, run as root inside the finance LXC:

```bash
cd /home/joneshq/joneshq-finance
apt update
apt install postgresql postgresql-client
systemctl enable --now postgresql
sudo -u postgres pg_isready
sudo -u joneshq /home/joneshq/joneshq-finance/venv/bin/pip install -r /home/joneshq/joneshq-finance/requirements-postgres.txt
```

Keep PostgreSQL private: use its local Unix socket, not a public database port.
Do not add firewall forwarding for port 5432. Check actual cluster listeners:

```bash
sudo -u postgres psql -X -Atc "SHOW listen_addresses"
```

The expected setting is `localhost` (or socket-only), not `*` or a public/LAN
address. Stop and correct it if broader than intended. Do not weaken `pg_hba.conf`
to `trust`.

Create a non-superuser role matching the app's existing Linux account, allowing
local peer authentication without a password in shell history:

```bash
sudo -u postgres createuser --no-superuser --no-createdb --no-createrole joneshq
sudo -u postgres createdb --owner=joneshq --template=template0 --encoding=UTF8 --lc-collate=C --lc-ctype=C joneshq_finance_rehearsal
sudo -u joneshq psql -X -d joneshq_finance_rehearsal -c "SELECT current_user, current_database();"
```

If that role or database already exists, **stop and inspect** rather than dropping,
replacing or granting privileges to an unknown existing resource. If peer login
fails, inspect the cluster authentication configuration; do not enable public access.
This single app role must not be superuser or able to create roles/databases.

## 2. Take a consistent SQLite snapshot

Do not copy the live `.db` file with `cp`: SQLite may have an active journal/WAL.
The online `.backup` API produces a consistent standalone snapshot while the app
runs. Keep this file private: it contains credentials and financial records.

```bash
install -d -o joneshq -g joneshq -m 700 /home/joneshq/postgres-rehearsal
sudo -u joneshq bash -c 'umask 077; sqlite3 /home/joneshq/joneshq-finance/instance/joneshq_finance.db ".backup /home/joneshq/postgres-rehearsal/source.db"'
```

Use a fresh, unused snapshot filename for later attempts. Do not upload this file
or send it through chat. The snapshot must be at the current application's migration
head. Existing schema drift, broken foreign keys, invalid boolean values or numeric
precision beyond declared scales block transfer; do not disable the checks or round
financial values automatically to force success.

## 3. Validate the source without opening PostgreSQL

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && venv/bin/python deployment/rehearse_postgres.py --source /home/joneshq/postgres-rehearsal/source.db'
```

This opens SQLite read-only and pins a read transaction. It checks integrity,
foreign keys, table/column coverage, booleans, numeric precision and migration
head, printing aggregate counts only. The source is never upgraded or modified.

### Approved legacy-data preparation

The reviewed policy keeps posted money at its existing scale (normally pennies)
and widens these calculated fields to eight decimal places, retaining their
existing whole-number capacity:

- `fuel_records.mpg`, `fuel_records.price_per_mile`
- `trips.approx_mpg`, `trips.gallons_used`, `trips.cumulative_gallons`
- `loans.monthly_apr`, `mortgage_snapshots.interest_rate`
- `pension_snapshots.growth_percent`, `property_valuation_snapshots.change_percent`

Migration `a24c6e8f1032` changes the PostgreSQL column types. On SQLite it deliberately
does not rebuild tables: SQLite does not enforce NUMERIC precision/scale, and the
raw stored values must remain intact. Models use the wider scale when reading;
calculated results may therefore differ from the old two-decimal intermediate
values. The migration does not recalculate historical records or round SQLite data.
Narrowing the PostgreSQL types on downgrade can round values; take a recovery dump.

After deploying this migration **while production is still SQLite**, take a fresh
snapshot at the new head. Do not reuse the earlier rounded rehearsal copy: its
discarded precision cannot be recovered by widening its schema.

Report the changes without writing:

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && venv/bin/python deployment/prepare_postgres_source.py --source /home/joneshq/postgres-rehearsal/fresh-source.db'
```

With the reviewed policy approved, prepare a **new** copy:

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && venv/bin/python deployment/prepare_postgres_source.py --source /home/joneshq/postgres-rehearsal/fresh-source.db --output /home/joneshq/postgres-rehearsal/prepared-source.db --apply-reviewed-policy'
```

This command pins a read-only source transaction and uses SQLite's backup API.
It refuses existing output files and the source path. In the copy only, it:

- Clears orphan card-category IDs only when there are no possible same-family
  exact head/sub-budget matches; it preserves all denormalized labels.
- Converts valid oversized ISO `YYYY-Www` card week labels into `ww-YYYY`.
- Rounds excess precision with `ROUND_HALF_EVEN` only in explicitly reviewed
  columns, using the current money/quantity/rate scales.
- Prints per-column affected counts, maximum rounding differences and signed
  aggregate rounding deltas, without individual records.
- Validates integrity, all foreign keys, schema, migration head, numeric scale
  **and capacity**, booleans and text lengths before reporting success.

SQLite decimal-to-binary storage can introduce a one-ULP representation difference
even after explicit rounding. Validation accepts this only when the difference is
at most one binary float step, that step is less than half the declared decimal
unit, and SQLAlchemy reads exactly the intended rounded Decimal. This is not a
general epsilon or permission to accept genuine excess decimal precision.
The final PostgreSQL transfer still compares every typed row exactly.

Unreviewed defects fail closed. Failed output created by this invocation is
removed; existing files are never overwritten. The tool neither connects to
PostgreSQL nor changes production configuration. Keep the report with the private
migration artifacts. Review the report before importing, especially financial
aggregate deltas; do not equate a successful copy with application validation.

For a final cutover, stop **all** app/background writers before the fresh snapshot
and keep them stopped through preparation, import, validation and the deliberate
configuration switch. A snapshot taken while production runs is rehearsal only.
Use an empty new target; never clear the previous successful rehearsal database.

## 4. Run the actual PostgreSQL integration test

Before the full snapshot import, test the PostgreSQL path with synthetic data.
The test requires an empty disposable database and rolls its schema/data back
even on success. It exercises exact typed values, cyclic links, sequence reset
and transaction rollback on the actual PostgreSQL backend:

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && PGCLIENTENCODING=UTF8 PG_REHEARSAL_DATABASE_URL=postgresql+psycopg:///joneshq_finance_rehearsal venv/bin/python -m pytest -q tests/test_postgres_rehearsal.py'
```

Install the existing development requirements first if pytest is missing:
`sudo -u joneshq venv/bin/pip install -r requirements-dev.txt`.
Do not run this against another database or use a production connection string.

## 5. Import the private snapshot into the empty rehearsal database

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && PGCLIENTENCODING=UTF8 PG_REHEARSAL_DATABASE_URL=postgresql+psycopg:///joneshq_finance_rehearsal venv/bin/python deployment/rehearse_postgres.py --source /home/joneshq/postgres-rehearsal/prepared-source.db --import-to-rehearsal'
```

The target schema is created from the current registered SQLAlchemy models, not
by replaying historical SQLite-specific DDL. The source must already be at that
same Alembic head. This is a reviewed current-schema baseline, not a way to skip
unapplied migrations. Future migrations continue from the recorded head.

Rows are inserted in foreign-key order; cyclic nullable links are restored without
changing timestamps. Every typed row is then compared in primary-key order
(including money, dates, credentials and links). PostgreSQL constraints remain
enabled. Identity sequences are reset before recording the migration head.
All target schema/data changes commit together or roll back on failure.
Errors do not print SQL parameters, row contents or connection credentials.

**A successful import is not a complete application compatibility test.** Still
needed: an isolated PostgreSQL-backed app smoke test covering sign-in, household
visibility, writes, financial calculations, exports/deletion and future migrations.
Do not expose that test instance publicly or configure it to send real emails.
Do not connect the normal live app or maintenance job to this disposable database.

Re-running a successful import refuses the now-nonempty target. Use a new
explicitly named disposable database for another attempt; the tool never clears
an existing target.

## 6. Report results and stop before cutover

Share only the aggregate success/error output, not the snapshot, URLs containing
passwords, database rows or secrets. If validation fails, investigate the indicated
table/column privately before changing source data.

Keep production on SQLite until all of these are ready:

- PostgreSQL application-level validation and migration-head/schema comparison.
- Verified PostgreSQL dump/restore and an agreed manual update-recovery procedure.
- LXC backups that include PostgreSQL data/WAL, are stored outside the container,
  and have been restored and checked.
- A maintenance window stopping app writers and the retention timer.
- A final fresh snapshot/import with the app stopped, not this older rehearsal.
- Deliberate production configuration switch and database/Redis health checks.
- A rollback decision before allowing writes. Returning to SQLite after accepting
  PostgreSQL writes loses those writes unless they are deliberately reconciled.

## 7. Updates and recovery after cutover

Moved to the [production runbook](README.md): see *Updating production*,
*Backups* and *Recovering from a failed update*. The procedure there is the one
to follow; it supersedes the pre-cutover wording that used to be here.

Rehearsal snapshots and cutover artifacts contain real personal data and
credentials. Remove only explicitly named files/directories once they are no
longer needed, after verifying their exact identity.
