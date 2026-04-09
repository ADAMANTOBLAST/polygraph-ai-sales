/**
 * Кастомные выпадающие списки для .module-form select (тёмная тема, без белого нативного popup).
 */
(function () {
  var openWrap = null;

  function closeAll() {
    if (!openWrap) return;
    openWrap.panel.hidden = true;
    openWrap.trigger.setAttribute('aria-expanded', 'false');
    openWrap = null;
  }

  function syncTrigger(wrap) {
    var sel = wrap.querySelector('select');
    var valEl = wrap.querySelector('.fnr-select__value');
    if (!sel || !valEl) return;
    var opt = sel.options[sel.selectedIndex];
    valEl.textContent = opt ? opt.textContent : '—';
  }

  function buildPanel(wrap) {
    var sel = wrap.querySelector('select');
    var panel = wrap.querySelector('.fnr-select__panel');
    if (!sel || !panel) return;
    panel.innerHTML = '';
    Array.prototype.forEach.call(sel.options, function (o) {
      var li = document.createElement('li');
      li.className = 'fnr-select__item';
      li.setAttribute('role', 'option');
      li.setAttribute('data-value', o.value);
      li.textContent = o.textContent;
      li.setAttribute('aria-selected', o.selected ? 'true' : 'false');
      var val = o.value;
      li.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        sel.value = val;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        syncTrigger(wrap);
        Array.prototype.forEach.call(panel.querySelectorAll('.fnr-select__item'), function (node) {
          node.setAttribute('aria-selected', node.getAttribute('data-value') === val ? 'true' : 'false');
        });
        closeAll();
      });
      panel.appendChild(li);
    });
  }

  function enhance(sel) {
    if (!sel || sel.classList.contains('fnr-select__native')) return;

    var wrap = document.createElement('div');
    wrap.className = 'fnr-select';
    sel.parentNode.insertBefore(wrap, sel);

    var trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'fnr-select__trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    var lab = sel.closest('label.field');
    var span = lab && lab.querySelector('span');
    if (span && span.textContent) {
      trigger.setAttribute('aria-label', span.textContent.trim());
    }

    var valSpan = document.createElement('span');
    valSpan.className = 'fnr-select__value';
    var chev = document.createElement('span');
    chev.className = 'fnr-select__chev';
    chev.setAttribute('aria-hidden', 'true');
    chev.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M5 8l5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    trigger.appendChild(valSpan);
    trigger.appendChild(chev);

    var panel = document.createElement('ul');
    panel.className = 'fnr-select__panel';
    panel.setAttribute('role', 'listbox');
    panel.hidden = true;

    sel.classList.add('fnr-select__native');
    sel.setAttribute('tabindex', '-1');
    sel.setAttribute('aria-hidden', 'true');

    wrap.appendChild(trigger);
    wrap.appendChild(panel);
    wrap.appendChild(sel);

    buildPanel(wrap);
    syncTrigger(wrap);

    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (openWrap && openWrap.wrap === wrap) {
        closeAll();
        return;
      }
      closeAll();
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      openWrap = { wrap: wrap, panel: panel, trigger: trigger };
    });

    sel.addEventListener('change', function () {
      syncTrigger(wrap);
      buildPanel(wrap);
    });

    var mo = new MutationObserver(function () {
      buildPanel(wrap);
      syncTrigger(wrap);
    });
    mo.observe(sel, { childList: true, subtree: true });
  }

  function init() {
    document.querySelectorAll('.module-form select').forEach(enhance);
  }

  function syncOne(sel) {
    if (!sel) return;
    var wrap = sel.closest('.fnr-select');
    if (!wrap) return;
    buildPanel(wrap);
    syncTrigger(wrap);
  }

  function syncAll() {
    document.querySelectorAll('.module-form select.fnr-select__native').forEach(function (sel) {
      syncOne(sel);
    });
  }

  document.addEventListener(
    'click',
    function (e) {
      if (!openWrap) return;
      if (openWrap.wrap.contains(e.target)) return;
      closeAll();
    },
    true
  );

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll();
  });

  window.fnrSyncCustomSelect = syncOne;
  window.fnrSyncAllCustomSelects = syncAll;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
