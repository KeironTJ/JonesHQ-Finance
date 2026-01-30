from app import create_app
from models.settings import Settings
from models.accounts import Account
app = create_app()
app.app_context().push()
val = Settings.get_value('expenses.reimburse_account_id')
print('expenses.reimburse_account_id:', val)
if val:
    acc = Account.query.get(int(val))
    print('Account:', acc and acc.name)
else:
    print('No reimburse account set')
