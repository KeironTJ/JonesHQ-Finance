"""
Create `ExpenseCalendarEntry` rows from existing `Expense` records.
Usage:
    python -m scripts.maintenance.migrate_expenses_to_calendar

This creates one calendar entry per Expense using the Expense.date, total_cost and description.
If an Expense already has a linked calendar entry (via `expense.calendar_entries`), it will be skipped.
"""
from app import create_app
from extensions import db
from models.expense_calendar import ExpenseCalendarEntry
from models.expenses import Expense


def main():
    app = create_app()
    app.app_context().push()

    created = 0
    skipped = 0
    for exp in Expense.query.order_by(Expense.date).all():
        if exp.calendar_entries:
            skipped += 1
            continue
        entry = ExpenseCalendarEntry(
            date=exp.date,
            assigned_to=None,
            expense_id=exp.id,
            amount=exp.total_cost,
            description=exp.description
        )
        db.session.add(entry)
        created += 1

    db.session.commit()
    print(f'Created {created} calendar entries, skipped {skipped} existing')


if __name__ == '__main__':
    main()
