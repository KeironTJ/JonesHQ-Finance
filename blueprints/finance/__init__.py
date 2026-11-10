from services.finance.settings_navigation_service import FinanceSettingsNavigationService


def register_blueprints(app):
    from .accounts import accounts_bp
    from .categories import bp as categories_bp
    from .childcare import childcare_bp
    from .credit_cards import credit_cards_bp
    from .dashboard import dashboard_bp
    from .expenses import expenses_bp
    from .income import income_bp
    from .loans import loans_bp
    from .mortgage import mortgage_bp
    from .networth import networth_bp
    from .onboarding import onboarding_bp
    from .pensions import pensions_bp
    from .plans import plans_bp
    from .preferences import finance_preferences_bp
    from .settings import settings_bp
    from .transactions import transactions_bp
    from .vehicles import vehicles_bp
    from .vendors import bp as vendors_bp

    for blueprint in (
        accounts_bp, categories_bp, childcare_bp, credit_cards_bp, dashboard_bp,
        expenses_bp, income_bp, mortgage_bp, networth_bp, onboarding_bp,
        pensions_bp, plans_bp, finance_preferences_bp, settings_bp,
        transactions_bp, vehicles_bp, vendors_bp,
    ):
        app.register_blueprint(
            blueprint,
            url_prefix='/finance' + (blueprint.url_prefix or ''),
        )
    app.register_blueprint(loans_bp, url_prefix='/finance/loans')


MODULE = {
    'key': 'finance',
    'title': 'Finance',
    'description': 'A clear view of your money, from everyday banking and bills to borrowing and longer-term plans.',
    'icon': 'bi-wallet2',
    'home_endpoint': 'dashboard.index',
    'overview_label': 'Finance overview',
    'navigation_template': 'finance/_navigation.html',
    'page_labels': {'finance_preferences': 'Finance preferences', 'networth': 'Net worth'},
    'status': 'available',
    'requires_household': True,
    'default_destination': True,
    'register_blueprints': register_blueprints,
    'settings_group': FinanceSettingsNavigationService.get_group,
}
