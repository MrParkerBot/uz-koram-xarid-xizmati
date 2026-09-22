/* 1C Integratsiya: the supplied prototype's simulated sync and status toggle. */

'use strict';

let apiConnected = true;

document.getElementById('sync-now').addEventListener('click', (event) => {
  const btn = event.currentTarget;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Sinxronlanmoqda…';
  setTimeout(() => {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-repeat" aria-hidden="true"></i> Sinxronlash';
    Toast.success('Sinxronlash muvaffaqiyatli bajarildi');
    const tbody = document.getElementById('sync-log-tbody');
    const d = new Date();
    const pad = n => String(n).padStart(2, '0');
    // Day first, the way every date on the pages is printed.
    const now = `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} `
      + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const newRow = `<tr><td class="mono-cell">SHT-2025-044</td><td class="mono-cell">${now}</td><td><span class="badge badge-approved">Muvaffaq</span></td><td>—</td><td>—</td></tr>`;
    tbody.insertAdjacentHTML('afterbegin', newRow);
  }, 2000);
});

function retrySync(num) {
  Toast.info(`${num} qayta sinxronlanmoqda…`);
  setTimeout(() => Toast.success(`${num} muvaffaqiyatli sinxronlandi`), 1500);
}

// Toggle the connected / not connected demo state.
document.querySelector('#api-status-badge').addEventListener('click', () => {
  apiConnected = !apiConnected;
  document.getElementById('api-dot').className = `api-status-dot ${apiConnected?'online':'offline'}`;
  document.getElementById('api-status-text').textContent = apiConnected ? '1C API: Ulangan' : '1C API: Ulanmagan';
  document.getElementById('api-status-badge').innerHTML = apiConnected
    ? '<span class="badge badge-approved"><i class="bi bi-circle-fill" aria-hidden="true"></i> Ulangan</span>'
    : '<span class="badge badge-danger"><i class="bi bi-circle-fill" aria-hidden="true"></i> Ulanmagan</span>';
});
