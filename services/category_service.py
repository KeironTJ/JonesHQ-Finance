from datetime import datetime, timezone

from extensions import db
from models.categories import Category
from models.transactions import Transaction
from utils import db_helpers
from utils.db_helpers import family_get_or_404, family_query


class CategoryService:
    @staticmethod
    def get_categories_by_head():
        head_budgets = family_query(Category).with_entities(
            Category.head_budget
        ).distinct().order_by(Category.head_budget).all()

        categories_by_head = {}
        for (head_budget,) in head_budgets:
            categories = family_query(Category).filter_by(
                head_budget=head_budget
            ).order_by(Category.sub_budget).all()
            for category in categories:
                category.transaction_count = family_query(Transaction).filter_by(
                    category_id=category.id
                ).count()

            categories_by_head[head_budget] = {
                'categories': categories,
                'total_count': sum(
                    category.transaction_count for category in categories
                ),
            }

        return dict(sorted(
            categories_by_head.items(),
            key=lambda item: item[1]['total_count'],
            reverse=True,
        ))

    @staticmethod
    def get_existing_heads():
        head_budgets = family_query(Category).with_entities(
            Category.head_budget
        ).distinct().order_by(Category.head_budget).all()
        return [head_budget[0] for head_budget in head_budgets]

    @staticmethod
    def find_conflict(head_budget, sub_budget, exclude_id=None):
        query = family_query(Category).filter_by(
            head_budget=head_budget,
            sub_budget=sub_budget or None,
        )
        if exclude_id is not None:
            query = query.filter(Category.id != exclude_id)
        return query.first()

    @staticmethod
    def create_category(head_budget, sub_budget, category_type):
        normalized_sub_budget = sub_budget or None
        name = head_budget + (f' - {normalized_sub_budget}' if normalized_sub_budget else '')
        category = Category(
            family_id=db_helpers.get_family_id(),
            name=name,
            head_budget=head_budget,
            sub_budget=normalized_sub_budget,
            category_type=category_type,
        )
        db.session.add(category)
        db.session.commit()
        return category

    @staticmethod
    def update_category(category_id, head_budget, sub_budget, category_type):
        category = family_get_or_404(Category, category_id)
        normalized_sub_budget = sub_budget or None
        category.head_budget = head_budget
        category.sub_budget = normalized_sub_budget
        category.category_type = category_type
        category.name = head_budget + (
            f' - {normalized_sub_budget}' if normalized_sub_budget else ''
        )
        category.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        return category

    @staticmethod
    def delete_category(category_id):
        category = family_get_or_404(Category, category_id)
        if category.transactions:
            return {'deleted': False, 'name': category.name, 'reason': 'transactions', 'count': len(category.transactions)}
        if category.budgets:
            return {'deleted': False, 'name': category.name, 'reason': 'budgets', 'count': len(category.budgets)}

        name = category.name
        db.session.delete(category)
        db.session.commit()
        return {'deleted': True, 'name': name}

    @staticmethod
    def get_subcategories(head_budget):
        categories = family_query(Category).filter_by(head_budget=head_budget).all()
        return [category.sub_budget for category in categories if category.sub_budget]
