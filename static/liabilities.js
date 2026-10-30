(() => {
  'use strict';
  const total = document.getElementById('original_principal');
  const current = document.getElementById('current_balance');
  const outstanding = document.getElementById('outstanding_percentage');
  const repaid = document.getElementById('repaid_percentage');
  function calculate() {
    const totalValue = Number(total?.value) || 0;
    const currentValue = Number(current?.value) || 0;
    const outstandingValue = totalValue > 0 ? (currentValue / totalValue) * 100 : 0;
    const repaidValue = totalValue > 0 ? Math.max(0, 100 - outstandingValue) : 0;
    if (outstanding) { outstanding.value = `${outstandingValue.toFixed(2)}%`; outstanding.classList.toggle('negative', outstandingValue > 0); outstanding.classList.toggle('positive', outstandingValue === 0); }
    if (repaid) repaid.value = `${repaidValue.toFixed(2)}%`;
  }
  [total, current].filter(Boolean).forEach(field => field.addEventListener('input', calculate));
  document.querySelectorAll('.liability-delete-form').forEach(form => form.addEventListener('submit', event => { if (!window.confirm('Delete this liability record?')) event.preventDefault(); }));
  calculate();
})();
