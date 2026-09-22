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
    btn.type = 'button';
    // Keep the caret in the field: without this the button steals focus on press.
    btn.addEventListener('mousedown', e => e.preventDefault());
    btn.addEventListener('click', () => {
      const focused = document.activeElement === input;
      const start = input.selectionStart;
      const end = input.selectionEnd;
      input.type = input.type === 'password' ? 'text' : 'password';
      const hidden = input.type === 'password';
      btn.innerHTML = `<i class="bi ${hidden ? 'bi-eye' : 'bi-eye-slash'}" aria-hidden="true"></i>`;
      btn.setAttribute('aria-label', hidden ? "Parolni ko'rsatish" : 'Parolni yashirish');
      btn.setAttribute('aria-pressed', hidden ? 'false' : 'true');
      if (focused) {
        input.focus();
        if (start !== null) {
          try { input.setSelectionRange(start, end); } catch (_) { /* unsupported input type */ }
        }
      }
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

// ─── PHONE NUMBER MASK ───
// The nine digits after the +998 the page prints beside the field, grouped
// the way the empty field promises: __-___-__-__ becomes 90-123-45-67.
const PHONE_GROUPS = [2, 3, 2, 2];
const PHONE_DIGITS = PHONE_GROUPS.reduce((total, size) => total + size, 0);

function groupedPhone(digits) {
  const parts = [];
  let at = 0;
  for (const size of PHONE_GROUPS) {
    if (at >= digits.length) break;
    parts.push(digits.substring(at, at + size));
    at += size;
  }
  return parts.join('-');
}

function initPhoneMask() {
  document.querySelectorAll('[data-phone-mask]').forEach(input => {
    const reformat = () => {
      const before = input.value;
      const caret = input.selectionStart === null ? before.length : input.selectionStart;
      const typedBeforeCaret = before.substring(0, caret).replace(/\D/g, '').length;

      let digits = before.replace(/\D/g, '');
      // A pasted +998901234567 carries the code the page already prints.
      if (digits.length > PHONE_DIGITS && digits.startsWith('998')) digits = digits.substring(3);
      const formatted = groupedPhone(digits.substring(0, PHONE_DIGITS));
      if (formatted === before) return;

      input.value = formatted;
      // Leave the caret after the same digit, not at the end of the field.
      let seen = 0;
      let position = typedBeforeCaret === 0 ? 0 : formatted.length;
      for (let i = 0; i < formatted.length && typedBeforeCaret > 0; i++) {
        if (/\d/.test(formatted[i])) seen++;
        if (seen === typedBeforeCaret) { position = i + 1; break; }
      }
      try { input.setSelectionRange(position, position); } catch (_) { /* unsupported */ }
    };

    input.addEventListener('input', reformat);
    // An edit form opens with a number in it, and an old one may hold spaces.
    reformat();
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
//
// The button that submitted may carry its own question and is asked first.
// One form can have two submits - Kelishinlingan's Saqlash and Yuborish
// share a row's drop-down, so they share its form - and there the question
// belongs to the irreversible one rather than to both.
function initConfirmedForms() {
  document.addEventListener('submit', (event) => {
    const form = event.target.closest('form');
    if (!form) return;

    const asked = (event.submitter && event.submitter.dataset.confirm)
      || form.dataset.confirm;
    if (asked && !window.confirm(asked)) {
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

// ─── THE KO'RISH SLIDE-OVER, FILLED FROM THE SERVER ───
// A button carrying data-detail-url opens the contract drawer and fills it
// with what that address returns. The markup is rendered by the server and
// not built here: eight labelled fields and a table of goods would
// otherwise be a second copy of the page's own template, in another
// language, drifting from it.
//
// Fetched rather than rendered into every row for the reason initModalForms
// gives: a list of two hundred contracts carries one panel.
//
// Drawer.open takes the name the overlay's id is built from, not the id.
const DETAIL_DRAWER = 'sht-tafsilot';

function initDetailDrawer() {
  const overlay = document.getElementById(DETAIL_DRAWER + '-overlay');
  if (!overlay) return;

  const heading = overlay.querySelector('[data-detail-title]');
  const body = overlay.querySelector('[data-detail-body]');

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-detail-url]');
    if (!button) return;

    // textContent, so a firma name with an apostrophe in it is a name.
    heading.textContent = button.dataset.detailTitle || 'Tafsilotlar';
    body.textContent = 'Yuklanmoqda...';
    // Scrolled back to the top: the panel is reused, and a contract opened
    // after a long one would otherwise start halfway down.
    body.scrollTop = 0;
    Drawer.open(DETAIL_DRAWER);

    fetch(button.dataset.detailUrl, { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) throw new Error(response.status);
        return response.text();
      })
      .then((markup) => { body.innerHTML = markup; })
      .catch(() => { body.textContent = "Tafsilotlarni yuklab bo'lmadi."; });
  });
}

// ─── REMOVING A ROW OF GOODS ───
// The trash button beside a row hides it and ticks the DELETE box the
// formset renders, which is what the server reads. Hidden rather than
// removed from the document: a formset counts its forms, and a form taken
// out from under it is missing data rather than a row somebody deleted.
//
// The last row standing cannot go. A contract needs one row of goods
// (REQ-SHARTNOMA-007), so a form that let somebody remove the last one
// would be a form that can only be refused on submit.
const ROW = '.js-sht-qator';

function livingRows(container) {
  return Array.from(container.querySelectorAll(ROW)).filter((row) => !row.hidden);
}

// The button on the only remaining row is disabled rather than missing, so
// that a row count going up and down does not make controls appear and
// disappear under the pointer.
function refreshRowRemovers(container) {
  const alone = livingRows(container).length <= 1;
  livingRows(container).forEach((row) => {
    const button = row.querySelector('[data-remove-row]');
    if (button) {
      button.disabled = alone;
      button.title = alone
        ? "Kamida bitta qator bo'lishi kerak"
        : "Qatorni o'chirish";
    }
  });
}

function initRowRemovers() {
  document.querySelectorAll('[data-contract-rows]').forEach(refreshRowRemovers);

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-row]');
    if (!button || button.disabled) return;

    const row = button.closest(ROW);
    const container = row && row.closest('[data-contract-rows]');
    if (!container || livingRows(container).length <= 1) return;

    const tick = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
    if (tick) tick.checked = true;
    row.hidden = true;

    refreshRowRemovers(container);
    // The contract value is the sum of the rows that are left.
    container.dispatchEvent(new CustomEvent('rows:changed', { bubbles: true }));
  });
}

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
      refreshRowRemovers(container);
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
      // A row the trash button removed is still in the document, holding
      // the tick that tells the server to drop it. It is not part of what
      // the contract comes to.
      if (row.hidden) return;

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
  // suggestion carries it. Matched on the name in the box rather than on a
  // selected option, because the box is typed into as well as picked from -
  // so a half-typed name simply shows no INN until it is a whole one.
  const firmaSource = form.querySelector('[data-inn-source]');
  const firmaInput = firmaSource && firmaSource.querySelector('input');
  const firmaInn = form.querySelector('[data-inn-target]');
  if (firmaInput && firmaInn) {
    const firms = Array.from(firmaSource.querySelectorAll('.combo-option'));
    const showInn = () => {
      const typed = firmaInput.value.trim().toLowerCase();
      const chosen = firms.find(firm => firm.dataset.value.toLowerCase() === typed);
      firmaInn.value = (chosen && chosen.dataset.inn) || '';
    };
    firmaInput.addEventListener('input', showInn);
    // Picking from the list sets the value in code, which fires no input
    // event of its own; the combo dispatches change for exactly this.
    firmaInput.addEventListener('change', showInn);
    showInn();
  }

  recalculate();
}

// ─── GLOBAL INIT ───
// ─── TYPE-AHEAD COMBO ───
// The list a <datalist> would have shown, drawn in the page so the stylesheet
// can say how tall it is. Progressive: with no JS the list stays hidden and
// the box is still a text field the server matches, which is where the real
// check lives anyway.

function comboMatches(option, query) {
  return option.textContent.toLowerCase().includes(query);
}

function initCombo(combo) {
  const input = combo.querySelector('input');
  const list  = combo.querySelector('[data-combo-list]');
  if (!input || !list) return;

  const options = Array.from(list.querySelectorAll('.combo-option'));
  let shown = [];

  const close = () => {
    list.classList.add('hidden');
    input.setAttribute('aria-expanded', 'false');
  };

  const highlight = option => {
    options.forEach(each => each.classList.toggle('is-active', each === option));
    // Keeps the highlighted row inside the five that are visible.
    if (option) option.scrollIntoView({ block: 'nearest' });
  };

  const open = () => {
    const query = input.value.trim().toLowerCase();
    shown = options.filter(option => {
      const matches = comboMatches(option, query);
      option.hidden = !matches;
      return matches;
    });

    // Nothing to suggest is not worth an empty box in the way of the form.
    if (!shown.length) return close();

    list.classList.remove('hidden');
    input.setAttribute('aria-expanded', 'true');
    // Keep the highlight where it was if that row still matches, so typing
    // another character does not throw away where the reader had got to.
    highlight(shown.find(option => option.classList.contains('is-active')) || shown[0]);
  };

  const choose = option => {
    input.value = option.dataset.value;
    close();
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };

  input.addEventListener('input', open);
  input.addEventListener('focus', open);
  input.addEventListener('blur', () => window.setTimeout(close, 0));

  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') return close();
    if (event.key === 'Enter' && !list.classList.contains('hidden')) {
      const active = shown.find(option => option.classList.contains('is-active'));
      if (active) {
        event.preventDefault();
        choose(active);
      }
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;

    event.preventDefault();
    if (list.classList.contains('hidden')) return open();

    const at = shown.findIndex(option => option.classList.contains('is-active'));
    const step = event.key === 'ArrowDown' ? 1 : -1;
    highlight(shown[(at + step + shown.length) % shown.length]);
  });

  options.forEach(option => {
    // mousedown rather than click: the input's blur would otherwise close the
    // list before the click landed, and the pick would be lost.
    option.addEventListener('mousedown', event => {
      event.preventDefault();
      choose(option);
    });
  });
}

function initCombos() {
  document.querySelectorAll('[data-combo]').forEach(initCombo);
}

document.addEventListener('DOMContentLoaded', () => {
  Sidebar.init();
  UserChip.init();
  initPasswordToggle();
  initPasswordStrength();
  initPhoneMask();
  initTableSort();
  initTableSearchInputs();
  initConfirmedForms();
  initModalForms();
  initDetailDrawer();
  initFormsetRowAdders();
  initRowRemovers();
  initContractCalculator();
  initCombos();

  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => Modal.close(btn.dataset.closeModal));
  });

  document.querySelectorAll('[data-open-modal]').forEach(btn => {
    btn.addEventListener('click', () => Modal.open(btn.dataset.openModal));
  });

  document.querySelectorAll('[data-open-drawer]').forEach(btn => {
    btn.addEventListener('click', () => Drawer.open(btn.dataset.openDrawer));
  });

  document.querySelectorAll('[data-close-drawer]').forEach(btn => {
    btn.addEventListener('click', () => Drawer.close(btn.dataset.closeDrawer));
  });

  // Clicking the dimmed area beside a drawer closes it; clicking inside the
  // panel bubbles up to the same overlay, so only the overlay itself counts.
  document.querySelectorAll('.drawer-overlay').forEach(overlay => {
    overlay.addEventListener('click', event => {
      if (event.target === overlay) overlay.classList.add('hidden');
    });
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

// ─── TABLE PAGER ───
// The row count applies when it is chosen, rather than waiting for a button
// nobody expects beside a drop-down. The button stays in the markup for a
// reader without JavaScript; .js-on tells the stylesheet to hide it, and is
// set here so the button is only ever hidden where something replaces it.
(function pagerRowCount() {
  document.documentElement.classList.add('js-on');

  document.addEventListener('change', (event) => {
    const select = event.target.closest('[data-rows-form] select');
    if (select) {
      select.form.submit();
    }
  });
})();

// ─── LANGUAGE PICKER ───
// The same open-and-close-on-outside-click the account chip has. Written as
// its own listener rather than shared with it so that opening one closes the
// other, which is what a reader expects of two menus in one bar.
(function languagePicker() {
  const chip = document.querySelector('[data-language-chip]');
  const menu = document.querySelector('[data-language-menu]');
  if (!chip || !menu) return;

  chip.addEventListener('click', (event) => {
    event.stopPropagation();
    menu.classList.toggle('hidden');
    document.querySelector('.account-menu:not(.language-menu)')?.classList.add('hidden');
  });

  document.addEventListener('click', () => menu.classList.add('hidden'));
})();
