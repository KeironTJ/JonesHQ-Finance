"""
Write-time guard against cross-household references.

``family_query()`` stops one household *reading* another's rows, but a form can
still submit any integer as ``account_id``/``category_id``/etc. Without a check,
household A could save a record pointing at household B's account and then read
B's data back through the relationship. Rather than relying on every service to
validate every submitted ID, this ``before_flush`` hook rejects any new or changed
foreign key whose target row belongs to a different household.

Rows with ``family_id = NULL`` (on either side) are not checked. Platform/auth
tables whose rows legitimately follow a user between households are excluded.
"""
import logging

from flask import current_app, has_app_context
from sqlalchemy import and_, func, inspect, select


# Audit/auth tables that reference users across household moves (joining,
# leaving, deletion). They are not household financial data.
EXCLUDED_SOURCE_TABLES = frozenset({
    'users',
    'security_events',
    'family_invites',
    'household_invites',
    'user_sessions',
    'user_recovery_codes',
})


class CrossFamilyReferenceError(ValueError):
    """Raised when a record would reference another household's record."""

    def __init__(self, table_name, column_name):
        self.table_name = table_name
        self.column_name = column_name
        super().__init__('That selection is not available in your household.')


_REFERENCES = None


def family_references(db):
    """Return ``[(source_table, column, target_table, target_column)]`` for every
    foreign key between two household-scoped tables, excluding platform tables."""
    global _REFERENCES
    if _REFERENCES is None:
        references = []
        for table in db.metadata.sorted_tables:
            if table.name in EXCLUDED_SOURCE_TABLES or 'family_id' not in table.c:
                continue
            for column in table.c:
                if column.name == 'family_id':
                    continue
                for fk in column.foreign_keys:
                    target_table = fk.column.table
                    if 'family_id' in target_table.c:
                        references.append((table, column, target_table, fk.column))
        _REFERENCES = references
    return _REFERENCES


def _class_for_table(db, table):
    for mapper in db.Model.registry.mappers:
        if mapper.local_table is table:
            return mapper.class_
    return None


def _log_blocked(table_name, column_name):
    message = 'TENANCY_REFERENCE_BLOCKED table=%s column=%s'
    if has_app_context():
        current_app.logger.warning(message, table_name, column_name)
    else:
        logging.getLogger(__name__).warning(message, table_name, column_name)


def register_cross_family_guard(db):
    """Attach the guard to ``db.session``. Call once from the app factory."""
    from sqlalchemy import event

    by_source = {}
    for table, column, target_table, target_column in family_references(db):
        by_source.setdefault(table.name, []).append((column, target_table, target_column))
    class_cache = {}

    def target_class(target_table):
        if target_table.name not in class_cache:
            class_cache[target_table.name] = _class_for_table(db, target_table)
        return class_cache[target_table.name]

    @event.listens_for(db.session, 'before_flush')
    def _reject_cross_family_references(session, flush_context, instances):
        candidates = list(session.new) + [
            obj for obj in session.dirty if session.is_modified(obj, include_collections=False)
        ]
        if not candidates:
            return
        with session.no_autoflush:
            for obj in candidates:
                table = getattr(obj, '__table__', None)
                if table is None or table.name not in by_source:
                    continue
                family_id = getattr(obj, 'family_id', None)
                if family_id is None:
                    continue
                state = inspect(obj)
                mapper = state.mapper
                family_changed = (
                    not state.pending
                    and state.attrs[mapper.get_property_by_column(table.c.family_id).key]
                    .history.has_changes()
                )
                for column, target_table, target_column in by_source[table.name]:
                    key = mapper.get_property_by_column(column).key
                    if not state.pending and not family_changed:
                        if not state.attrs[key].history.has_changes():
                            continue
                    value = getattr(obj, key)
                    if value is None:
                        continue
                    target_family_id = _target_family_id(
                        session, target_class(target_table), target_table, target_column, value
                    )
                    if target_family_id is not None and target_family_id != family_id:
                        _log_blocked(table.name, column.name)
                        raise CrossFamilyReferenceError(table.name, column.name)

    return _reject_cross_family_references


def _target_family_id(session, target_cls, target_table, target_column, value):
    # Prefer the in-session object so unflushed changes are respected.
    if target_cls is not None and target_column.primary_key:
        target = session.get(target_cls, value)
        return getattr(target, 'family_id', None) if target is not None else None
    return session.execute(
        select(target_table.c.family_id).where(target_column == value)
    ).scalar()


def find_cross_family_references(db):
    """Read-only scan. Returns ``{'table.column': count}`` for existing rows that
    reference another household's row. Empty dict means no violations."""
    results = {}
    for table, column, target_table, target_column in family_references(db):
        target = target_table.alias('target')
        target_col = target.c[target_column.name]
        count = db.session.execute(
            select(func.count())
            .select_from(table.join(target, column == target_col))
            .where(and_(
                table.c.family_id.is_not(None),
                target.c.family_id.is_not(None),
                table.c.family_id != target.c.family_id,
            ))
        ).scalar()
        if count:
            results[f'{table.name}.{column.name}'] = count
    return results
