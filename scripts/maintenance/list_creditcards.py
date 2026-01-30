from app import create_app
from models.credit_cards import CreditCard
app = create_app()
app.app_context().push()
for cc in CreditCard.query.order_by(CreditCard.card_name).all():
    print(cc.id, cc.card_name)
