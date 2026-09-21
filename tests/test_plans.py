from datetime import date
from decimal import Decimal

from extensions import db
from models.categories import Category
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.plans import Plan, PlanItem
from models.transactions import Transaction


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_plan_totals_use_linked_transaction_over_manual_cost(family):
    category = Category(
        family_id=family.id,
        name='Gifts',
        category_type='expense',
        head_budget='Lifestyle',
        sub_budget='Gifts',
    )
    transaction = Transaction(
        family_id=family.id,
        category=category,
        amount=Decimal('-42.50'),
        transaction_date=date.today(),
        description='Gift shop',
    )
    plan = Plan(
        family_id=family.id,
        title='Christmas',
        target_amount=Decimal('100.00'),
    )
    plan.items = [
        PlanItem(
            family_id=family.id,
            title='Scooter',
            assigned_to='Oliver',
            estimated_cost=Decimal('60.00'),
            actual_cost=Decimal('55.00'),
            transaction=transaction,
        ),
        PlanItem(
            family_id=family.id,
            title='Book',
            estimated_cost=Decimal('15.00'),
            actual_cost=Decimal('12.00'),
        ),
    ]
    db.session.add(plan)
    db.session.commit()

    assert plan.estimated_total == Decimal('75.00')
    assert plan.actual_total == Decimal('54.50')
    assert plan.progress_percent == 54
    assert plan.items[0].assigned_to == 'Oliver'


def test_plan_item_uses_linked_credit_card_purchase_as_actual_cost(family):
    card = CreditCard(
        family_id=family.id,
        card_name='Rewards Card',
        annual_apr=24,
        monthly_apr=2,
        min_payment_percent=2,
        credit_limit=5000,
        current_balance=0,
        available_credit=5000,
        is_active=True,
    )
    purchase = CreditCardTransaction(
        family_id=family.id,
        credit_card=card,
        date=date.today(),
        transaction_type='Purchase',
        item='Toy shop',
        amount=Decimal('-64.99'),
    )
    plan = Plan(family_id=family.id, title='Christmas')
    plan.items = [PlanItem(
        family_id=family.id,
        title='Scooter',
        actual_cost=Decimal('50.00'),
        credit_card_transaction=purchase,
    )]
    db.session.add(plan)
    db.session.commit()

    assert plan.items[0].resolved_actual_cost == Decimal('64.99')
    assert plan.actual_total == Decimal('64.99')


def test_create_plan_and_add_item(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.post('/plans/add', data={
        'title': 'Christmas 2026',
        'plan_type': 'occasion',
        'person': 'The kids',
        'target_date': '2026-12-25',
        'target_amount': '500.00',
    })
    plan = Plan.query.one()

    assert response.status_code == 302
    assert response.headers['Location'].endswith(f'/plans/{plan.id}')

    response = client.post(f'/plans/{plan.id}/items/add', data={
        'title': 'Bike',
        'assigned_to': user.name,
        'estimated_cost': '150.00',
        'actual_cost': '140.00',
        'status': 'purchased',
        'priority': 'high',
    })

    assert response.status_code == 302
    assert PlanItem.query.one().resolved_actual_cost == Decimal('140.00')
    assert PlanItem.query.one().assigned_to == user.name


def test_add_item_rejects_unknown_assignee(app, family, user):
    plan = Plan(family_id=family.id, title='Christmas')
    db.session.add(plan)
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/plans/{plan.id}/items/add', data={
        'title': 'Private gift',
        'assigned_to': 'Someone from another family',
        'status': 'idea',
        'priority': 'normal',
    })

    assert response.status_code == 302
    assert PlanItem.query.count() == 0


def test_cannot_link_another_familys_transaction(app, family, user):
    from models.family import Family

    other_family = Family(name='Other Family')
    category = Category(
        family_id=family.id,
        name='Gifts',
        category_type='expense',
        head_budget='Lifestyle',
        sub_budget='Gifts',
    )
    plan = Plan(family_id=family.id, title='Birthday')
    db.session.add_all([other_family, category, plan])
    db.session.flush()
    transaction = Transaction(
        family_id=other_family.id,
        category_id=category.id,
        amount=Decimal('-25.00'),
        transaction_date=date.today(),
    )
    db.session.add(transaction)
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/plans/{plan.id}/items/add', data={
        'title': 'Headphones',
        'transaction_id': str(transaction.id),
        'status': 'idea',
        'priority': 'normal',
    })

    assert response.status_code == 302
    assert PlanItem.query.count() == 0


def test_plan_overview_and_detail_render(app, family, user):
    plan = Plan(
        family_id=family.id,
        title='Holiday fund',
        plan_type='savings_goal',
        target_amount=Decimal('1000.00'),
        saved_amount=Decimal('250.00'),
    )
    db.session.add(plan)
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    overview = client.get('/plans')
    detail = client.get(f'/plans/{plan.id}')

    assert overview.status_code == 200
    assert b'Holiday fund' in overview.data
    assert detail.status_code == 200
    assert b'25%' in detail.data


def test_link_transaction_from_transaction_page_can_create_and_unlink_item(app, family, user):
    category = Category(
        family_id=family.id,
        name='Gifts',
        category_type='expense',
        head_budget='Lifestyle',
        sub_budget='Gifts',
    )
    transaction = Transaction(
        family_id=family.id,
        category=category,
        amount=Decimal('-39.95'),
        transaction_date=date.today(),
        description='Toy shop',
        assigned_to=user.name,
    )
    plan = Plan(family_id=family.id, title='Christmas')
    db.session.add_all([transaction, plan])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/plans/transactions/{transaction.id}/link', data={
        'plan_id': str(plan.id),
        'new_item_title': 'Train set',
    })
    item = PlanItem.query.one()

    assert response.status_code == 302
    assert item.transaction_id == transaction.id
    assert item.status == 'purchased'
    assert item.estimated_cost == Decimal('39.95')
    assert item.assigned_to == user.name

    response = client.post(f'/plans/transactions/{transaction.id}/link', data={})

    assert response.status_code == 302
    assert item.transaction_id is None


def test_link_transaction_rejects_another_familys_plan_item(app, family, user):
    from models.family import Family

    other_family = Family(name='Other Family')
    category = Category(
        family_id=family.id,
        name='Gifts',
        category_type='expense',
        head_budget='Lifestyle',
        sub_budget='Gifts',
    )
    transaction = Transaction(
        family_id=family.id,
        category=category,
        amount=Decimal('-20.00'),
        transaction_date=date.today(),
    )
    foreign_plan = Plan(family_id=1, title='Placeholder')
    db.session.add_all([other_family, transaction])
    db.session.flush()
    foreign_plan.family_id = other_family.id
    foreign_item = PlanItem(family_id=other_family.id, plan=foreign_plan, title='Private item')
    db.session.add(foreign_plan)
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/plans/transactions/{transaction.id}/link', data={
        'item_id': str(foreign_item.id),
    })

    assert response.status_code == 404
    assert foreign_item.transaction_id is None


def test_transaction_index_renders_plan_link_action_and_existing_link(app, family, user):
    category = Category(
        family_id=family.id,
        name='Gifts',
        category_type='expense',
        head_budget='Lifestyle',
        sub_budget='Gifts',
    )
    transaction = Transaction(
        family_id=family.id,
        category=category,
        amount=Decimal('-18.00'),
        transaction_date=date.today(),
        description='Book shop',
    )
    plan = Plan(family_id=family.id, title='Birthday')
    item = PlanItem(family_id=family.id, plan=plan, title='Books', transaction=transaction)
    db.session.add_all([transaction, plan, item])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/transactions?is_paid=pending')

    assert response.status_code == 200
    assert b'linkPlanModal' in response.data
    assert b'Birthday' in response.data
    assert b'Books' in response.data


def test_transaction_search_only_returns_current_family_matches(app, family, user):
    from models.family import Family

    category = Category(
        family_id=family.id,
        name='Gifts',
        category_type='expense',
        head_budget='Lifestyle',
        sub_budget='Gifts',
    )
    other_family = Family(name='Other Family')
    db.session.add_all([category, other_family])
    db.session.flush()
    db.session.add_all([
        Transaction(
            family_id=family.id,
            category=category,
            amount=Decimal('-10.00'),
            transaction_date=date.today(),
            description='Unique toy shop',
        ),
        Transaction(
            family_id=other_family.id,
            category=category,
            amount=Decimal('-99.00'),
            transaction_date=date.today(),
            description='Unique private purchase',
        ),
    ])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/plans/api/transactions?q=Unique')
    results = response.get_json()

    assert response.status_code == 200
    assert len(results) == 1
    assert 'toy shop' in results[0]['label']


def test_transaction_search_excludes_forecasts_and_income_and_matches_amount(app, family, user):
    category = Category(
        family_id=family.id,
        name='Gifts',
        category_type='expense',
        head_budget='Lifestyle',
        sub_budget='Gifts',
    )
    db.session.add(category)
    db.session.flush()
    db.session.add_all([
        Transaction(family_id=family.id, category=category, amount=Decimal('-42.50'), transaction_date=date.today(), description='Actual purchase', is_forecasted=False),
        Transaction(family_id=family.id, category=category, amount=Decimal('-42.50'), transaction_date=date.today(), description='Ten year forecast', is_forecasted=True),
        Transaction(family_id=family.id, category=category, amount=Decimal('42.50'), transaction_date=date.today(), description='Refund income', is_forecasted=False),
    ])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    empty_response = client.get('/plans/api/transactions')
    amount_response = client.get('/plans/api/transactions?q=42.50')

    assert empty_response.get_json() == []
    assert len(amount_response.get_json()) == 1
    assert 'Actual purchase' in amount_response.get_json()[0]['label']


def test_plan_transaction_search_returns_typed_bank_and_card_results(app, family, user):
    category = Category(family_id=family.id, name='Gifts', category_type='expense', head_budget='Lifestyle', sub_budget='Gifts')
    card = CreditCard(
        family_id=family.id, card_name='Rewards Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True,
    )
    bank_transaction = Transaction(family_id=family.id, category=category, amount=Decimal('-25.00'), transaction_date=date.today(), description='Shared search')
    card_transaction = CreditCardTransaction(family_id=family.id, credit_card=card, amount=Decimal('-30.00'), date=date.today(), transaction_type='Purchase', item='Shared search')
    db.session.add_all([category, card, bank_transaction, card_transaction])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    results = client.get('/plans/api/transactions?q=Shared').get_json()

    assert {result['id'] for result in results} == {
        f'bank:{bank_transaction.id}',
        f'card:{card_transaction.id}',
    }


def test_plan_item_can_link_card_transaction_from_plan_form(app, family, user):
    card = CreditCard(
        family_id=family.id, card_name='Rewards Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True,
    )
    card_transaction = CreditCardTransaction(family_id=family.id, credit_card=card, amount=Decimal('-30.00'), date=date.today(), transaction_type='Purchase', item='Toy shop')
    plan = Plan(family_id=family.id, title='Christmas')
    db.session.add_all([card, card_transaction, plan])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/plans/{plan.id}/items/add', data={
        'title': 'Train set', 'transaction_ref': f'card:{card_transaction.id}',
        'status': 'purchased', 'priority': 'normal',
    })
    item = PlanItem.query.one()

    assert response.status_code == 302
    assert item.credit_card_transaction_id == card_transaction.id
    assert item.transaction_id is None
    assert item.resolved_actual_cost == Decimal('30.00')


def test_savings_goal_adds_linked_contributions_to_opening_balance(family):
    category = Category(
        family_id=family.id,
        name='Transfers',
        category_type='expense',
        head_budget='Savings',
        sub_budget='Transfer',
    )
    contribution = Transaction(
        family_id=family.id,
        category=category,
        amount=Decimal('75.00'),
        transaction_date=date.today(),
        description='Transfer into savings',
    )
    plan = Plan(
        family_id=family.id,
        title='Emergency fund',
        plan_type='savings_goal',
        target_amount=Decimal('1000.00'),
        saved_amount=Decimal('125.00'),
    )
    plan.items = [PlanItem(
        family_id=family.id,
        title='September contribution',
        transaction=contribution,
        status='purchased',
    )]
    db.session.add(plan)
    db.session.commit()

    assert plan.actual_total == Decimal('75.00')
    assert plan.saved_total == Decimal('200.00')
    assert plan.progress_percent == 20


def test_savings_transaction_search_includes_incoming_transfer(app, family, user):
    category = Category(
        family_id=family.id,
        name='Transfers',
        category_type='income',
        head_budget='Savings',
        sub_budget='Transfer',
    )
    db.session.add(Transaction(
        family_id=family.id,
        category=category,
        amount=Decimal('90.00'),
        transaction_date=date.today(),
        description='Goal contribution',
        is_forecasted=False,
    ))
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    ordinary_results = client.get('/plans/api/transactions?q=Goal').get_json()
    savings_results = client.get('/plans/api/transactions?plan_type=savings_goal&q=Goal').get_json()

    assert ordinary_results == []
    assert len(savings_results) == 1
    assert '+£90.00' in savings_results[0]['label']