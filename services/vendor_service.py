from datetime import datetime, timezone

from extensions import db
from models.vendors import Vendor, VendorType
from models.transactions import Transaction
from sqlalchemy import func
from utils.db_helpers import family_get_or_404, family_query, get_family_id


DEFAULT_VENDOR_TYPES = [
    'Grocery', 'Fuel', 'Restaurant', 'Online Retailer',
    'Utility', 'Insurance', 'Bank', 'Government',
    'Entertainment', 'Healthcare', 'Education', 'Other',
]


class VendorService:
    @staticmethod
    def list_vendors(vendor_type=None, search=None, sort_by='usage'):
        query = family_query(Vendor)
        if vendor_type:
            if vendor_type.lower() == 'uncategorized':
                query = query.filter(Vendor.vendor_type_id.is_(None))
            else:
                query = query.join(VendorType, isouter=True).filter(
                    func.lower(VendorType.name) == vendor_type.lower()
                )
        if search:
            query = query.filter(Vendor.name.ilike(f'%{search}%'))

        vendors = query.all()
        for vendor in vendors:
            vendor.transaction_count = family_query(Transaction).filter_by(
                vendor_id=vendor.id
            ).count()
        if sort_by == 'usage':
            vendors.sort(key=lambda vendor: vendor.transaction_count, reverse=True)
        elif sort_by == 'name':
            vendors.sort(key=lambda vendor: vendor.name.lower())
        return vendors

    @staticmethod
    def list_types():
        return family_query(VendorType).order_by(
            VendorType.sort_order.nulls_last(), VendorType.name
        ).all()

    @staticmethod
    def type_counts(vendor_types):
        return {
            vendor_type.id: family_query(Vendor).filter_by(
                vendor_type_id=vendor_type.id
            ).count()
            for vendor_type in vendor_types
        }

    @staticmethod
    def create_type(name, sort_order, is_active):
        vendor_type = VendorType(
            family_id=get_family_id(),
            name=name,
            is_active=is_active,
            sort_order=sort_order,
        )
        db.session.add(vendor_type)
        db.session.commit()
        return vendor_type

    @staticmethod
    def find_type(name, exclude_id=None):
        query = family_query(VendorType).filter(
            func.lower(VendorType.name) == name.lower()
        )
        if exclude_id is not None:
            query = query.filter(VendorType.id != exclude_id)
        return query.first()

    @staticmethod
    def update_type(type_id, name, sort_order, is_active):
        vendor_type = family_get_or_404(VendorType, type_id)
        vendor_type.name = name
        vendor_type.is_active = is_active
        vendor_type.sort_order = sort_order
        db.session.commit()
        return vendor_type

    @staticmethod
    def delete_type(type_id):
        vendor_type = family_get_or_404(VendorType, type_id)
        usage_count = family_query(Vendor).filter_by(vendor_type_id=vendor_type.id).count()
        if usage_count:
            return {'deleted': False, 'name': vendor_type.name}
        name = vendor_type.name
        db.session.delete(vendor_type)
        db.session.commit()
        return {'deleted': True, 'name': name}

    @staticmethod
    def seed_types():
        if family_query(VendorType).count() > 0:
            return False
        for index, name in enumerate(DEFAULT_VENDOR_TYPES, start=1):
            db.session.add(VendorType(
                family_id=get_family_id(),
                name=name,
                is_active=True,
                sort_order=index,
            ))
        db.session.commit()
        return True

    @staticmethod
    def create_vendor(name, vendor_type, default_category_id, website, notes):
        vendor = Vendor(
            family_id=get_family_id(),
            name=name,
            vendor_type_id=int(vendor_type) if vendor_type else None,
            vendor_type=vendor_type if vendor_type else None,
            default_category_id=int(default_category_id) if default_category_id else None,
            website=website or None,
            notes=notes or None,
        )
        db.session.add(vendor)
        db.session.commit()
        return vendor

    @staticmethod
    def update_vendor(vendor_id, name, vendor_type, default_category_id, website, notes, is_active):
        vendor = family_get_or_404(Vendor, vendor_id)
        vendor.name = name
        vendor.vendor_type_id = int(vendor_type) if vendor_type else None
        vendor.vendor_type = vendor_type if vendor_type else None
        vendor.default_category_id = int(default_category_id) if default_category_id else None
        vendor.website = website or None
        vendor.notes = notes or None
        vendor.is_active = is_active
        vendor.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        return vendor

    @staticmethod
    def delete_vendor(vendor_id):
        vendor = family_get_or_404(Vendor, vendor_id)
        transaction_count = vendor.transactions.count()
        if transaction_count:
            return {'deleted': False, 'name': vendor.name, 'count': transaction_count}
        name = vendor.name
        db.session.delete(vendor)
        db.session.commit()
        return {'deleted': True, 'name': name}

    @staticmethod
    def quick_add(name):
        existing = family_query(Vendor).filter_by(name=name).first()
        if existing:
            return existing, True
        vendor = Vendor(family_id=get_family_id(), name=name)
        db.session.add(vendor)
        db.session.commit()
        return vendor, False
