/* ─── SIDEBAR BUILDER ─── */
/* Call buildSidebar() after DOM is ready */

function buildSidebar() {
  const user = Auth.requireAuth();
  const role = user?.role || 'Admin';
  const isAdmin  = role === 'Admin';
  const isMgr    = role === 'Admin' || role === 'Manager';
  const isSpec   = role === 'Specialist';
  const isDir    = role === 'Director';

  const nav = [
    { group: 'Umumiy' },
    { label: 'Dashboard',          icon: 'bi-speedometer2',       href: 'dashboard.html',          show: isMgr || isDir },
    { group: 'Ma\'lumotlar' },
    { label: 'User Specialty',     icon: 'bi-mortarboard',        href: 'user-specialty.html',     show: isAdmin },
    { label: 'User Types',         icon: 'bi-person-badge',       href: 'user-types.html',         show: isAdmin },
    { label: 'Foydalanuvchilar',   icon: 'bi-people',             href: 'users.html',              show: isAdmin },
    { label: 'Ariza Status',       icon: 'bi-flag',               href: 'ariza-status.html',       show: isAdmin },
    { label: 'Shartnoma Status',   icon: 'bi-clipboard-check',    href: 'shartnoma-status.html',   show: isAdmin },
    { label: 'Mahsulot Turlari',   icon: 'bi-collection',         href: 'mahsulot-turlari.html',   show: isAdmin },
    { label: 'Shartnoma Turi',     icon: 'bi-file-earmark-text',  href: 'shartnoma-turi.html',     show: isAdmin },
    { group: 'Arizalar' },
    { label: 'Kelib Tushgan',      icon: 'bi-inbox',              href: 'kelib-arizalar.html',     show: isMgr },
    { label: 'Qabul Qilingan',     icon: 'bi-check2-circle',      href: 'qabul-arizalar.html',     show: isMgr },
    { label: 'Tayinlangan',        icon: 'bi-pin-angle',          href: 'tayinlangan.html',        show: isMgr || isSpec },
    { group: 'Shartnomalar' },
    { label: 'Kelishinlingan',     icon: 'bi-file-earmark-check', href: 'kelishinlingan.html',     show: isMgr || isSpec },
    { label: 'Tuzilgan',           icon: 'bi-journal-text',       href: 'tuzilgan.html',           show: isMgr },
    { group: 'Hisobotlar' },
    { label: 'Xodimlar Yuklamasi', icon: 'bi-graph-up-arrow',     href: 'xodimlar-yuklamasi.html', show: isAdmin },
    { label: 'Bo\'limlar',         icon: 'bi-buildings',          href: 'bolimlar.html',           show: isAdmin },
    { label: 'Mahsulot Turi',      icon: 'bi-box-seam',           href: 'mahsulot-tur.html',       show: isAdmin },
    { label: 'Mahsulotlar',        icon: 'bi-search',             href: 'mahsulotlar.html',        show: isAdmin },
    { label: 'Xarid Arizasi',      icon: 'bi-cart3',              href: 'xarid-ariza.html',        show: isSpec || isMgr },
    { group: 'Tizim' },
    { label: '1C Integratsiya',    icon: 'bi-plug',               href: 'integration.html',        show: isAdmin },
    { label: 'Logs',               icon: 'bi-journal-code',       href: 'logs.html',               show: isAdmin },
  ];

  const sidebarEl = document.querySelector('.sidebar');
  if (!sidebarEl) return;

  // Build nav HTML. A group label is emitted only when at least one of the
  // entries that follow it (up to the next group) is visible for this role —
  // otherwise Manager/Specialist/Director see empty section headings.
  const html = nav.map((item, i) => {
    if (item.group) {
      let hasVisibleChild = false;
      for (let j = i + 1; j < nav.length && !nav[j].group; j++) {
        if (nav[j].show) { hasVisibleChild = true; break; }
      }
      return hasVisibleChild ? `<div class="nav-section-label">${item.group}</div>` : '';
    }
    if (!item.show) return '';
    const active = window.location.pathname.endsWith(item.href) ? 'active' : '';
    return `<a href="${item.href}" class="nav-link ${active}">` +
             `<i class="bi ${item.icon}" aria-hidden="true"></i>` +
             `<span class="label-text">${item.label}</span>` +
           `</a>`;
  }).join('');

  const navEl = sidebarEl.querySelector('.sidebar-nav');
  if (navEl) navEl.innerHTML = html;

  // Fill footer user info
  const av     = sidebarEl.querySelector('.sidebar-avatar');
  const nameEl = sidebarEl.querySelector('.sidebar-user-info .name');
  const roleEl = sidebarEl.querySelector('.sidebar-user-info .role');
  if (av)     av.textContent     = user?.initials || 'U';
  if (nameEl) nameEl.textContent = user?.name || 'Foydalanuvchi';
  if (roleEl) roleEl.textContent = user?.role || '';
}

document.addEventListener('DOMContentLoaded', buildSidebar);
