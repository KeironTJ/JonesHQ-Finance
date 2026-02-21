"""
Migration: Add family / multi-user support
==========================================

Adds the ``families`` and ``family_invites`` tables and extends the
``users`` table with ``family_id``, ``role``, ``member_name``, and
``allowed_sections`` columns.

Also seeds a default Family and makes all existing users admins of it.

Usage
-----
Run from the project root while the virtual-env is active::

    python scripts/database/migrate_add_family.py

The script is idempotent – it checks whether each column / table already
exists before adding it, so it is safe to run more than once.
"""
import os
import sys

# ── Make sure the project root is on the path ─────────────────────────────────
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from sqlalchemy import text
from app import create_app
from extensions import db

app = create_app()


def column_exists(conn, table, column):
    result = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in result)


def table_exists(conn, table):
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table}
    ).fetchone()
    return result is not None


with app.app_context():
    with db.engine.connect() as conn:

        # ── 1. Create new tables via SQLAlchemy ────────────────────────────
        print("Creating new tables if they don't exist …")
        db.create_all()
        print("  ✓ families, family_invites (and all other missing tables) created.")

        # ── 2. Add new columns to users ────────────────────────────────────
        new_columns = {
            'family_id':        'INTEGER REFERENCES families(id)',
            'role':             "VARCHAR(20) NOT NULL DEFAULT 'admin'",
            'member_name':      'VARCHAR(100)',
            'allowed_sections': 'TEXT',
        }

        for col_name, col_def in new_columns.items():
            if not column_exists(conn, 'users', col_name):
                print(f"  Adding column users.{col_name} …")
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
            else:
                print(f"  Column users.{col_name} already exists, skipping.")

        conn.commit()

    # ── 3. Seed default family and assign existing admins ──────────────────
    from models.family import Family
    from models.users import User

    # Only seed if there are no families yet
    if Family.query.count() == 0:
        print("Creating default Family 'Jones HQ' …")
        family = Family(name='Jones HQ')
        db.session.add(family)
        db.session.flush()

        users = User.query.all()
        print(f"  Assigning {len(users)} existing user(s) as admin …")
        for user in users:
            user.family_id = family.id
            user.role = 'admin'
            user.member_name = user.member_name or user.name

        db.session.commit()
        print(f"  ✓ Family '{family.name}' created (id={family.id}).")
    else:
        print("Family records already exist – skipping seed.")

    print("\nMigration complete.")
