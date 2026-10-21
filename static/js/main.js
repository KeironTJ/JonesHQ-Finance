// Family HQ — Main JS

// ── Theme Manager ─────────────────────────────────────────────────────────────
const ThemeManager = (function () {
    const STORAGE_KEY = 'jhq-theme';
    const THEMES = { LIGHT: 'light', DARK: 'dark', AUTO: 'auto' };
    const config = window.FinanceAppearance || { account: false, mode: 'light', palette: 'blue' };
    let current = { mode: config.mode, palette: config.palette };
    let saved = { ...current };
    let saving = false;

    function getStored() {
        return current.mode;
    }

    function getResolved(stored) {
        if (stored === THEMES.AUTO) {
            return window.matchMedia('(prefers-color-scheme: dark)').matches
                ? THEMES.DARK : THEMES.LIGHT;
        }
        return stored;
    }

    function apply(appearance) {
        current = { ...appearance };
        const resolved = getResolved(current.mode);
        document.documentElement.setAttribute('data-theme', resolved);
        document.documentElement.setAttribute('data-bs-theme', resolved);
        document.documentElement.setAttribute('data-palette', current.palette);
        updateToggleIcons(resolved, current.mode);
        document.querySelectorAll('#appearanceForm input[type="radio"]').forEach(radio => {
            radio.checked = radio.value === current[radio.name];
        });
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.content = getComputedStyle(document.documentElement).getPropertyValue('--nav-bg').trim();
        if (window.updateChartTheme) window.updateChartTheme(resolved);
    }

    function showStatus(message, error = false) {
        let status = document.getElementById('appearanceStatus');
        if (!status) {
            status = document.getElementById('appearanceNotification');
            if (!status) {
                status = document.createElement('div');
                status.id = 'appearanceNotification';
                document.querySelector('.workspace-content').prepend(status);
            }
            status.className = 'alert alert-' + (error ? 'danger' : 'success');
        } else {
            status.classList.toggle('text-muted', !error);
            status.classList.toggle('text-danger', error);
        }
        status.setAttribute('role', error ? 'alert' : 'status');
        status.textContent = message;
    }

    async function persist(appearance) {
        if (saving) return;
        saving = true;
        const controls = [...document.querySelectorAll('#appearanceForm input:not([type="hidden"]), #appearanceForm button, #themeToggleBtn, #themeToggleBtnMobile')];
        const disabledStates = controls.map(control => control.disabled);
        controls.forEach(control => { control.disabled = true; });
        const form = document.getElementById('appearanceForm');
        if (form) form.setAttribute('aria-busy', 'true');
        apply(appearance);
        showStatus('Saving appearance...');
        try {
            const response = await fetch(config.saveUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content,
                },
                body: JSON.stringify(appearance),
            });
            if (response.redirected) throw new Error('Your session may have expired. Sign in again before saving your appearance.');
            if (!response.headers.get('content-type')?.includes('application/json')) {
                throw new Error('Unable to save your appearance. Reload the page and try again.');
            }
            const result = await response.json();
            if (!response.ok || !result.success) {
                throw new Error(result.error || 'Unable to save your appearance. Please try again.');
            }
            saved = { ...appearance };
            showStatus('Saved to your account. Your appearance will follow you across devices.');
        } catch (error) {
            apply(saved);
            showStatus(error.message || 'Unable to save your appearance. Please try again.', true);
        } finally {
            saving = false;
            controls.forEach((control, index) => { control.disabled = disabledStates[index]; });
            if (form) form.removeAttribute('aria-busy');
        }
    }

    function updateToggleIcons(resolved, stored) {
        const isDark = resolved === THEMES.DARK;
        const icons = [
            { btn: document.getElementById('themeToggleBtn'),    icon: document.getElementById('themeIcon') },
            { btn: document.getElementById('themeToggleBtnMobile'), icon: document.getElementById('themeIconMobile') },
        ];
        icons.forEach(({ btn, icon }) => {
            if (!icon) return;
            icon.className = isDark ? 'bi bi-sun' : 'bi bi-moon';
            if (btn) {
                const label = 'Switch to ' + (isDark ? 'light' : 'dark') + ' theme';
                btn.setAttribute('aria-label', label);
                btn.title = label;
            }
        });

        const lbl = document.getElementById('themeLabel');
        if (lbl) {
            lbl.textContent = stored === THEMES.AUTO
                ? 'Auto (' + (isDark ? 'Dark' : 'Light') + ')'
                : (isDark ? 'Dark Mode' : 'Light Mode');
        }
    }

    function cycle() {
        const next = getResolved(getStored()) === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK;
        return setTheme(next);
    }

    function setTheme(theme) {
        if (!Object.values(THEMES).includes(theme)) return;
        if (config.account) return persist({ ...current, mode: theme });
        apply({ ...current, mode: theme });
        try {
            localStorage.setItem(STORAGE_KEY, theme);
        } catch (error) {
            console.warn('Family HQ: theme will only be applied to this page.', error);
            document.dispatchEvent(new CustomEvent('theme-storage-unavailable'));
        }
    }

    function init() {
        apply(current);

        // Desktop toggle
        const btn = document.getElementById('themeToggleBtn');
        if (btn) btn.addEventListener('click', cycle);

        // Mobile toggle
        const btnMobile = document.getElementById('themeToggleBtnMobile');
        if (btnMobile) btnMobile.addEventListener('click', cycle);

        const form = document.getElementById('appearanceForm');
        if (form) {
            form.addEventListener('change', event => {
                if (!['mode', 'palette'].includes(event.target.name)) return;
                apply({ ...current, [event.target.name]: event.target.value });
                showStatus('Preview only. Save appearance to keep this choice across devices.');
            });
            form.addEventListener('submit', event => {
                event.preventDefault();
                persist({ ...current });
            });
            const reset = document.getElementById('appearanceReset');
            reset.classList.remove('d-none');
            reset.addEventListener('click', () => {
                apply(saved);
                showStatus('Preview reset to your saved appearance.');
            });
        }

        // Listen for system preference changes (auto mode)
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            if (getStored() === THEMES.AUTO) apply(current);
        });
        window.addEventListener('storage', event => {
            if (config.account || (event.key !== STORAGE_KEY && event.key !== null)) return;
            const mode = event.newValue || THEMES.LIGHT;
            if (Object.values(THEMES).includes(mode)) apply({ ...current, mode });
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
window.financeChartPalette = function () {
    const styles = getComputedStyle(document.documentElement);
    return Array.from({ length: 6 }, (_, index) => styles.getPropertyValue('--chart-' + (index + 1)).trim());
};

window.updateChartTheme = function (theme) {
    if (typeof Chart === 'undefined') return;
    const styles = getComputedStyle(document.documentElement);
    const textColor = styles.getPropertyValue('--text-secondary').trim();
    const gridColor = styles.getPropertyValue('--border-color').trim();
    const bgColor = styles.getPropertyValue('--bg-surface').trim();

    Chart.defaults.color            = textColor;
    Chart.defaults.borderColor      = gridColor;
    Chart.defaults.backgroundColor  = bgColor;
    Chart.defaults.font.family      = styles.getPropertyValue('--font').trim();
    Chart.defaults.plugins.tooltip.backgroundColor = bgColor;
    Chart.defaults.plugins.tooltip.titleColor = styles.getPropertyValue('--text-primary').trim();
    Chart.defaults.plugins.tooltip.bodyColor = textColor;
    Chart.defaults.plugins.tooltip.borderColor = gridColor;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.animation = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 350 };

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
        const palette = window.financeChartPalette();
        chart.data.datasets.forEach(dataset => {
            if (dataset.financeColours) {
                dataset.backgroundColor = chart.data.labels.map((_, index) => palette[index % palette.length]);
                return;
            }
            if (!Number.isInteger(dataset.financeColour)) return;
            dataset.borderColor = palette[dataset.financeColour % palette.length];
            dataset.backgroundColor = dataset.borderColor + (dataset.financeAlpha || '');
        });
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
                chart.options.plugins.tooltip.backgroundColor = bgColor;
                chart.options.plugins.tooltip.titleColor      = styles.getPropertyValue('--text-primary').trim();
                chart.options.plugins.tooltip.bodyColor       = textColor;
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

    document.querySelectorAll('[data-bs-toggle="popover"]').forEach(element => {
        new bootstrap.Popover(element, { sanitize: false });
    });
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
