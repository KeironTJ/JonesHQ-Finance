from datetime import date
from decimal import Decimal

from extensions import db
from models.networth import NetWorth
from services.networth_service import NetWorthService


def test_delete_networth_snapshot_is_service_owned(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    snapshot = NetWorth(
        family_id=family.id,
        date=date(2026, 1, 1),
        year_month='2026-01',
        total_assets=Decimal('100'),
        total_liabilities=Decimal('25'),
        net_worth=Decimal('75'),
    )
    db.session.add(snapshot)
    db.session.commit()

    NetWorthService.delete_networth_snapshot(snapshot.id)

    assert db.session.get(NetWorth, snapshot.id) is None
