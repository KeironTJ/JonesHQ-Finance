// Income source form: show fields that apply to the chosen income type / pay
// frequency and keep a live payslip estimate (POSTs to income.calculate_preview).
(function () {
    const form = document.getElementById('source-form');
    if (!form) return;

    const rules = JSON.parse(form.dataset.typeRules || '{}');
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const preview = document.getElementById('preview');
    const typeSelect = form.querySelector('#income_type');
    const freqSelect = form.querySelector('#pay_frequency');
    const grossLabel = form.querySelector('#gross_label');
    const grossLabels = {
        employment: 'Annual salary',
        private_pension: 'Annual pension',
        state_pension: 'Annual state pension',
        self_employed: 'Annual profit',
        rental: 'Annual rent',
        benefit: 'Annual amount',
        other_untaxed: 'Annual amount',
    };
    const money = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' });

    function applyVisibility() {
        const type = typeSelect.value;
        const freq = freqSelect.value;
        form.querySelectorAll('[data-show-rule]').forEach(el => {
            el.classList.toggle('d-none', !(rules[el.dataset.showRule] || []).includes(type));
        });
        form.querySelectorAll('[data-show-freq]').forEach(el => {
            el.classList.toggle('d-none', !el.dataset.showFreq.split(' ').includes(freq));
        });
        if (grossLabel) grossLabel.textContent = grossLabels[type] || 'Annual gross';
    }

    function payload() {
        const data = {};
        new FormData(form).forEach((value, key) => {
            if (key === 'csrf_token') return;
            if (key === 'student_loan_plans') {
                (data[key] = data[key] || []).push(value);
            } else {
                data[key] = value;
            }
        });
        return data;
    }

    function row(label, value, cls) {
        return `<tr class="${cls || ''}"><td>${label}</td><td class="text-end">${money.format(value)}</td></tr>`;
    }

    function render(r) {
        const per = { monthly: 'month', weekly: 'week', fortnightly: 'fortnight', four_weekly: '4 weeks', annual: 'year' }[r.frequency] || 'payment';
        let html = `<div class="text-center mb-3">
            <div class="text-muted small">Take home per ${per}</div>
            <div class="fs-3 fw-bold text-success">${money.format(r.take_home)}</div>
            <div class="small text-muted">≈ ${money.format(r.take_home * r.periods_per_year)} a year · tax year ${r.tax_year}</div>
        </div><table class="table table-sm small mb-2"><tbody>`;
        html += row('Gross', r.gross_period, 'fw-semibold');
        if (r.employee_pension) html += row('Your pension', -r.employee_pension);
        if (r.income_tax) html += row(r.income_type === 'rental' ? 'Set aside for tax' : 'Income tax', -r.income_tax);
        if (r.national_insurance) html += row('National Insurance', -r.national_insurance);
        if (r.student_loan) html += row('Student loan', -r.student_loan);
        if (r.avc) html += row('AVC', -r.avc);
        if (r.other_deductions) html += row('Other', -r.other_deductions);
        html += row('Take home', r.take_home, 'fw-semibold table-success');
        html += '</tbody></table>';
        if (r.employer_pension) {
            html += `<div class="small text-muted">Employer adds ${money.format(r.employer_pension)} to your pension.</div>`;
        }
        (r.warnings || []).forEach(w => {
            html += `<div class="alert alert-warning small py-1 px-2 mt-2 mb-0">${escapeHtml(w)}</div>`;
        });
        preview.innerHTML = html;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    let timer = null;
    let seq = 0;
    function schedulePreview() {
        clearTimeout(timer);
        timer = setTimeout(async () => {
            const data = payload();
            if (!data.gross_annual) {
                preview.innerHTML = '<p class="text-muted small mb-0">Enter the gross amount to see an estimate.</p>';
                return;
            }
            const mine = ++seq;
            try {
                const response = await fetch(form.dataset.previewUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                    body: JSON.stringify(data),
                });
                const result = await response.json();
                if (mine !== seq) return;
                if (result.success) {
                    render(result);
                } else {
                    preview.innerHTML = `<div class="text-danger small">${escapeHtml(result.error || 'Unable to estimate.')}</div>`;
                }
            } catch (e) {
                if (mine === seq) preview.innerHTML = '<div class="text-danger small">Unable to estimate right now.</div>';
            }
        }, 300);
    }

    typeSelect.addEventListener('change', applyVisibility);
    freqSelect.addEventListener('change', applyVisibility);
    form.addEventListener('input', schedulePreview);
    form.addEventListener('change', schedulePreview);
    applyVisibility();
    schedulePreview();
})();
