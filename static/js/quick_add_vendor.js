let quickAddVendorTargetSelectId = null;
let quickAddVendorPending = false;
let quickAddVendorShown = Promise.resolve();

function openQuickAddVendor(selectId) {
    quickAddVendorTargetSelectId = selectId;
    const modal = document.getElementById('quickAddVendorModal');
    document.getElementById('quickVendorName').value = '';
    document.getElementById('quickVendorError').style.display = 'none';
    quickAddVendorShown = new Promise(resolve => {
        modal.addEventListener('shown.bs.modal', function () {
            document.getElementById('quickVendorName').focus();
            resolve();
        }, { once: true });
    });
    bootstrap.Modal.getOrCreateInstance(modal).show();
}

document.getElementById('quickVendorName').addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        submitQuickAddVendor();
    }
});

async function submitQuickAddVendor() {
    if (quickAddVendorPending) return;
    const name = document.getElementById('quickVendorName').value.trim();
    const errorElement = document.getElementById('quickVendorError');
    if (!name) {
        errorElement.textContent = 'Please enter a name.';
        errorElement.style.display = '';
        return;
    }
    const modal = document.getElementById('quickAddVendorModal');
    const select = document.getElementById(quickAddVendorTargetSelectId);
    const button = document.getElementById('quickVendorSubmit');
    errorElement.style.display = 'none';
    quickAddVendorPending = true;
    button.disabled = true;
    try {
        const response = await fetch(modal.dataset.quickAddUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': modal.dataset.csrfToken},
            body: JSON.stringify({name})
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            throw new Error(data.error || 'Request failed. Try again.');
        }
        if (!Number.isInteger(data.id) || typeof data.name !== 'string') {
            throw new Error('Invalid response. Try again.');
        }
        if (!Array.from(select.options).some(option => option.value === String(data.id))) {
            select.add(new Option(data.name, data.id));
        }
        select.value = String(data.id);
        select.dispatchEvent(new Event('change', {bubbles: true}));
        await quickAddVendorShown;
        bootstrap.Modal.getInstance(modal).hide();
    } catch (error) {
        errorElement.textContent = error.message || 'Request failed. Try again.';
        errorElement.style.display = '';
    } finally {
        quickAddVendorPending = false;
        button.disabled = false;
    }
}
