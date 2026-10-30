(() => {
  'use strict';
  const dataNode = document.getElementById('dashboard-chart-data');
  if (!dataNode) return;

  let data;
  try { data = JSON.parse(dataNode.textContent || '{}'); }
  catch (error) { console.error('Invalid dashboard chart data.', error); return; }

  const palette = ['#38bdf8','#22c55e','#6366f1','#f59e0b','#eab308','#ef4444','#8b5cf6','#14b8a6','#94a3b8'];
  const currencySymbols = {INR:'₹',USD:'$',EUR:'€',GBP:'£',SGD:'S$',AED:'د.إ',JPY:'¥',CAD:'C$',AUD:'A$'};
  const textColor = '#c9cbd5';
  const mutedColor = '#8f91a2';
  const gridColor = 'rgba(169,170,187,.16)';
  const formatNumber = value => new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(Number(value)||0);

  function prepare(canvas) {
    const parent = canvas.parentElement;
    const ratio = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const width = Math.max(280, parent.clientWidth);
    const height = Math.max(250, parent.clientHeight);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return {ctx, width, height};
  }

  function empty(ctx, width, height, label='No data available') {
    ctx.fillStyle = mutedColor;
    ctx.font = '13px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText(label, width / 2, height / 2);
  }

  function legend(ctx, labels, values, colors, total, width, startY=18) {
    ctx.font = '12px system-ui';
    ctx.textAlign = 'left';
    let x = 18;
    let y = startY;
    labels.forEach((label, index) => {
      const value = Number(values[index]) || 0;
      const pct = total > 0 ? (value / total) * 100 : 0;
      const valueText = `${label}  ${pct.toFixed(1)}%`;
      const itemWidth = ctx.measureText(valueText).width + 42;
      if (x + itemWidth > width - 12) { x = 18; y += 24; }
      ctx.fillStyle = colors[index];
      ctx.beginPath();
      ctx.arc(x + 6, y - 4, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = textColor;
      ctx.fillText(valueText, x + 18, y);
      x += itemWidth;
    });
    return y + 18;
  }

  function currencyContext(labels) {
    const currencies = Array.isArray(labels) ? labels.filter(Boolean) : [];
    if (currencies.length !== 1) return {prefix:'', caption:'Mixed currencies'};
    const code = currencies[0];
    return {prefix:`${currencySymbols[code] || code} `, caption:code};
  }

  function donut(id, series, centerLabel, showCurrency=false) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const {ctx, width, height} = prepare(canvas);
    const labels = Array.isArray(series.labels) ? series.labels : [];
    const values = Array.isArray(series.values) ? series.values.map(Number) : [];
    const total = values.reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
    if (!labels.length || total <= 0) { empty(ctx, width, height); return; }

    const colors = labels.map((_, index) => palette[index % palette.length]);
    const legendBottom = legend(ctx, labels, values, colors, total, width);
    const primary = id === 'allocation-chart';
    const availableHeight = Math.max(175, height - legendBottom - 18);
    const radius = Math.min(width * (primary ? 0.30 : 0.28), availableHeight * 0.50);
    const inner = radius * (primary ? 0.68 : 0.60);
    const cx = width / 2;
    const cy = legendBottom + availableHeight / 2;
    let angle = -Math.PI / 2;

    values.forEach((value, index) => {
      const next = angle + (value / total) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, angle, next);
      ctx.arc(cx, cy, inner, next, angle, true);
      ctx.closePath();
      ctx.fillStyle = colors[index];
      ctx.fill();
      ctx.strokeStyle = '#303244';
      ctx.lineWidth = primary ? 4 : 2;
      ctx.stroke();
      angle = next;
    });

    const currency = currencyContext(data.balance?.labels);
    const prefix = showCurrency ? currency.prefix : '';
    const caption = showCurrency ? `Current portfolio value · ${currency.caption}` : centerLabel;
    ctx.fillStyle = '#fff';
    ctx.font = primary ? '700 20px system-ui' : '700 18px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText(`${prefix}${formatNumber(total)}`, cx, cy - 3);
    ctx.fillStyle = mutedColor;
    ctx.font = '11px system-ui';
    ctx.fillText(caption, cx, cy + 20);
  }

  function barChart(id, series) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const {ctx, width, height} = prepare(canvas);
    const labels = Array.isArray(series.labels) ? series.labels : [];
    const assets = Array.isArray(series.assets) ? series.assets.map(Number) : [];
    const liabilities = Array.isArray(series.liabilities) ? series.liabilities.map(Number) : [];
    if (!labels.length) { empty(ctx, width, height); return; }

    const totalAssets = assets.reduce((sum, value) => sum + (value || 0), 0);
    const totalLiabilities = liabilities.reduce((sum, value) => sum + (value || 0), 0);
    const grandTotal = totalAssets + totalLiabilities;
    legend(ctx, ['Assets','Liabilities'], [totalAssets,totalLiabilities], ['#4da48d','#e45676'], grandTotal, width);

    const top = 58, left = 78, bottom = 40;
    const plotH = height - top - bottom;
    const plotW = width - left - 20;
    const max = Math.max(1, ...assets, ...liabilities);
    const step = plotW / labels.length;
    const bar = Math.min(32, step * 0.27);
    const currency = currencyContext(labels);

    ctx.font = '10px system-ui';
    for (let i = 0; i <= 4; i += 1) {
      const y = top + plotH * i / 4;
      ctx.strokeStyle = gridColor;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(width - 14, y);
      ctx.stroke();
      ctx.fillStyle = textColor;
      ctx.textAlign = 'right';
      ctx.fillText(`${currency.prefix}${formatNumber(max * (1 - i / 4))}`, left - 8, y + 3);
    }

  labels.forEach((label, i) => {
    const x =
    left + step * i + step / 2;
    [
      [assets[i] || 0, -bar - 15, '#4da48d'],
      [liabilities[i] || 0, 15, '#e45676']
    ].forEach(([value, offset, color]) => {
      const barHeight =
      value / max * plotH;
      ctx.fillStyle = color;
      ctx.fillRect(
        x + offset,
        top + plotH - barHeight,
        bar,barHeight
        );
        /* Value labels */
        ctx.fillStyle =
        '#ffffff';
        ctx.font =
        '10px system-ui';
        ctx.textAlign =
            'center';

        const valueLabel =
            `${currency.prefix}${formatNumber(value)}`;

        ctx.fillText(
            valueLabel,
            x + offset + (bar / 2),
            top + plotH - barHeight - 6
        );

    });

    ctx.fillStyle =
        textColor;

    ctx.textAlign =
        'center';

    ctx.fillText(
        label,
        x,
        height - 14
    );

});
  }

  function lineChart(id, series) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const {ctx, width, height} = prepare(canvas);
    const labels = Array.isArray(series.labels) ? series.labels : [];
    const income = Array.isArray(series.income) ? series.income.map(Number) : [];
    const expense = Array.isArray(series.expense) ? series.expense.map(Number) : [];
    if (!labels.length) { empty(ctx, width, height); return; }

    const totalIncome = income.reduce((sum, value) => sum + (value || 0), 0);
    const totalExpense = expense.reduce((sum, value) => sum + (value || 0), 0);
    legend(ctx, ['Income','Expense'], [totalIncome,totalExpense], ['#4da48d','#e45676'], totalIncome + totalExpense, width);

    const top = 58, left = 64, bottom = 40;
    const plotH = height - top - bottom;
    const plotW = width - left - 20;
    const max = Math.max(1, ...income, ...expense);

    for (let i = 0; i <= 4; i += 1) {
      const y = top + plotH * i / 4;
      ctx.strokeStyle = gridColor;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(width - 14, y);
      ctx.stroke();
      ctx.fillStyle = textColor;
      ctx.font = '10px system-ui';
      ctx.textAlign = 'right';
      ctx.fillText(formatNumber(max * (1 - i / 4)), left - 8, y + 3);
    }

    const draw = (values, color) => {
      ctx.beginPath();
      values.forEach((value, i) => {
        const x = left + (labels.length === 1 ? plotW / 2 : i * plotW / (labels.length - 1));
        const y = top + plotH - value / max * plotH;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.stroke();
    };
    draw(income, '#4da48d');
    draw(expense, '#e45676');

    ctx.fillStyle = textColor;
    ctx.font = '10px system-ui';
    ctx.textAlign = 'center';
    labels.forEach((label, i) => {
      if (labels.length <= 6 || i % 2 === 0) {
        const x = left + (labels.length === 1 ? plotW / 2 : i * plotW / (labels.length - 1));
        ctx.fillText(label, x, height - 14);
      }
    });
  }

  function render() {
    donut('allocation-chart', data.allocation || {}, '', true);
    barChart('balance-chart', data.balance || {});
    lineChart('cashflow-chart', data.cashflow || {});
    donut('liability-chart',data.liabilities || {},'Outstanding',true);
    donut('metals-chart',data.metals || {},'Current value',true);
  }

  let resizeTimer;
  render();
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 180);
  });
})();
