/* Korhona Xaridi | Mahsulot Turi: the supplied prototype's drawer with sample orders. */

'use strict';

const sampleOrders = [
  {num:'ARZ-2025-001',bolim:'Texnik',nomi:'Bolt M12×50',soni:500,status:'Shartnoma tuzilgan',sc:'badge-info'},
  {num:'ARZ-2025-004',bolim:'Texnik',nomi:'Prokat po\'lat',soni:1000,status:"Birjaga qo'yilgan",sc:'badge-trial'},
  {num:'ARZ-2025-009',bolim:'Ishlab chiqarish',nomi:'Armatura D12',soni:800,status:'Yetkazib berilgan',sc:'badge-approved'},
];

function openView(category) {
  document.getElementById('view-drawer-title').textContent = category + ' — Buyurtmalar';
  document.getElementById('drawer-tbody').innerHTML = sampleOrders.map(d=>`
    <tr>
      <td class="mono-cell">${d.num}</td>
      <td>${d.bolim}</td>
      <td>${d.nomi}</td>
      <td style="font-weight:600;">${d.soni}</td>
      <td><span class="badge ${d.sc}">${d.status}</span></td>
    </tr>
  `).join('');
  Drawer.open('view-drawer');
}
