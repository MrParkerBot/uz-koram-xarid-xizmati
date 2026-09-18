/* Xodimlar Yuklamasi: the supplied prototype's sample workload rows. */

'use strict';

const workload = [
  {id:1, name:'Alisher Karimov',  phone:'90 111 22 33', jami:12, boshlangich:3, birja:2, shartnoma:5, yetkazib:1, bekor:1},
  {id:2, name:'Bobur Toshmatov',  phone:'91 222 33 44', jami:8,  boshlangich:1, birja:1, shartnoma:4, yetkazib:2, bekor:0},
  {id:3, name:'Dilnoza Yusupova', phone:'93 333 44 55', jami:11, boshlangich:2, birja:3, shartnoma:4, yetkazib:2, bekor:0},
  {id:4, name:'Sardor Nazarov',   phone:'94 444 55 66', jami:7,  boshlangich:1, birja:2, shartnoma:2, yetkazib:1, bekor:1},
];

const maxJami = Math.max(...workload.map(d=>d.jami));

function applyFilter() {
  Toast.info('Hisobot yangilandi');
  renderTable();
}

function renderTable() {
  const tbody = document.getElementById('yukl-tbody');
  const sortDir = document.getElementById('f-sort').value;
  const sorted = [...workload].sort((a,b) => sortDir==='desc' ? b.jami-a.jami : a.jami-b.jami);

  tbody.innerHTML = sorted.map((item,i) => {
    const isTop = item.jami === maxJami;
    return `
    <tr>
      <td>${i+1}</td>
      <td><div style="display:flex;align-items:center;gap:8px;"><div class="user-avatar">${item.name.split(' ').map(n=>n[0]).join('')}</div><strong>${item.name}</strong></div></td>
      <td class="mono-cell">+998 ${item.phone}</td>
      <td style="font-weight:800;font-size:15px;${isTop?'color:var(--color-primary);':''}">${item.jami}</td>
      <td>${item.boshlangich}</td>
      <td>${item.birja}</td>
      <td style="font-weight:600;">${item.shartnoma}</td>
      <td style="color:var(--color-success);font-weight:600;">${item.yetkazib}</td>
      <td style="color:${item.bekor>0?'var(--color-danger)':'var(--color-text-muted)'};font-weight:${item.bekor>0?700:400};">${item.bekor}</td>
    </tr>`;
  }).join('');

  const totals = sorted.reduce((acc,d) => ({
    jami:acc.jami+d.jami, boshlangich:acc.boshlangich+d.boshlangich,
    birja:acc.birja+d.birja, shartnoma:acc.shartnoma+d.shartnoma,
    yetkazib:acc.yetkazib+d.yetkazib, bekor:acc.bekor+d.bekor
  }), {jami:0,boshlangich:0,birja:0,shartnoma:0,yetkazib:0,bekor:0});

  tbody.innerHTML += `
    <tr class="total-row">
      <td colspan="3" style="font-weight:700;"><i class="bi bi-file-earmark-spreadsheet" aria-hidden="true"></i> Jami:</td>
      <td style="font-weight:800;color:var(--color-primary);">${totals.jami}</td>
      <td style="font-weight:700;">${totals.boshlangich}</td>
      <td style="font-weight:700;">${totals.birja}</td>
      <td style="font-weight:700;">${totals.shartnoma}</td>
      <td style="font-weight:700;color:var(--color-success);">${totals.yetkazib}</td>
      <td style="font-weight:700;color:var(--color-danger);">${totals.bekor}</td>
    </tr>`;
}

// Default date range: the current month.
const now = new Date();
document.getElementById('f-dan').value   = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0];
document.getElementById('f-gacha').value = new Date(now.getFullYear(), now.getMonth()+1, 0).toISOString().split('T')[0];

renderTable();
