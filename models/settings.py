from extensions import db
from datetime import datetime, timezone


class Settings(db.Model):
    """Application settings and preferences"""
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.String(500))
    description = db.Column(db.String(255))
    setting_type = db.Column(db.String(50))  # 'int', 'float', 'string', 'boolean', 'date'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    @staticmethod
    def get_value(key, default=None):
        """Get a setting value by key"""
        from utils.db_helpers import get_family_id

        setting = Settings.query.filter_by(
            key=key,
            family_id=get_family_id(),
        ).first()
        if not setting:
            return default
        
        # Convert based on type
        if setting.setting_type == 'int':
            return int(setting.value)
        elif setting.setting_type == 'float':
            return float(setting.value)
        elif setting.setting_type == 'boolean':
            return setting.value.lower() in ('true', '1', 'yes')
        else:
            return setting.value
    
    @staticmethod
    def set_value(key, value, description=None, setting_type='string'):
        """Set a setting value"""
        from utils.db_helpers import get_family_id

        family_id = get_family_id()
        setting = Settings.query.filter_by(key=key, family_id=family_id).first()
        if setting:
            setting.value = str(value)
            setting.description = description or setting.description
            setting.setting_type = setting_type
            setting.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            setting = Settings(
                family_id=family_id,
                key=key,
                value=str(value),
                description=description,
                setting_type=setting_type
            )
            db.session.add(setting)
        return setting
