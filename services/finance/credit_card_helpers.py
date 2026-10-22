from extensions import db
from models.accounts import Account
from models.vendors import Vendor
from utils import db_helpers
from utils.db_helpers import family_get, family_query


def get_or_create_card_vendor(card):
    vendor = family_query(Vendor).filter_by(name=card.card_name).first()
    if not vendor:
        vendor = Vendor(
            family_id=db_helpers.get_family_id(),
            name=card.card_name,
        )
        db.session.add(vendor)
        db.session.flush()
    return vendor


def get_or_create_payment_vendor(card, account_id=None):
    account = family_get(Account, account_id) if account_id else None
    if not account:
        return get_or_create_card_vendor(card)

    vendor = family_query(Vendor).filter_by(name=account.name).first()
    if not vendor:
        vendor = Vendor(
            family_id=db_helpers.get_family_id(),
            name=account.name,
        )
        db.session.add(vendor)
        db.session.flush()
    return vendor
