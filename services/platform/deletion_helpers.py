from sqlalchemy import select

from extensions import db
from models import User


def deletion_references(plan, delete_order, allowed_family_detach=()):
    """Validate incoming links and select nullable references to detach before deletion."""
    references = []
    order = {table: index for index, table in enumerate(delete_order)}
    for table in db.metadata.tables.values():
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                target = foreign_key.column.table
                targets = plan.get(target, {})
                if not targets:
                    continue
                condition = column.in_(targets)
                deleting = plan.get(table, {})
                rows = db.session.execute(select(table).where(condition)).mappings().all()
                if not rows:
                    continue
                surviving = [row for row in rows if row['id'] not in deleting]
                if target != User.__table__:
                    for row in rows:
                        if column.name == 'family_id' and table in allowed_family_detach:
                            continue
                        if 'family_id' in row and row['family_id'] != targets[row[column.name]]:
                            raise ValueError('Linked household data is inconsistent. Contact the site administrator before deletion.')
                if not column.nullable:
                    if surviving:
                        raise ValueError('Linked records prevent safe account deletion. Contact the site administrator.')
                    continue
                if surviving and column.name == 'owner_id' and target == User.__table__:
                    raise ValueError('Private records require a reviewed deletion rule. Contact the site administrator.')
                if table in order and order[table] < order[target]:
                    # Subscriptions must retain their funding target until they are deleted.
                    condition &= table.c.id.not_in(deleting)
                references.append((table, column, condition))
    return references
