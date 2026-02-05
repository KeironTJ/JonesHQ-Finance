#!/bin/bash
#
# Find all JonesHQ Finance installations on the server
#

echo "========================================="
echo "  Finding JonesHQ Finance Installations"
echo "========================================="
echo ""

echo "1. Checking systemd service location..."
if [ -f /etc/systemd/system/joneshq-finance.service ]; then
    echo "✓ Service file found at: /etc/systemd/system/joneshq-finance.service"
    echo ""
    echo "Working directory from service file:"
    grep "WorkingDirectory=" /etc/systemd/system/joneshq-finance.service
    echo ""
    echo "ExecStart from service file:"
    grep "ExecStart=" /etc/systemd/system/joneshq-finance.service
    echo ""
else
    echo "✗ Service file not found"
fi

echo "2. Checking running processes..."
ps aux | grep -i gunicorn | grep -v grep
echo ""

echo "3. Searching for app.py files..."
find /home -name "app.py" -path "*/joneshq*" 2>/dev/null || find /home -name "app.py" 2>/dev/null
echo ""

echo "4. Searching for .git directories in /home..."
find /home -type d -name ".git" 2>/dev/null | while read gitdir; do
    repodir=$(dirname "$gitdir")
    echo "Found git repo: $repodir"
    cd "$repodir"
    echo "  Remote URL: $(git config --get remote.origin.url)"
    echo "  Current branch: $(git branch --show-current)"
    echo "  Last commit: $(git log -1 --oneline)"
    echo ""
done

echo "5. Expected location from deploy.sh:"
echo "  /home/joneshq/app"
if [ -d /home/joneshq/app ]; then
    echo "  ✓ Directory exists"
    cd /home/joneshq/app
    if [ -d .git ]; then
        echo "  ✓ Is a git repo"
        echo "  Branch: $(git branch --show-current)"
        echo "  Last commit: $(git log -1 --oneline)"
        echo "  Templates check:"
        if grep -q "csrf_token" templates/vendors/add.html 2>/dev/null; then
            echo "    ✓ CSRF tokens present in templates"
        else
            echo "    ✗ CSRF tokens NOT found in templates"
        fi
    else
        echo "  ✗ Not a git repo"
    fi
else
    echo "  ✗ Directory does not exist"
fi

echo ""
echo "========================================="
echo "To update the correct installation:"
echo "  cd /home/joneshq/app"
echo "  git pull origin main"
echo "  sudo systemctl restart joneshq-finance"
echo "========================================="
