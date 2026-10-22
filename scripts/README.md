# Scripts

Only the model-driven family-ID diagnostic is retained here. Historical
imports, one-off data repairs, completed migrations, and ad-hoc test scripts
have been removed. Their source remains in Git history, but they are not
supported operational tools and should not be restored as setup steps.

## Missing Family IDs

From the repository root, after confirming the application's target database:

```powershell
venv\Scripts\python.exe scripts\checks\check_family_id_integrity.py
```

The check reads registered SQLAlchemy models rather than a copied table list.
It reports tenant-owned rows with a missing `family_id` and exits non-zero when
any are found. Global tax defaults, household-less users, and security events
are deliberately excluded because a NULL household is valid for those records.

For foreign keys that cross household boundaries, use the application's
read-only tenancy checker:

```powershell
venv\Scripts\python.exe -m flask maintenance check-tenancy
```

## Supported Alternatives

- **Database setup and upgrades:** apply checked-in Flask-Migrate revisions;
  see the [Quick Start](../docs/QUICKSTART.md).
- **Account creation:** use household-invite registration or family invitations;
  see [authentication setup](../docs/AUTHENTICATION_SETUP.md).
- **Payday changes:** use the household settings or recurring-income update flow;
  see [payday tracking](../docs/PAYDAY_TRACKING.md).
- **Balance-cache rebuilds:** use the net-worth cache-refresh action;
  see [monthly balance cache](../docs/MONTHLY_BALANCE_CACHE.md).
- **Production updates, backups, and recovery:** follow the
  [production runbook](../deployment/README.md).

New imports or bulk repair tools need explicit household scoping, reviewed
inputs, regression tests, and a recovery plan. Do not add hard-coded personal
records or duplicate service logic.
