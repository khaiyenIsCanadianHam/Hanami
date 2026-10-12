(() => {
  'use strict';
  const dataNode = document.getElementById('revenue-data');
  const canvas = document.querySelector('[data-revenue-chart]');
  if (!dataNode || !canvas || typeof Chart === 'undefined') return;
  const data = JSON.parse(dataNode.textContent);
  canvas.hidden = false;
  const fallback = document.querySelector('[data-chart-fallback]');
  if (fallback) fallback.hidden = true;
  new Chart(canvas, {
    type: 'bar',
    data: {labels: data.labels, datasets: [
      {label: 'Verified receipts', data: data.receipts.map(Number), backgroundColor: '#789b7c', borderRadius: 4, maxBarThickness: 18},
      {label: 'Expenses', data: data.expenses.map(Number), backgroundColor: '#deb18f', borderRadius: 4, maxBarThickness: 18}
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : {duration: 400},
      plugins: {legend: {display: false}, tooltip: {callbacks: {label: item => `${item.dataset.label}: ${new Intl.NumberFormat(undefined, {style:'currency',currency:data.currency}).format(item.parsed.y)}`}}},
      scales: {
        x: {grid: {display: false}, border: {display: false}, ticks: {font: {size: 9}, color: '#8c988c'}},
        y: {beginAtZero: true, border: {display:false}, grid: {color: '#89978015', drawTicks:false}, ticks: {maxTicksLimit: 5, padding: 12, font:{size:9}, color:'#8c988c', callback: value => value >= 1000 ? `${value/1000}k` : value}}
      }
    }
  });
})();
