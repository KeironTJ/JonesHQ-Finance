# Branching Strategy - JonesHQ Finance

## Current Phase: Solo Development (Pre-Production)

### Simple Strategy (Current)
For now, you can commit directly to `main` since there's no production deployment.

```powershell
# Make changes, then commit
git add .
git commit -m "Your commit message"
git push origin main
```

---

## Future Strategy: When Production Deployed

### Branch Structure

```
main (production-ready code)
├── develop (integration branch)
│   ├── feature/transaction-import
│   ├── feature/budget-alerts
│   ├── bugfix/vendor-search
│   └── hotfix/critical-security-fix
```

### Branch Types

#### 1. `main` Branch
- **Purpose:** Production-ready code
- **Protected:** Yes (when deployed)
- **Deployment:** Auto-deploys to production
- **Rules:** Only merge from `develop` or `hotfix/*`

#### 2. `develop` Branch
- **Purpose:** Integration branch for features
- **Merges from:** `feature/*`, `bugfix/*`
- **Merges to:** `main` (via pull request)

#### 3. Feature Branches: `feature/*`
- **Naming:** `feature/vendor-autocomplete`, `feature/csv-import`
- **Branch from:** `develop`
- **Merge to:** `develop`

```powershell
# Create feature branch
git checkout develop
git pull origin develop
git checkout -b feature/vendor-autocomplete

# Work on feature...
git add .
git commit -m "feat: add vendor autocomplete to transaction form"

# Push and create PR
git push origin feature/vendor-autocomplete
```

#### 4. Bugfix Branches: `bugfix/*`
- **Naming:** `bugfix/vendor-search-crash`
- **Branch from:** `develop`
- **Merge to:** `develop`

```powershell
git checkout develop
git checkout -b bugfix/vendor-search-crash

# Fix bug...
git add .
git commit -m "fix: prevent crash when searching empty vendor list"
git push origin bugfix/vendor-search-crash
```

#### 5. Hotfix Branches: `hotfix/*`
- **Naming:** `hotfix/security-patch`
- **Branch from:** `main`
- **Merge to:** `main` AND `develop`
- **Use when:** Critical production bug needs immediate fix

```powershell
git checkout main
git checkout -b hotfix/security-patch

# Fix critical issue...
git add .
git commit -m "hotfix: patch SQL injection vulnerability"

# Merge to main
git checkout main
git merge hotfix/security-patch
git push origin main

# Also merge to develop
git checkout develop
git merge hotfix/security-patch
git push origin develop
```

---

## Commit Message Convention

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting, no logic change)
- `refactor:` Code refactoring
- `perf:` Performance improvements
- `test:` Adding/updating tests
- `chore:` Build process, dependencies, etc.

### Examples
```
feat(vendors): add vendor management interface
fix(transactions): correct running balance calculation
docs(readme): update installation instructions
chore(deps): upgrade Flask to 3.0.1
refactor(categories): simplify category lookup logic
```

---

## When to Switch to Full Strategy

Switch from simple `main`-only to full branching when:

1. **✅ First Production Deployment**
   - Users are accessing the live application
   - Downtime has impact

2. **✅ Multiple Developers**
   - Even one other person working on code
   - Need code review process

3. **✅ CI/CD Pipeline**
   - Automated testing
   - Automated deployments

4. **✅ Feature Experimentation**
   - Want to try major changes without affecting main code
   - Easy rollback needed

---

## Transition Plan

### Step 1: Create `develop` branch
```powershell
# From main, create develop
git checkout main
git checkout -b develop
git push origin develop
```

### Step 2: Set branch protection on GitHub
- Require pull request reviews for `main`
- Require status checks to pass
- No direct commits to `main`

### Step 3: Feature development workflow
```powershell
# Always start from develop
git checkout develop
git pull origin develop

# Create feature branch
git checkout -b feature/my-feature

# Work, commit, push
git add .
git commit -m "feat: my feature"
git push origin feature/my-feature

# Create PR on GitHub: feature/my-feature → develop
# After PR approved and merged, delete feature branch
git checkout develop
git pull origin develop
git branch -d feature/my-feature
```

### Step 4: Release workflow
```powershell
# When ready to release
git checkout develop
git pull origin develop

# Create PR on GitHub: develop → main
# After merge, tag the release
git checkout main
git pull origin main
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

---

## Quick Reference

### Current (Pre-Production)
```powershell
git add .
git commit -m "feat: description"
git push origin main
```

### Future (Production)
```powershell
# Feature
git checkout -b feature/name
# ... work ...
git push origin feature/name
# Create PR → develop

# Hotfix
git checkout -b hotfix/name
# ... fix ...
git push origin hotfix/name
# Create PR → main (and develop)
```

---

## Notes

- Keep branches short-lived (< 1 week if possible)
- Merge frequently to avoid conflicts
- Delete merged branches
- Use descriptive branch names
- Always pull before creating new branch
