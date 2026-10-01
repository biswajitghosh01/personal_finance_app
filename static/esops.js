(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const fields = ['number_of_units', 'grant_price', 'current_price'].map(byId);
  const number = id => Number(byId(id)?.value) || 0;

  function calculate() {
    const units = number('number_of_units');
    const grantPrice = number('grant_price');
    const currentPrice = number('current_price');
    const totalGrantValue = units * grantPrice;
    const currentValue = units * currentPrice;
    const pnl = currentValue - totalGrantValue;
    const pct = totalGrantValue > 0 ? (pnl / totalGrantValue) * 100 : 0;

    byId('total_grant_value').value = totalGrantValue.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    byId('current_value').value = currentValue.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    byId('profit_loss_amount').value = pnl.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    byId('profit_loss_percentage').value = pct.toFixed(2) + '%';

    ['profit_loss_amount', 'profit_loss_percentage'].forEach(id => {
      const el = byId(id);
      if (!el) return;
      el.classList.toggle('positive', pnl >= 0);
      el.classList.toggle('negative', pnl < 0);
    });
  }

  fields.filter(Boolean).forEach(field => field.addEventListener('input', calculate));
  calculate();
})();
