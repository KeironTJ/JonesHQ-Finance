from extensions import db
from models.accounts import Account
from services.dashboard_service import DashboardService


def test_dashboard_data_scopes_accounts_and_builds_empty_summaries(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.dashboard_service.NetWorthService.calculate_current_networth',
        lambda: {'total': 100},
    )
    monkeypatch.setattr(
        'services.dashboard_service.PaydayService.get_payday_summary_for_year',
        lambda account_id, year, include_unpaid: [{'account_id': account_id, 'year': year}],
    )
    account = Account(
        family_id=family.id,
        name='Joint Current',
        account_type='Joint',
        balance=0,
        is_active=True,
    )
    db.session.add(account)
    db.session.commit()

    data = DashboardService.get_dashboard_data(None, 2026)

    assert data['accounts'] == [account]
    assert data['selected_account'] == account
    assert data['accounts'][0].calculated_balance == 0.0
    assert data['payday_data'] == [{'account_id': account.id, 'year': 2026}]
    assert data['networth'] == {'total': 100}
    assert data['credit_card_summary']['count'] == 0
    assert data['loan_summary']['count'] == 0
    assert data['mortgage_summary'] is None
    assert data['pension_summary']['count'] == 0
