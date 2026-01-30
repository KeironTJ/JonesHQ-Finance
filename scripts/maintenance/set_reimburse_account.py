from app import create_app
from models.accounts import Account
from models.settings import Settings
app = create_app()
app.app_context().push()

# Find Nationwide Current Account
acc = Account.query.filter(Account.name.ilike('%Nationwide Current Account%')).first()
if not acc:
    # fallback: exact match
    acc = Account.query.filter_by(name='Nationwide Current Account').first()
if not acc:
    print('Could not find Nationwide Current Account')
else:
    Settings.set_value('expenses.reimburse_account_id', acc.id, description='Account used for expense reimbursements', setting_type='int')
    from extensions import db
    db.session.commit()
    print('Set expenses.reimburse_account_id to', acc.id)
