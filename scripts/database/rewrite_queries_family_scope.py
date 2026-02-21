"""
One-time script: rewrite all .query. calls in blueprints/ and services/
to use the family-scoped helpers in utils/db_helpers.py.

Run from project root:
    python scripts/database/rewrite_queries_family_scope.py

The script modifies files in-place. Run git diff / review changes before committing.
"""
import os
import re
import sys

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# These directories contain files to rewrite
TARGET_DIRS = [
    os.path.join(PROJECT_ROOT, 'blueprints'),
    os.path.join(PROJECT_ROOT, 'services'),
]

# Models that must NOT be family-scoped (auth/family models)
SKIP_MODELS = {'User', 'Family', 'FamilyInvite'}

# The import line we'll ensure is present at the top of each changed file
HELPER_IMPORT = 'from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id'


# ── Helper ────────────────────────────────────────────────────────────────────

def should_scope(model_name):
    return model_name not in SKIP_MODELS


def make_replacer():
    """Return a list of (pattern, replacement_fn) tuples, applied in order."""
    rules = []

    # 1. Model.query.get_or_404(...)  →  family_get_or_404(Model, ...)
    def sub_get_or_404(m):
        model = m.group(1)
        arg = m.group(2)
        if should_scope(model):
            return f'family_get_or_404({model}, {arg})'
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.get_or_404\(([^)]+)\)'), sub_get_or_404))

    # 2. Model.query.get(...)  →  family_get(Model, ...)
    #    (but not Model.query.get_or_404 – already handled above)
    def sub_get(m):
        model = m.group(1)
        arg = m.group(2)
        if should_scope(model):
            return f'family_get({model}, {arg})'
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.get\(([^)]+)\)'), sub_get))

    # 3. Model.query.all()  →  family_query(Model).all()
    def sub_all(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).all()'
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.all\(\)'), sub_all))

    # 4. Model.query.count()  →  family_query(Model).count()
    def sub_count(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).count()'
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.count\(\)'), sub_count))

    # 5. Model.query.filter_by(  →  family_query(Model).filter_by(
    def sub_filter_by(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).filter_by('
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.filter_by\('), sub_filter_by))

    # 6. Model.query.filter(  →  family_query(Model).filter(
    def sub_filter(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).filter('
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.filter\('), sub_filter))

    # 7. Model.query.order_by(  →  family_query(Model).order_by(
    def sub_order_by(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).order_by('
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.order_by\('), sub_order_by))

    # 8. Model.query.options(  →  family_query(Model).options(
    def sub_options(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).options('
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.options\('), sub_options))

    # 9. Model.query.join(  →  family_query(Model).join(
    def sub_join(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).join('
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.join\('), sub_join))

    # 10. Model.query.distinct()  →  family_query(Model).distinct()
    def sub_distinct(m):
        model = m.group(1)
        if should_scope(model):
            return f'family_query({model}).distinct()'
        return m.group(0)
    rules.append((re.compile(r'(\w+)\.query\.distinct\(\)'), sub_distinct))

    return rules


def rewrite_file(path, rules, dry_run=False):
    with open(path, 'r', encoding='utf-8') as f:
        original = f.read()

    content = original
    for pattern, replacement in rules:
        content = pattern.sub(replacement, content)

    if content == original:
        return False  # no changes

    # Ensure the helper import is present
    if HELPER_IMPORT not in content:
        # Insert after the last 'from ...' / 'import ...' block at the top
        lines = content.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith(('import ', 'from ')):
                insert_at = i + 1
        lines.insert(insert_at, HELPER_IMPORT + '\n')
        content = ''.join(lines)

    if not dry_run:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    dry_run = '--dry-run' in sys.argv
    rules = make_replacer()
    changed = []
    skipped = []

    for target_dir in TARGET_DIRS:
        for dirpath, _, filenames in os.walk(target_dir):
            for filename in filenames:
                if not filename.endswith('.py'):
                    continue
                filepath = os.path.join(dirpath, filename)
                rel = os.path.relpath(filepath, PROJECT_ROOT)
                modified = rewrite_file(filepath, rules, dry_run=dry_run)
                if modified:
                    changed.append(rel)
                    print(f'  ✓ {rel}')
                else:
                    skipped.append(rel)

    print(f'\n{"(DRY RUN) " if dry_run else ""}Modified {len(changed)} file(s), '
          f'{len(skipped)} unchanged.')


if __name__ == '__main__':
    main()
