/* ═══════════════════════════════════════════════
   UZ-KORAM | Xarid Xizmati Bo'limi
   Shared JavaScript
   ═══════════════════════════════════════════════ */

'use strict';

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
//   >768px  -> toggles body.is-sidebar-collapsed, persisted to localStorage
//   <=768px -> toggles body.is-sidebar-open (off-canvas + backdrop)
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
// An input carrying data-table-search="#table" filters that table's rows.
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

function initTableSearchInputs() {
  document.querySelectorAll('[data-table-search]').forEach(input => {
    initTableSearch(`#${input.id}`, input.dataset.tableSearch);
  });
}

// ─── SORTING ───
function initTableSort() {
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

      const totalRow = tbody.querySelector('.total-row');
      if (totalRow) tbody.appendChild(totalRow);
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

  /* The supplier category chart, drawn from the rows the table beside it
     shows. They come from a JSON script element rather than from this file,
     so the chart and the table cannot say different things. */
  categoryBarChart(canvasId, dataId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === 'undefined') return;

    const source = dataId && document.getElementById(dataId);
    if (!source) return;

    let rows = [];
    try {
      rows = JSON.parse(source.textContent) || [];
    } catch (unreadable) {
      return;
    }
    if (!rows.length) return;

    const palette = ['#DF5830', '#F97316', '#4B5563', '#2E7D32', '#C67A00', '#666054'];
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(row => row.label),
        datasets: [{
          label: 'Yetkazib beruvchilar',
          data: rows.map(row => row.firms),
          backgroundColor: rows.map((row, index) => palette[index % palette.length]),
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

// ─── FORMS THAT ASK BEFORE THEY SUBMIT ───
// A form carrying data-confirm asks the question in that attribute before it
// submits. The question lives in an attribute rather than in an inline
// onsubmit handler: the browser decodes character references in an attribute
// value before the JavaScript engine reads the source, so a name containing
// an apostrophe would close a string literal. Delegated from the document so
// rows rendered after load are covered too.
function initConfirmedForms() {
  document.addEventListener('submit', (event) => {
    const form = event.target.closest('form[data-confirm]');
    if (form && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
}

// ─── ONE MODAL FORM PER PAGE, POINTED AT A ROW ───
// A button carrying data-modal-form="modal-id" opens that modal, points its
// form at data-action-url, and copies every data-fill-<name> attribute into
// the modal element carrying data-fill="<name>". Values travel on the button
// as data attributes and never reach JavaScript source, so a list of two
// hundred rows renders one dialog rather than two hundred.
function initModalForms() {
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-modal-form]');
    if (!button) return;

    const modal = document.getElementById(button.dataset.modalForm);
    if (!modal) return;

    const form = modal.querySelector('form');
    form.action = button.dataset.actionUrl;
    form.reset();

    modal.querySelectorAll('[data-fill]').forEach((target) => {
      target.textContent = button.getAttribute(`data-fill-${target.dataset.fill}`) || '';
    });

    Modal.open(modal.id);
    const firstField = modal.querySelector('textarea, select, input:not([type=hidden])');
    if (firstField) firstField.focus();
  });
}

// ─── FORMSET ROW ADDER ───
// The plus button of the three order-line forms. A button carrying
// data-add-row clones the <template> named by data-row-template into the
// container named by data-row-container, replacing __prefix__ - the index
// placeholder Django writes into empty_form - with the next index, and bumps
// the formset's TOTAL_FORMS. The clone is a DOM one and the index is written
// into attributes, so no HTML is parsed at runtime.
const ROW_INDEX_PLACEHOLDER = /__prefix__/g;

function initFormsetRowAdders() {
  document.querySelectorAll('[data-add-row]').forEach((button) => {
    button.addEventListener('click', () => {
      const total = document.getElementById(button.dataset.totalForms);
      const container = document.getElementById(button.dataset.rowContainer);
      const template = document.getElementById(button.dataset.rowTemplate);
      if (!total || !container || !template) return;

      const index = Number(total.value);
      const row = template.content.cloneNode(true);

      row.querySelectorAll('[name], [id], [for]').forEach((field) => {
        ['name', 'id', 'for'].forEach((attribute) => {
          const value = field.getAttribute(attribute);
          if (value) {
            field.setAttribute(attribute, value.replace(ROW_INDEX_PLACEHOLDER, index));
          }
        });
      });

      container.appendChild(row);
      total.value = index + 1;
      container.dispatchEvent(new CustomEvent('rows:changed', { bubbles: true }));
    });
  });
}

// ─── CONTRACT ENTRY: LINE TOTALS AND THE FIRM'S INN ───
// Display only: the server computes every total again from the posted rows.
function soum(amount) {
  const fixed = amount.toFixed(2);
  const [whole, fraction] = fixed.split('.');
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ',' + fraction;
}

function initContractCalculator() {
  const form = document.querySelector('[data-contract-form]');
  if (!form) return;

  const rows = form.querySelector('[data-contract-rows]');
  const contractValue = form.querySelector('[data-contract-value]');

  const recalculate = () => {
    let total = 0;
    rows.querySelectorAll('.js-sht-qator').forEach((row) => {
      const quantity = Number(row.querySelector('.js-qator-soni').value);
      const price = Number(row.querySelector('.js-qator-narxi').value);
      const lineTotal = quantity > 0 && price > 0 ? quantity * price : 0;
      row.querySelector('.js-qator-jami').value = soum(lineTotal);
      total += lineTotal;
    });
    contractValue.value = soum(total);
  };

  rows.addEventListener('input', (event) => {
    if (event.target.matches('.js-qator-soni, .js-qator-narxi')) recalculate();
  });
  rows.addEventListener('rows:changed', recalculate);

  // The INN is copied from the chosen firm rather than typed (DEC-011): the
  // option carries it.
  const firmaSelect = form.querySelector('[data-inn-source] select');
  const firmaInn = form.querySelector('[data-inn-target]');
  if (firmaSelect && firmaInn) {
    const showInn = () => {
      const chosen = firmaSelect.selectedOptions[0];
      firmaInn.value = (chosen && chosen.dataset.inn) || '';
    };
    firmaSelect.addEventListener('change', showInn);
    showInn();
  }

  recalculate();
}

// ─── GLOBAL INIT ───
document.addEventListener('DOMContentLoaded', () => {
  Sidebar.init();
  UserChip.init();
  initPasswordToggle();
  initPasswordStrength();
  initTableSort();
  initTableSearchInputs();
  initConfirmedForms();
  initModalForms();
  initFormsetRowAdders();
  initContractCalculator();

  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => Modal.close(btn.dataset.closeModal));
  });

  document.querySelectorAll('[data-open-modal]').forEach(btn => {
    btn.addEventListener('click', () => Modal.open(btn.dataset.openModal));
  });

  document.querySelectorAll('[data-close-drawer]').forEach(btn => {
    btn.addEventListener('click', () => Drawer.close(btn.dataset.closeDrawer));
  });
});

// ─── SHARED CONFIRM MODAL HTML ─── (injected on every page)
(function injectGlobalElements() {
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
