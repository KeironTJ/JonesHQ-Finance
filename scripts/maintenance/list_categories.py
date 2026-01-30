from app import create_app
from models.categories import Category
app = create_app()
app.app_context().push()
for c in Category.query.order_by(Category.head_budget, Category.sub_budget).all():
    print(c.id, c.head_budget, c.sub_budget, c.name)
