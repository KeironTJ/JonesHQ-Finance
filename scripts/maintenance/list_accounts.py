from app import create_app
from models.accounts import Account
app = create_app()
app.app_context().push()
for a in Account.query.order_by(Account.name).all():
    print(a.id, a.name)
