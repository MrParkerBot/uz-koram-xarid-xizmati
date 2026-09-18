/* Dashboard: the supplied prototype's charts and the Top suppliers toggle. */

'use strict';

window.addEventListener('load', () => {
  Charts.spendingChart('spending-chart');
  Charts.categoryBarChart('category-chart');
});

document.querySelectorAll('[data-top-mode]').forEach((button) => {
  button.addEventListener('click', () => {
    const mode = button.dataset.topMode;
    document.getElementById('toggle-sum').className   = mode === 'sum'   ? 'badge badge-primary' : 'badge badge-soft';
    document.getElementById('toggle-count').className = mode === 'count' ? 'badge badge-primary' : 'badge badge-soft';
    Toast.info('Ko\'rinish o\'zgartirildi');
  });
});
