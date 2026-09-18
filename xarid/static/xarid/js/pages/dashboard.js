/* Dashboard: the two charts.

The spendings chart is still the supplied prototype's own numbers. The
category chart draws the counted rows the table beside it shows, read from
the JSON the page emits, so the two cannot say different things.

The Summa / Tur soni toggle that sat on the Top suppliers panel is gone with
it: it recoloured two badges and raised a toast, and the ranking has one
measure (DEC-025). */

'use strict';

window.addEventListener('load', () => {
  Charts.spendingChart('spending-chart');
  Charts.categoryBarChart('category-chart', 'category-chart-data');
});
