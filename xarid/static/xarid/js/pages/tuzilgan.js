/* Tuzilgan Shartnomalar: the supplied prototype's sample rows and actions. */

'use strict';

let currentActionId = null;
const contracts = [
  {id:1, arizaNum:'ARZ-2025-001', bolim:'Texnik',  nomi:'Bolt M12×50',    shtNum:'SHT-2025-042', firma:'Texnoprom LLC', kim:'A. Karimov',  date:'2025-03-12', qiymati:'42,500,000', status:'pending',  rejectReason:''},
  {id:2, arizaNum:'ARZ-2025-003', bolim:'Moliya',  nomi:'Kabel 4mm²',     shtNum:'SHT-2025-043', firma:'ElektroStar',   kim:'D. Yusupova', date:'2025-03-13', qiymati:'18,750,000', status:'pending',  rejectReason:''},
  {id:3, arizaNum:'ARZ-2025-006', bolim:'Ishlab chiqarish', nomi:'Dizel', shtNum:'SHT-2025-044', firma:'GazTrade',      kim:'B. Toshmatov',date:'2025-03-14', qiymati:'95,000,000', status:'rejected', rejectReason:'Narx noto\'g\'ri, qayta ko\'rib chiqing'},
];

function acceptContract(id) {
  const item = contracts.find(c=>c.id===id);
  Modal.confirm('Shartnomani tasdiqlaysizmi?', `"${item.shtNum}" shartnomasi tasdiqlanadi va mutaxassisga xabar yuboriladi.`, () => {
    item.status = 'accepted';
    renderTable();
    Toast.success(`${item.shtNum} tasdiqlandi`);
  }, false);
}

function openReject(id) {
  currentActionId = id;
  const item = contracts.find(c=>c.id===id);
  document.getElementById('reject-desc').textContent = `"${item.shtNum}" shartnomasi inkor etiladi. Sababini kiriting:`;
  document.getElementById('reject-reason').value = '';
  document.getElementById('reject-reason-err').textContent = '';
  Modal.open('reject-modal');
}

document.getElementById('confirm-reject-btn').addEventListener('click', () => {
  const reason = document.getElementById('reject-reason').value.trim();
  if (!reason) { document.getElementById('reject-reason-err').textContent = 'Sabab kiritilishi shart'; return; }
  const item = contracts.find(c=>c.id===currentActionId);
  if (item) { item.status = 'rejected'; item.rejectReason = reason; }
  Modal.close('reject-modal');
  renderTable();
  Toast.error('Shartnoma inkor etildi. Mutaxassis xabardor qilindi.');
});

function openView(id) {
  const item = contracts.find(c=>c.id===id);
  document.getElementById('view-drawer-title').textContent = `${item.shtNum} — Tafsilotlar`;
  document.getElementById('view-drawer-body').innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;">
      <div class="panel"><div class="panel-body" style="padding:16px;">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;">
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Shartnoma №</div><strong class="mono-cell">${item.shtNum}</strong></div>
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Ariza №</div><span class="mono-cell">${item.arizaNum}</span></div>
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Firma</div>${item.firma}</div>
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Bo'lim</div>${item.bolim}</div>
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Buyurtma</div>${item.nomi}</div>
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Umumiy Qiymat</div><strong style="color:var(--color-primary);">${item.qiymati} UZS</strong></div>
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Kim tuzdi</div>${item.kim}</div>
          <div><div style="font-size:10px;color:var(--color-text-muted);text-transform:uppercase;margin-bottom:3px;">Sana</div>${item.date}</div>
        </div>
      </div></div>
      <table class="table-app"><thead><tr><th>Buyurtma nomi</th><th>Miqdori</th><th>Birlik</th><th>Narx (1ta)</th><th>Jami</th></tr></thead>
        <tbody><tr><td>${item.nomi}</td><td>500</td><td>ta</td><td>85,000</td><td style="font-weight:700;">${item.qiymati}</td></tr></tbody></table>
      <span class="pdf-badge" style="align-self:flex-start;padding:8px 14px;"><i class="bi bi-file-earmark-pdf" aria-hidden="true"></i> Shartnoma.pdf yuklab olish</span>
    </div>
  `;
  document.getElementById('view-drawer-footer').innerHTML = item.status === 'pending' ? `
    <button class="btn btn-outline-custom" data-close-drawer="view-drawer">Yopish</button>
    <button class="btn btn-outline-custom text-danger btn-sm" onclick="openReject(${item.id});Drawer.close('view-drawer')"><i class="bi bi-x-lg" aria-hidden="true"></i> Inkor</button>
    <button class="btn btn-outline-custom text-success btn-sm" onclick="acceptContract(${item.id});Drawer.close('view-drawer')"><i class="bi bi-check-lg" aria-hidden="true"></i> Qabul</button>
  ` : `<button class="btn btn-outline-custom" data-close-drawer="view-drawer">Yopish</button>`;
  document.querySelectorAll('#view-drawer-footer [data-close-drawer]').forEach(btn => {
    btn.addEventListener('click', () => Drawer.close(btn.dataset.closeDrawer));
  });
  Drawer.open('view-drawer');
}

function renderTable() {
  const tbody = document.getElementById('tuzilgan-tbody');
  tbody.innerHTML = contracts.map((item,i) => `
    <tr data-id="${item.id}">
      <td>${i+1}</td>
      <td class="mono-cell">${item.arizaNum}</td>
      <td>${item.bolim}</td>
      <td style="font-weight:500;">${item.nomi}</td>
      <td class="mono-cell">${item.shtNum}</td>
      <td>${item.firma}</td>
      <td>${item.kim}</td>
      <td class="mono-cell">${item.date}</td>
      <td style="text-align:center;"><button class="btn btn-outline-custom btn-xs" onclick="openView(${item.id})"><i class="bi bi-eye" aria-hidden="true"></i> Ko'rish</button></td>
      <td style="text-align:center;white-space:nowrap;">
        ${item.status === 'pending'
          ? `<button class="btn btn-outline-custom text-success btn-xs" onclick="acceptContract(${item.id})"><i class="bi bi-check-lg" aria-hidden="true"></i> Qabul</button>
             <button class="btn btn-outline-custom text-danger btn-xs" onclick="openReject(${item.id})"><i class="bi bi-x-lg" aria-hidden="true"></i> Inkor</button>`
          : item.status === 'accepted'
            ? `<span class="badge badge-approved">Tasdiqlandi</span>`
            : `<span class="badge badge-danger" title="${Toast.escape(item.rejectReason)}">Inkor etildi</span>`
        }
      </td>
    </tr>
  `).join('');
  document.getElementById('total-count').textContent = contracts.length;
}

renderTable();
