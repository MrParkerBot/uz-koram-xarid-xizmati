/* Logs: the supplied prototype's sample audit rows. */

'use strict';

const methodColors = {GET:'get',POST:'post',PUT:'put',DELETE:'del'};
const logs = [
  {id:1, time:'2025-03-17 15:42:10', user:'A. Karimov (Admin)',    method:'POST',   endpoint:'/api/contracts',          status:201, action:'Shartnoma yaratildi (SHT-2025-044)', duration:'142ms', ip:'192.168.1.5'},
  {id:2, time:'2025-03-17 15:40:05', user:'B. Toshmatov (Spec)',   method:'PUT',    endpoint:'/api/contracts/42/status', status:200, action:'Shartnoma holati yangilandi',         duration:'88ms',  ip:'192.168.1.8'},
  {id:3, time:'2025-03-17 15:38:22', user:'D. Yusupova (Spec)',    method:'POST',   endpoint:'/api/applications',        status:201, action:'Yangi ariza yaratildi (ARZ-2025-019)',duration:'110ms', ip:'192.168.1.12'},
  {id:4, time:'2025-03-17 15:35:17', user:'A. Karimov (Admin)',    method:'DELETE', endpoint:'/api/users/7',             status:200, action:'Foydalanuvchi o\'chirildi',           duration:'64ms',  ip:'192.168.1.5'},
  {id:5, time:'2025-03-17 15:30:44', user:'System',                method:'POST',   endpoint:'/api/1c/sync',             status:500, action:'1C sinxronlash xatosi',               duration:'5,200ms',ip:'127.0.0.1'},
  {id:6, time:'2025-03-17 15:28:12', user:'B. Toshmatov (Spec)',   method:'GET',    endpoint:'/api/applications',        status:200, action:'Arizalar ro\'yhati ko\'rildi',        duration:'45ms',  ip:'192.168.1.8'},
  {id:7, time:'2025-03-17 15:22:09', user:'A. Karimov (Admin)',    method:'POST',   endpoint:'/api/users',               status:201, action:'Yangi foydalanuvchi qo\'shildi',      duration:'93ms',  ip:'192.168.1.5'},
  {id:8, time:'2025-03-17 15:18:55', user:'D. Yusupova (Spec)',    method:'PUT',    endpoint:'/api/applications/18/assign',status:200,action:'Ariza tayinlandi',                  duration:'72ms',  ip:'192.168.1.12'},
  {id:9, time:'2025-03-17 15:10:01', user:'System',                method:'GET',    endpoint:'/api/health',              status:200, action:'Health check',                        duration:'12ms',  ip:'127.0.0.1'},
  {id:10,time:'2025-03-17 14:58:33', user:'A. Karimov (Admin)',    method:'POST',   endpoint:'/api/contracts/44/approve', status:200,action:'Shartnoma tasdiqlandi',               duration:'118ms', ip:'192.168.1.5'},
];

function statusColor(code) {
  if (code >= 200 && code < 300) return 'badge-approved';
  if (code >= 400 && code < 500) return 'badge-trial';
  return 'badge-danger';
}

function renderLogs() {
  const tbody = document.getElementById('logs-tbody');
  tbody.innerHTML = logs.map((item,i) => `
    <tr>
      <td>${i+1}</td>
      <td class="mono-cell" style="font-size:11px;">${item.time}</td>
      <td style="font-size:12px;">${item.user}</td>
      <td><span class="log-method ${methodColors[item.method]||'get'}">${item.method}</span></td>
      <td class="mono-cell" style="font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${item.endpoint}">${item.endpoint}</td>
      <td style="text-align:center;"><span class="badge ${statusColor(item.status)}">${item.status}</span></td>
      <td style="font-size:12px;max-width:200px;">${item.action}</td>
      <td style="text-align:center;" class="mono-cell">${item.duration}</td>
      <td class="mono-cell" style="font-size:11px;">${item.ip}</td>
    </tr>
  `).join('');
}

renderLogs();
