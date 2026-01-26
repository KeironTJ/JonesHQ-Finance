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
