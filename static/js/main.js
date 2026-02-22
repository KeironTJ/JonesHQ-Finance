// JonesHQ Finance — Main JS

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
