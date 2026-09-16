/* ═══════════════════════════════════════════════
   UZ-KORAM | Xarid Xizmati Bo'limi
   Shared JavaScript v1.0
   ═══════════════════════════════════════════════ */

'use strict';

// The mock Auth object that used to live here was removed by
// TASK-UZK-008. It kept four usernames and passwords in a file served to
// every browser and signed any visitor in as Admin. Django's session
// authentication replaced it; the signed-in user is rendered by the
// server.

// ─── TOAST NOTIFICATIONS ───
const Toast = {
  container: null,

  init() {
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.className = 'toast-container';
      document.body.appendChild(this.container);
    }
  },

  escape(str) {
    return String(str).replace(/[&<>"']/g, c => (
      { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]
    ));
  },

  show(message, type = 'info', duration = 3000) {
    this.init();
    const icons = {
      success: 'bi-check-circle-fill',
      error:   'bi-x-circle-fill',
      info:    'bi-info-circle-fill',
      warning: 'bi-exclamation-triangle-fill',
    };
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <i class="bi ${icons[type] || 'bi-megaphone-fill'}" aria-hidden="true"></i>
      <span>${this.escape(message)}</span>
      <button class="toast-close" aria-label="Yopish" onclick="this.parentElement.remove()"><i class="bi bi-x-lg" aria-hidden="true"></i></button>
    `;
    this.container.appendChild(toast);
    setTimeout(() => {
      toast.style.animation = 'slideOutRight .2s ease forwards';
      setTimeout(() => toast.remove(), 200);
    }, duration);
  },

  success(msg) { this.show(msg, 'success'); },
  error(msg)   { this.show(msg, 'error'); },
  info(msg)    { this.show(msg, 'info'); },
  warning(msg) { this.show(msg, 'warning'); },
};

// ─── MODAL MANAGER ───
const Modal = {
  open(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
  },
  close(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  },
  confirm(title, desc, onConfirm, danger = true) {
    const el = document.getElementById('confirm-modal');
    if (!el) return;
    el.querySelector('.modal-title').textContent = title;
    el.querySelector('.modal-desc').textContent  = desc;
    const btn = el.querySelector('#confirm-ok-btn');
    // Guide §6/§12: destructive actions are outline + text-danger, never a solid red fill.
    btn.className = danger ? 'btn btn-outline-custom text-danger' : 'btn btn-primary-custom';
    btn.onclick = () => { Modal.close('confirm-modal'); onConfirm(); };
    this.open('confirm-modal');
  }
};

// ─── DRAWER MANAGER ───
const Drawer = {
  open(id) {
    const overlay = document.getElementById(id + '-overlay');
    if (overlay) overlay.classList.remove('hidden');
  },
  close(id) {
    const overlay = document.getElementById(id + '-overlay');
    if (overlay) overlay.classList.add('hidden');
  }
};

// ─── SIDEBAR ───
// Mirrors the Texnik Bo'lim module's behaviour (assets/js/app.js) so both
// modules share the `uk-sidebar-collapsed` preference key:
//   >768px  -> toggles body.is-sidebar-collapsed, persisted to localStorage
//   <=768px -> toggles body.is-sidebar-open (off-canvas + backdrop)
// The toggle button and backdrop are injected into <body> so the sidebar's
// own translateX() can never move them off screen.
const Sidebar = {
  init() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;

    try {
      if (localStorage.getItem('uk-sidebar-collapsed') === '1') {
        document.body.classList.add('is-sidebar-collapsed');
      }
    } catch (_) {}

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'sidebar-toggle';
    toggle.setAttribute('aria-label', 'Menyuni ochish/yopish');
    toggle.innerHTML = '<i class="bi bi-list" aria-hidden="true"></i>';
    document.body.appendChild(toggle);

    const backdrop = document.createElement('div');
    backdrop.className = 'sidebar-backdrop';
    document.body.appendChild(backdrop);

    const close = () => document.body.classList.remove('is-sidebar-open');

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      if (window.innerWidth <= 768) {
        document.body.classList.toggle('is-sidebar-open');
      } else {
        const collapsed = document.body.classList.toggle('is-sidebar-collapsed');
        try { localStorage.setItem('uk-sidebar-collapsed', collapsed ? '1' : '0'); } catch (_) {}
      }
    });

    backdrop.addEventListener('click', close);
    sidebar.addEventListener('click', (e) => { if (e.target.closest('a')) close(); });
    window.addEventListener('resize', () => { if (window.innerWidth > 768) close(); });
  }
};

// ─── USER CHIP ───
const UserChip = {
  init() {
    const chip = document.querySelector('.user-chip');
    const menu = document.querySelector('.account-menu');
    if (!chip || !menu) return;

    chip.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.classList.toggle('hidden');
    });

    document.addEventListener('click', () => {
      if (menu) menu.classList.add('hidden');
    });

    // The identity in the chip is rendered by the server. Nothing here
    // rewrites it.
  }
};

// ─── PASSWORD TOGGLE ───
function initPasswordToggle() {
  document.querySelectorAll('.pwd-toggle').forEach(btn => {
    const input = btn.previousElementSibling || btn.closest('.input-group')?.querySelector('input');
    if (!input) return;
    btn.addEventListener('click', () => {
      input.type = input.type === 'password' ? 'text' : 'password';
      const hidden = input.type === 'password';
      btn.innerHTML = `<i class="bi ${hidden ? 'bi-eye' : 'bi-eye-slash'}" aria-hidden="true"></i>`;
      btn.setAttribute('aria-label', hidden ? "Parolni ko'rsatish" : 'Parolni yashirish');
    });
  });
}

// ─── PASSWORD STRENGTH ───
function initPasswordStrength() {
  document.querySelectorAll('.pwd-strength-input').forEach(input => {
    const bars = input.closest('.form-group')?.querySelectorAll('.pwd-strength-bar');
    if (!bars) return;
    input.addEventListener('input', () => {
      const v = input.value;
      let score = 0;
      if (v.length >= 6)  score++;
      if (v.length >= 10) score++;
      if (/[A-Z]/.test(v) && /[0-9]/.test(v)) score++;

      bars.forEach((b, i) => {
        b.className = 'pwd-strength-bar';
        if (i < score) {
          if (score === 1) b.classList.add('weak');
          else if (score === 2) b.classList.add('medium');
          else b.classList.add('strong');
        }
      });
    });
  });
}

// ─── SEARCH / CLIENT-SIDE FILTER ───
function initTableSearch(inputSel, tableSel) {
  const input = document.querySelector(inputSel);
  const rows  = document.querySelectorAll(tableSel + ' tbody tr:not(.total-row)');
  if (!input || !rows.length) return;

  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    rows.forEach(row => {
      const text = row.textContent.toLowerCase();
      row.style.display = text.includes(q) ? '' : 'none';
    });
  });
}

// ─── FORM VALIDATION ───
function validateRequired(formEl) {
  let valid = true;
  formEl.querySelectorAll('[required]').forEach(field => {
    const err = field.parentElement?.querySelector('.form-error');
    if (!field.value.trim()) {
      field.style.borderColor = 'var(--color-danger)';
      if (err) err.textContent = 'Bu maydon to\'ldirilishi shart';
      valid = false;
    } else {
      field.style.borderColor = '';
      if (err) err.textContent = '';
    }
  });
  return valid;
}

// ─── FORMAT CURRENCY ───
function formatCurrency(num) {
  if (!num && num !== 0) return '—';
  return Number(num).toLocaleString('uz-UZ') + ' UZS';
}

// ─── AUTO-CALCULATE TOTAL ───
function initAutoCalc() {
  document.querySelectorAll('.item-row').forEach(row => {
    const qty    = row.querySelector('.calc-qty');
    const price  = row.querySelector('.calc-price');
    const total  = row.querySelector('.calc-total');
    if (!qty || !price || !total) return;

    const calc = () => {
      const q = parseFloat(qty.value) || 0;
      const p = parseFloat(price.value) || 0;
      total.value = (q * p).toLocaleString('uz-UZ');
    };

    qty.addEventListener('input', calc);
    price.addEventListener('input', calc);
  });

  // Grand total
  updateGrandTotal();
}

function updateGrandTotal() {
  const allTotals = document.querySelectorAll('.calc-total');
  const grandEl   = document.querySelector('.grand-total-field');
  if (!grandEl) return;

  let sum = 0;
  allTotals.forEach(t => {
    const val = parseFloat(t.value.replace(/\s/g,'').replace(/,/g,'')) || 0;
    sum += val;
  });
  grandEl.value = formatCurrency(sum);
}

// ─── ADD ITEM ROW ───
function addItemRow(containerId, template) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const row = document.createElement('div');
  row.innerHTML = template;
  container.insertBefore(row.firstChild, container.querySelector('.add-row-btn'));
  initAutoCalc();
}

// ─── FILE UPLOAD PREVIEW ───
function initFileUpload() {
  document.querySelectorAll('.file-upload-area').forEach(area => {
    const input   = area.querySelector('input[type=file]') || area.nextElementSibling;
    const preview = area.closest('.file-upload-wrap')?.querySelector('.file-upload-preview');

    area.addEventListener('click', () => {
      if (input?.type === 'file') input.click();
    });

    area.addEventListener('dragover', e => {
      e.preventDefault();
      area.style.borderColor = 'var(--color-primary)';
      area.style.background  = 'var(--primary-soft)';
    });
    area.addEventListener('dragleave', () => {
      area.style.borderColor = '';
      area.style.background  = '';
    });
    area.addEventListener('drop', e => {
      e.preventDefault();
      area.style.borderColor = '';
      area.style.background  = '';
      const file = e.dataTransfer.files[0];
      if (file) showFilePreview(area, file, preview);
    });

    if (input?.type === 'file') {
      input.addEventListener('change', () => {
        const file = input.files[0];
        if (file) showFilePreview(area, file, preview);
      });
    }
  });
}

function showFilePreview(area, file, previewEl) {
  if (!previewEl) return;
  previewEl.innerHTML = `
    <i class="bi bi-file-earmark" aria-hidden="true"></i>
    <span>${Toast.escape(file.name)}</span>
    <span class="small text-muted">(${(file.size/1024).toFixed(1)} KB)</span>
    <button class="remove-btn" aria-label="Faylni olib tashlash" onclick="this.closest('.file-upload-wrap').querySelector('.file-upload-preview').innerHTML='';this.closest('.file-upload-wrap').querySelector('.file-upload-area').style.display=''"><i class="bi bi-x-lg" aria-hidden="true"></i></button>
  `;
  area.style.display = 'none';
}

// ─── PAGINATION ───
const Pagination = {
  init(totalRows = 30, perPage = 10) {
    const wrap = document.querySelector('.pagination-wrap');
    if (!wrap) return;

    const totalPages = Math.ceil(totalRows / perPage);
    let current = 1;

    const render = () => {
      const btns = wrap.querySelectorAll('.page-btn');
      btns.forEach(b => {
        const p = parseInt(b.dataset.page);
        b.className = `btn btn-sm ${p === current ? 'btn-primary-custom' : 'btn-outline-custom'} page-btn`;
      });
      const info = wrap.querySelector('.pagination-info .count');
      if (info) info.textContent = totalRows;
    };

    wrap.querySelectorAll('.page-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const p = parseInt(btn.dataset.page);
        if (p >= 1 && p <= totalPages) {
          current = p;
          render();
        }
      });
    });

    wrap.querySelector('.prev-btn')?.addEventListener('click', () => {
      if (current > 1) { current--; render(); }
    });
    wrap.querySelector('.next-btn')?.addEventListener('click', () => {
      if (current < totalPages) { current++; render(); }
    });

    render();
  }
};

// ─── SORTING ───
function initTableSort() {
  // Paint the indicator for one header from its asc/desc state.
  const paint = (h) => {
    const icon = h.querySelector('.sort-icon');
    if (!icon) return;
    const dir = h.classList.contains('asc') ? 'bi-arrow-up'
              : h.classList.contains('desc') ? 'bi-arrow-down'
              : 'bi-arrow-down-up';
    icon.className = `sort-icon bi ${dir}`;
  };

  document.querySelectorAll('.table-app th.sortable').forEach(th => {
    th.innerHTML += '<i class="sort-icon bi bi-arrow-down-up" aria-hidden="true"></i>';
    th.addEventListener('click', () => {
      const table  = th.closest('table');
      const col    = Array.from(th.parentElement.children).indexOf(th);
      const isAsc  = th.classList.contains('asc');

      table.querySelectorAll('th.sortable').forEach(h => {
        h.classList.remove('asc', 'desc');
        paint(h);
      });
      th.classList.add(isAsc ? 'desc' : 'asc');
      paint(th);

      const tbody = table.querySelector('tbody');
      const rows  = Array.from(tbody.querySelectorAll('tr:not(.total-row)'));
      rows.sort((a, b) => {
        const av = a.cells[col]?.textContent.trim() || '';
        const bv = b.cells[col]?.textContent.trim() || '';
        const an = parseFloat(av.replace(/[^\d.]/g,''));
        const bn = parseFloat(bv.replace(/[^\d.]/g,''));
        if (!isNaN(an) && !isNaN(bn)) return isAsc ? bn - an : an - bn;
        return isAsc ? bv.localeCompare(av, 'uz') : av.localeCompare(bv, 'uz');
      });
      rows.forEach(r => tbody.appendChild(r));

      // Re-attach total row at bottom
      const totalRow = tbody.querySelector('.total-row');
      if (totalRow) tbody.appendChild(totalRow);
    });
  });
}

// ─── COLOUR BADGE PREVIEW ───
function initColorBadgePreview() {
  const nameInput  = document.getElementById('status-name-input');
  const colorInput = document.getElementById('status-color-input');
  const preview    = document.getElementById('status-badge-preview');
  if (!nameInput || !preview) return;

  const update = () => {
    const text  = nameInput.value || 'Status nomi';
    const color = colorInput?.value || '#DF5830';
    preview.textContent   = text;
    preview.style.background = color + '22';
    preview.style.color      = color;
    preview.style.border     = `1px solid ${color}44`;
  };

  nameInput.addEventListener('input', update);
  if (colorInput) colorInput.addEventListener('input', update);
  update();
}

// ─── EDIT PERMISSION MUTEX ───
function initEditPermissionToggle() {
  document.querySelectorAll('.edit-permission-toggle').forEach(toggle => {
    toggle.addEventListener('change', function() {
      if (!this.checked) return;
      const userId = this.dataset.userId;
      const userName = this.dataset.userName;

      // Find other active toggles
      const others = document.querySelectorAll(`.edit-permission-toggle:not([data-user-id="${userId}"])`);
      const activeOther = Array.from(others).find(t => t.checked);

      if (activeOther) {
        Modal.confirm(
          'Ruxsat o\'zgarishi',
          `Bu amal ${activeOther.dataset.userName}ga tahrirlash ruhsatini bekor qiladi. Davom etasizmi?`,
          () => {
            others.forEach(t => t.checked = false);
            Toast.warning(`${activeOther.dataset.userName} ruxsati bekor qilindi`);
            Toast.success(`${userName}ga tahrirlash ruxsati berildi`);
          }
        );
        this.checked = false; // revert until confirmed
      }
    });
  });
}

// ─── INLINE STATUS CHANGE ───
function initStatusDropdowns() {
  document.querySelectorAll('.status-dropdown').forEach(sel => {
    sel.addEventListener('change', function() {
      Toast.success('Holat muvaffaqiyatli saqlandi');
    });
  });
}

// ─── CHART INIT (Chart.js) ───
const Charts = {
  spendingChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === 'undefined') return;
    new Chart(ctx, {
      type: 'line',
      data: {
        labels: ['Yan','Feb','Mar','Apr','May','Iyn','Iyl','Avg','Sen','Okt','Noy','Dek'],
        datasets: [
          {
            label: 'Sarf (M UZS)',
            data: [85,102,98,120,110,135,118,142,125,155,130,168],
            borderColor: '#DF5830',
            backgroundColor: 'rgba(223,88,48,.08)',
            fill: true,
            tension: 0.35,
            pointBackgroundColor: '#DF5830',
            pointRadius: 3,
          },
          {
            label: 'Tejaldi (M UZS)',
            data: [8,10,9,14,12,16,11,18,13,20,15,22],
            borderColor: '#2E7D32',
            backgroundColor: 'rgba(46,125,50,.06)',
            fill: true,
            tension: 0.35,
            pointBackgroundColor: '#2E7D32',
            pointRadius: 3,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { family: 'Inter', size: 11 }, padding: 16 } } },
        scales: {
          x: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 11 } } },
          y: { grid: { color: '#DFE2C1' }, ticks: { font: { family: 'Inter', size: 11 }, callback: v => v + 'M' } }
        }
      }
    });
  },

  categoryBarChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === 'undefined') return;
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Metallurgiya','Kimyoviy','Elektr','Qurilish','Yoqilg\'i','Boshqa'],
        datasets: [{
          label: 'Yetkazib beruvchilar',
          data: [48, 36, 52, 28, 22, 62],
          backgroundColor: ['#DF5830','#F97316','#4B5563','#2E7D32','#C67A00','#666054'],
          borderRadius: 6,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: '#DFE2C1' }, ticks: { font: { family: 'Inter', size: 11 } } },
          y: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 11 } } }
        }
      }
    });
  }
};

// NOTE: nav active state is owned by buildSidebar() in js/sidebar.js.
// The former setActiveNav() here competed with it and stripped the icon
// class off the active item — removed rather than ported.

// ─── GLOBAL INIT ───
document.addEventListener('DOMContentLoaded', () => {
  Sidebar.init();
  UserChip.init();
  initPasswordToggle();
  initPasswordStrength();
  initTableSort();
  initFileUpload();
  initEditPermissionToggle();
  initStatusDropdowns();
  initColorBadgePreview();

  // Confirm modal close buttons
  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => Modal.close(btn.dataset.closeModal));
  });

  // Drawer close buttons
  document.querySelectorAll('[data-close-drawer]').forEach(btn => {
    btn.addEventListener('click', () => Drawer.close(btn.dataset.closeDrawer));
  });

  initConfirmedForms();

  // Logout is a form posting to the server; there is nothing to bind here.
});

// ─── FORMS THAT ASK BEFORE THEY SUBMIT ───
// A form carrying data-confirm asks the question in that attribute before it
// submits. The question lives in an attribute rather than in an inline
// onsubmit handler because a server-rendered name has to be escaped for one
// context or the other, and it cannot be both: the browser decodes character
// references in an attribute value before the JavaScript engine reads the
// source, so a name containing an apostrophe would close the string literal.
// The same decoding is exactly right for an attribute the handler reads back.
//
// Delegated from the document so rows rendered after load are covered too.
function initConfirmedForms() {
  document.addEventListener('submit', (event) => {
    const form = event.target.closest('form[data-confirm]');
    if (form && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
}

// ─── SHARED CONFIRM MODAL HTML ─── (injected on every page)
(function injectGlobalElements() {
  // Confirm modal
  if (!document.getElementById('confirm-modal')) {
    const modal = document.createElement('div');
    modal.id = 'confirm-modal';
    modal.className = 'modal-overlay hidden';
    modal.innerHTML = `
      <div class="modal-box">
        <div class="modal-title"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i> Tasdiqlash</div>
        <div class="modal-desc"></div>
        <div class="modal-footer">
          <button class="btn btn-outline-custom" data-close-modal="confirm-modal">Bekor</button>
          <button id="confirm-ok-btn" class="btn btn-outline-custom text-danger">Ha, davom</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    modal.querySelector('[data-close-modal]').addEventListener('click', () => {
      Modal.close('confirm-modal');
    });
  }
})();
