// Family HQ — Main JS

// ── Theme Manager ─────────────────────────────────────────────────────────────
const ThemeManager = (function () {
    const STORAGE_KEY = 'jhq-theme';
    const THEMES = { LIGHT: 'light', DARK: 'dark', AUTO: 'auto' };

    function getStored() {
        return localStorage.getItem(STORAGE_KEY) || THEMES.LIGHT;
    }

    function getResolved(stored) {
        if (stored === THEMES.AUTO) {
            return window.matchMedia('(prefers-color-scheme: dark)').matches
                ? THEMES.DARK : THEMES.LIGHT;
        }
        return stored;
    }

    function apply(stored) {
        const resolved = getResolved(stored);
        document.documentElement.setAttribute('data-theme', resolved);
        updateToggleIcons(resolved, stored);

        // Update Chart.js defaults if charts are present
        if (window.updateChartTheme) window.updateChartTheme(resolved);
    }

    function updateToggleIcons(resolved, stored) {
        const isDark = resolved === THEMES.DARK;
        const icons = [
            { btn: document.getElementById('themeToggleBtn'),    icon: document.getElementById('themeIcon') },
            { btn: document.getElementById('themeToggleBtnMobile'), icon: document.getElementById('themeIconMobile') },
        ];
        icons.forEach(({ icon }) => {
            if (!icon) return;
            icon.className = isDark ? 'bi bi-moon-stars-fill' : 'bi bi-sun-fill';
        });

        const lbl = document.getElementById('themeLabel');
        if (lbl) {
            lbl.textContent = stored === THEMES.AUTO
                ? 'Auto (' + (isDark ? 'Dark' : 'Light') + ')'
                : (isDark ? 'Dark Mode' : 'Light Mode');
        }
    }

    function cycle() {
        // Simple toggle: light ↔ dark (auto is set explicitly via Settings only)
        const current = getResolved(getStored());
        const next = current === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK;
        localStorage.setItem(STORAGE_KEY, next);
        apply(next);
    }

    function setTheme(theme) {
        if (!Object.values(THEMES).includes(theme)) return;
        localStorage.setItem(STORAGE_KEY, theme);
        apply(theme);
    }

    function init() {
        const stored = getStored();
        apply(stored);

        // Desktop toggle
        const btn = document.getElementById('themeToggleBtn');
        if (btn) btn.addEventListener('click', cycle);

        // Mobile toggle
        const btnMobile = document.getElementById('themeToggleBtnMobile');
        if (btnMobile) btnMobile.addEventListener('click', cycle);

        // Settings radio buttons (if present)
        document.querySelectorAll('[name="jhq-theme-radio"]').forEach(radio => {
            radio.addEventListener('change', () => setTheme(radio.value));
            radio.checked = radio.value === stored;
        });

        // Listen for system preference changes (auto mode)
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            if (getStored() === THEMES.AUTO) apply(THEMES.AUTO);
        });
    }

    return { init, setTheme, getStored, getResolved, THEMES };
})();

async function savePersonalPreference(toggle, url, key, headers) {
    const value = toggle.checked;
    toggle.disabled = true;
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers,
            body: JSON.stringify({ key, value }),
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            throw new Error(result.error || 'Unable to save your preference. Please try again.');
        }
    } catch (error) {
        toggle.checked = !value;
        window.alert(error.message || 'Unable to save your preference. Please try again.');
    } finally {
        toggle.disabled = false;
    }
}

// ── Chart.js Theme Integration ────────────────────────────────────────────────
window.updateChartTheme = function (theme) {
    if (typeof Chart === 'undefined') return;
    const isDark = theme === 'dark';
    const textColor   = isDark ? '#8b949e' : '#475569';
    const gridColor   = isDark ? '#30363d' : '#e2e8f0';
    const bgColor     = isDark ? '#161b22' : '#ffffff';

    Chart.defaults.color            = textColor;
    Chart.defaults.borderColor      = gridColor;
    Chart.defaults.backgroundColor  = bgColor;

    if (Chart.defaults.scales) {
        ['x', 'y', 'r'].forEach(axis => {
            if (Chart.defaults.scales[axis]) {
                if (Chart.defaults.scales[axis].grid)  Chart.defaults.scales[axis].grid.color  = gridColor;
                if (Chart.defaults.scales[axis].ticks) Chart.defaults.scales[axis].ticks.color = textColor;
            }
        });
    }

    // Update all existing chart instances
    Object.values(Chart.instances || {}).forEach(chart => {
        if (chart.options.scales) {
            Object.values(chart.options.scales).forEach(scale => {
                if (scale.grid)  scale.grid.color  = gridColor;
                if (scale.ticks) scale.ticks.color = textColor;
                if (scale.title) scale.title.color = textColor;
            });
        }
        if (chart.options.plugins) {
            if (chart.options.plugins.legend && chart.options.plugins.legend.labels) {
                chart.options.plugins.legend.labels.color = textColor;
            }
            if (chart.options.plugins.tooltip) {
                chart.options.plugins.tooltip.backgroundColor = isDark ? '#1c2128' : '#ffffff';
                chart.options.plugins.tooltip.titleColor      = isDark ? '#e6edf3' : '#0f172a';
                chart.options.plugins.tooltip.bodyColor       = isDark ? '#8b949e' : '#475569';
                chart.options.plugins.tooltip.borderColor     = gridColor;
                chart.options.plugins.tooltip.borderWidth     = 1;
            }
        }
        chart.update('none');
    });
};

document.addEventListener('DOMContentLoaded', function () {
    ThemeManager.init();

    // ── Modal stacking-context fix ────────────────────────────────────────────
    // Bootstrap appends its backdrop to <body> (z-index 1040) but leaves the
    // .modal element wherever it sits in the DOM.  If any ancestor has a CSS
    // stacking context (e.g. from an opacity or transform animation) the modal
    // dialog's z-index becomes local to that context, rendering the backdrop
    // visually on top of the dialog and blocking all pointer events.
    // Relocating every .modal to <body> avoids this entirely.
    document.querySelectorAll('.modal').forEach(function (modal) {
        if (modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
    });

    // ── Mobile navbar close-on-click-outside & link-click ────────────────────
    const navCollapse = document.getElementById('navbarNav');
    const toggler = document.querySelector('.navbar-toggler');

    if (navCollapse && toggler) {
        function isMobileNav() {
            return window.getComputedStyle(toggler).display !== 'none';
        }

        function closeNav() {
            if (navCollapse.classList.contains('show')) {
                const bsCollapse = bootstrap.Collapse.getInstance(navCollapse) ||
                    new bootstrap.Collapse(navCollapse, { toggle: false });
                bsCollapse.hide();
            }
        }

        // Close when clicking off the menu (outside navbar collapse and toggler)
        document.addEventListener('click', function (event) {
            if (!isMobileNav()) return;
            if (!navCollapse.classList.contains('show')) return;

            if (!navCollapse.contains(event.target) && !toggler.contains(event.target)) {
                closeNav();
                return;
            }

            const navLink = event.target.closest('a.nav-link:not(.dropdown-toggle), a.dropdown-item');
            if (navLink && navCollapse.contains(navLink)) {
                closeNav();
            }
        });

        // Close on Escape key press
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && isMobileNav() && navCollapse.classList.contains('show')) {
                closeNav();
            }
        });

        // Clean up open dropdown menus and body state when the mobile navbar closes
        navCollapse.addEventListener('hide.bs.collapse', function () {
            document.body.classList.remove('mobile-nav-open');
            navCollapse.querySelectorAll('.dropdown-toggle[aria-expanded="true"]').forEach(function (toggle) {
                const bsDropdown = bootstrap.Dropdown.getInstance(toggle);
                if (bsDropdown) {
                    bsDropdown.hide();
                } else {
                    toggle.setAttribute('aria-expanded', 'false');
                    toggle.classList.remove('show');
                    const menu = toggle.nextElementSibling;
                    if (menu && menu.classList.contains('dropdown-menu')) {
                        menu.classList.remove('show');
                    }
                }
            });
        });

        navCollapse.addEventListener('shown.bs.collapse', function () {
            document.body.classList.add('mobile-nav-open');
        });

        navCollapse.addEventListener('hidden.bs.collapse', function () {
            document.body.classList.remove('mobile-nav-open');
        });

        window.addEventListener('resize', function () {
            if (!isMobileNav() && navCollapse.classList.contains('show')) {
                const bsCollapse = bootstrap.Collapse.getInstance(navCollapse);
                if (bsCollapse) {
                    bsCollapse.hide();
                } else {
                    navCollapse.classList.remove('show');
                }
                document.body.classList.remove('mobile-nav-open');
            }
        });
    }
});

// Helper function to format currency
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-GB', {
        style: 'currency',
        currency: 'GBP'
    }).format(amount);
}

// Helper function to format dates
function formatDate(date) {
    return new Intl.DateTimeFormat('en-GB').format(new Date(date));
}

// Global helpers used by Fuel/Trip pages for consistent period/vehicle filter behavior
function changePaydayPeriodFrom(selectId) {
    const sel = document.getElementById(selectId);
    if (sel && sel.form) sel.form.submit();
}

function changePeriodBy(selectId, offset) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    
    // Get current selected index
    let currentIndex = sel.selectedIndex;
    
    // If "All Periods" is selected (index 0), start from first actual period
    if (currentIndex === 0 || !sel.value) {
        currentIndex = offset > 0 ? 0 : sel.options.length - 1;
    }
    
    // Calculate new index
    let newIndex = currentIndex + offset;
    
    // Clamp to valid range (skip index 0 which is "All Periods")
    if (newIndex < 1) newIndex = 1;
    if (newIndex >= sel.options.length) newIndex = sel.options.length - 1;
    
    // Set new value and submit
    if (sel.options[newIndex]) {
        sel.selectedIndex = newIndex;
        if (sel.form) sel.form.submit();
    }
}

function changeVehicleFilter(selectId) {
    const sel = document.getElementById(selectId);
    if (sel && sel.form) sel.form.submit();
}

function jumpToCurrentPeriod(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    
    // Get today's date
    const today = new Date();
    const currentYear = today.getFullYear();
    const currentMonth = String(today.getMonth() + 1).padStart(2, '0');
    const currentPeriod = `${currentYear}-${currentMonth}`;
    
    // Try to find the current period in the dropdown
    for (let i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === currentPeriod) {
            sel.selectedIndex = i;
            if (sel.form) sel.form.submit();
            return;
        }
    }
    
    // If exact match not found, select the first non-"All" option (most recent)
    if (sel.options.length > 1) {
        sel.selectedIndex = 1;
        if (sel.form) sel.form.submit();
    }
}

function changeYear(year) {
    const urlParams = new URLSearchParams(window.location.search);
    urlParams.set('year', year);
    window.location.search = urlParams.toString();
}
