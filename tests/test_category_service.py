from extensions import db
from models.categories import Category
from services.finance.category_service import CategoryService


def test_create_category_assigns_family_and_builds_name(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    category = CategoryService.create_category('Home', 'Rent', 'expense')

    assert category.family_id == family.id
    assert category.name == 'Home - Rent'
    assert category.sub_budget == 'Rent'


def test_category_conflict_excludes_category_being_edited(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    category = Category(
        family_id=family.id,
        name='Home - Rent',
        head_budget='Home',
        sub_budget='Rent',
        category_type='expense',
    )
    db.session.add(category)
    db.session.commit()

    assert CategoryService.find_conflict('Home', 'Rent') is category
    assert CategoryService.find_conflict('Home', 'Rent', exclude_id=category.id) is None


def test_update_and_delete_unused_category(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    category = Category(
        family_id=family.id,
        name='Old',
        head_budget='Old',
        sub_budget=None,
        category_type='expense',
    )
    db.session.add(category)
    db.session.commit()

    updated = CategoryService.update_category(category.id, 'New', '', 'income')
    result = CategoryService.delete_category(category.id)

    assert updated.name == 'New'
    assert updated.sub_budget is None
    assert updated.category_type == 'income'
    assert result == {'deleted': True, 'name': 'New'}
    assert db.session.get(Category, category.id) is None
