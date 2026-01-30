// Main JavaScript file for JonesHQ Finance

document.addEventListener('DOMContentLoaded', function() {
    console.log('JonesHQ Finance loaded');
    
    // Add any global JavaScript functionality here
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
