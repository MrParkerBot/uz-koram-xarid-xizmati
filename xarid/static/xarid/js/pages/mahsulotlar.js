/* Korhona Xaridi | Mahsulotlar: the supplied prototype's sample product rows. */

'use strict';

const statusBadge = {
  'Kelib tushdi':'badge-soft', 'Qabul qilindi':'badge-info', 'Tayinlandi':'badge-info',
  'Shartnoma tuzilgan':'badge-info', "Birjaga qo'yilgan":'badge-trial',
  'Yetkazib berilgan':'badge-approved', 'Bekor qilingan':'badge-danger'
};

const products = [
  {id:1,num:'ARZ-2025-001',bolim:'Texnik',mahsulot:'100042 — Metal',nomi:'Bolt M12×50',soni:500,olchov:'ta',izoh:'Zanglamaydigan',date:'2025-03-10',status:'Shartnoma tuzilgan'},
  {id:2,num:'ARZ-2025-002',bolim:'Ishlab chiqarish',mahsulot:'200031 — Kimyoviy',nomi:'Asetilen gazi',soni:20,olchov:'kg',izoh:'—',date:'2025-03-11',status:'Qabul qilindi'},
  {id:3,num:'ARZ-2025-003',bolim:'Moliya',mahsulot:'300015 — Elektr',nomi:'Kabel 4mm²',soni:200,olchov:'m',izoh:'Mis',date:'2025-03-12',status:'Tayinlandi'},
  {id:4,num:'ARZ-2025-004',bolim:'Texnik',mahsulot:'100042 — Metal',nomi:'Prokat po\'lat',soni:1000,olchov:'kg',izoh:'GOST',date:'2025-03-13',status:"Birjaga qo'yilgan"},
  {id:5,num:'ARZ-2025-005',bolim:'Texnik',mahsulot:'400008 — Qurilish',nomi:'Sement M500',soni:50,olchov:'qop',izoh:'Nam emas',date:'2025-03-14',status:'Yetkazib berilgan'},
  {id:6,num:'ARZ-2025-006',bolim:'Ishlab chiqarish',mahsulot:'500022 — Yoqilg\'i',nomi:'Dizel yoqilg\'isi',soni:1000,olchov:'l',izoh:'Euro-5',date:'2025-03-15',status:'Shartnoma tuzilgan'},
  {id:7,num:'ARZ-2025-007',bolim:'Moliya',mahsulot:'300015 — Elektr',nomi:'Lampa LED 40W',soni:100,olchov:'ta',izoh:'—',date:'2025-03-16',status:'Bekor qilingan'},
];

function filterByStatus(val) {
  document.querySelectorAll('#mahsulot-tbody tr').forEach(row => {
    row.style.display = (!val || row.textContent.includes(val)) ? '' : 'none';
  });
}

function renderTable() {
  document.getElementById('mahsulot-tbody').innerHTML = products.map((item,i) => `
    <tr>
      <td>${i+1}</td>
      <td class="mono-cell">${item.num}</td>
      <td>${item.bolim}</td>
      <td style="font-size:12px;">${item.mahsulot}</td>
      <td style="font-weight:500;">${item.nomi}</td>
      <td style="font-weight:600;color:var(--color-primary);">${item.soni}</td>
      <td>${item.olchov}</td>
      <td style="font-size:11px;color:var(--color-text-muted);">${item.izoh}</td>
      <td><span class="pdf-badge"><i class="bi bi-file-earmark-pdf" aria-hidden="true"></i></span></td>
      <td class="mono-cell">${item.date}</td>
      <td><span class="badge ${statusBadge[item.status]||'badge-soft'}">${item.status}</span></td>
    </tr>
  `).join('');
  document.getElementById('total-count').textContent = products.length;
}
renderTable();
