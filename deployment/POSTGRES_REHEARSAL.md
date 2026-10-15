# SQLite to PostgreSQL: rehearsal only

**Do not change production's `DATABASE_URL` yet.** These steps prepare a disposable
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
sudo -u postgres createdb --owner=joneshq joneshq_finance_rehearsal
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

## 4. Run the actual PostgreSQL integration test

Before the full snapshot import, test the PostgreSQL path with synthetic data.
The test requires an empty disposable database and rolls its schema/data back
even on success. It exercises exact typed values, cyclic links, sequence reset
and transaction rollback on the actual PostgreSQL backend:

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && PG_REHEARSAL_DATABASE_URL=postgresql+psycopg:///joneshq_finance_rehearsal venv/bin/python -m pytest -q tests/test_postgres_rehearsal.py'
```

Install the existing development requirements first if pytest is missing:
`sudo -u joneshq venv/bin/pip install -r requirements-dev.txt`.
Do not run this against another database or use a production connection string.

## 5. Import the private snapshot into the empty rehearsal database

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && PG_REHEARSAL_DATABASE_URL=postgresql+psycopg:///joneshq_finance_rehearsal venv/bin/python deployment/rehearse_postgres.py --source /home/joneshq/postgres-rehearsal/source.db --import-to-rehearsal'
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

## 7. Updates and recovery after a future PostgreSQL cutover

LXC backups remain the main disaster-recovery system; this change does not add a
scheduled database backup or change `backup.sh`. Do not schedule the SQLite-only
`backup.sh` after a PostgreSQL cutover: it would back up the obsolete SQLite file.
Check existing cron jobs/timers as part of cutover.

Deploy the new updater/helper files while production is still on SQLite. The
updater validates the backend before pulling, supports `postgresql+psycopg` URLs
with an explicit database name and no query parameters, and installs
`requirements-postgres.txt` on PostgreSQL. The Linux app user must be able to
authenticate to PostgreSQL (local peer authentication is suitable for this LXC).
Install matching PostgreSQL client tools, including `pg_dump` and `pg_restore`.
The maintenance scripts explicitly use UTF8 client encoding. Do not use shell
`source` on `.env.production`; the helpers parse it literally like the existing
configuration checker.

For PostgreSQL, `quick_update.sh`:

1. Records the current commit and a private environment-file copy in a unique
   `/home/joneshq/backups/postgres-update-*` directory.
2. Stops the retention timer/service and the app before creating `database.dump`.
   Records the timer's prior active state in `maintenance-timer-active` (1 or 0).
   Stop any other independently configured writers before running the updater.
3. Creates a custom-format PostgreSQL dump as the app user and verifies its
   archive listing. A failed dump is removed and the update stops before pulling.
4. Pulls code, installs dependencies, checks configuration and runs tests.
5. Runs migrations using `.env.production`, not Flask's default development
   database, then restarts the app and checks health.
6. Restarts the retention timer only if it was previously active.

**On any failure after maintenance begins, the app and retention jobs are left
stopped. There is no automatic PostgreSQL restore or code rollback.** Review the
reported recovery directory/previous commit before restarting. An archive listing
is not a restore test; perform the separate restore rehearsal before cutover.
Only treat `database.dump` as confirmed if the helper reported success.
An incomplete-update marker at
`/home/joneshq/backups/postgres-update-incomplete` records the recovery directory
and blocks subsequent updater runs until an operator resolves the failure.

Manual recovery checklist:

- Keep the app, retention jobs and any other writers stopped. Preserve logs and
  the failed database for diagnosis; do not delete it or blindly reset code.
- Decide whether a forward fix is safer. Dependency/test failures before
  migration do not themselves require restoring the database.
- If restore is needed, create a **new**, explicitly named UTF8 database owned
  by the app role, using `template0` and the original locale. Never restore over
  the failed database as the first recovery step.
- Restore the confirmed dump to that empty database with
  `pg_restore --single-transaction --exit-on-error`, as the app user. Verify the
  migration version, rows, sequences and application behavior before using it.
- Restore the recorded compatible code/dependencies and review the saved
  environment file privately. Deliberately point `.env.production` at the
  recovered database; retain all original credentials/settings securely.
- Check production configuration, restart the app, verify health/login and only
  then re-enable the retention timer if it was previously enabled.
- Once recovery is confirmed, remove only the reviewed
  `/home/joneshq/backups/postgres-update-incomplete` marker to permit updates again.
- If any writes were accepted after the recovery dump (including during the
  startup health-check window), reconcile those writes before a restore-based
  recovery. A dump is a point-in-time copy, not zero-data-loss rollback.

Recovery directories contain credentials and personal data. They are not
automatically pruned; set an explicit retention policy and remove only reviewed,
specifically named recovery directories after recovery is no longer needed.

Rehearsal snapshots contain real personal data. Remove only the explicitly named
rehearsal file/database when no longer needed, after verifying their exact identity.
The operator must set an appropriate retention period; the tool does not schedule
cleanup or change the existing backup policy.
