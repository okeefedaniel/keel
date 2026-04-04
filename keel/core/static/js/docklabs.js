/**
 * DockLabs Design System — Shared JavaScript
 * Used by: Beacon, Harbor, Lookout, and all DockLabs products.
 * Requires: Bootstrap 5.3+
 *
 * Products include this via Keel's static files:
 *   <script src="{% static 'js/docklabs.js' %}"></script>
 *
 * Products keep their own app-specific JS (e.g., beacon.js) for
 * domain-specific behavior.
 */
(function () {
  'use strict';

  // =========================================================================
  // 1. Auto-dismiss alerts after 5 seconds
  // =========================================================================
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.alert-dismissible').forEach(function (el) {
      setTimeout(function () {
        try {
          var bsAlert = bootstrap.Alert.getOrCreateInstance(el);
          bsAlert.close();
        } catch (e) { /* bootstrap not loaded yet */ }
      }, 5000);
    });
  });

  // =========================================================================
  // 2. HTMX CSRF token injection
  // =========================================================================
  document.body.addEventListener('htmx:configRequest', function (event) {
    var token = getCookie('csrftoken');
    if (!token) {
      var el = document.querySelector('[name=csrfmiddlewaretoken]');
      if (el) token = el.value;
    }
    if (token) {
      event.detail.headers['X-CSRFToken'] = token;
    }
  });

  // =========================================================================
  // 3. Button loading states on form submit
  // =========================================================================
  // Uses requestAnimationFrame to defer disable so the form POST isn't cancelled.
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form || form.tagName !== 'FORM') return;

    var buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    buttons.forEach(function (btn) {
      if (btn.disabled || btn.hasAttribute('data-no-loading')) return;

      btn.setAttribute('data-original-html', btn.innerHTML);

      requestAnimationFrame(function () {
        btn.disabled = true;
        btn.classList.add('btn-loading');
        var loadingText = btn.getAttribute('data-loading-text') || 'Processing\u2026';
        btn.innerHTML =
          '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
          loadingText;
      });
    });
  });

  // =========================================================================
  // 4. Confirmation prompts for destructive actions
  // =========================================================================
  // Usage: <a href="/delete/1/" data-confirm="Are you sure?">Delete</a>
  document.addEventListener('click', function (event) {
    var el = event.target.closest('[data-confirm]');
    if (el && !confirm(el.dataset.confirm)) {
      event.preventDefault();
      event.stopPropagation();
    }
  });

  // =========================================================================
  // 5. Bootstrap tooltip activation
  // =========================================================================
  document.addEventListener('DOMContentLoaded', function () {
    var els = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    els.forEach(function (el) {
      new bootstrap.Tooltip(el);
    });
  });

  // =========================================================================
  // 6. Clickable table rows
  // =========================================================================
  // Usage: <tr data-href="/detail/1/">...</tr> on a .table-clickable table
  document.addEventListener('click', function (event) {
    var row = event.target.closest('.table-clickable tbody tr[data-href]');
    if (row && !event.target.closest('a, button, input')) {
      window.location.href = row.dataset.href;
    }
  });

  // =========================================================================
  // 7. Bootstrap 5 client-side form validation
  // =========================================================================
  // Works with forms that have the `novalidate` attribute.
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[novalidate]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        if (!form.checkValidity()) {
          e.preventDefault();
          e.stopPropagation();
        }
        form.classList.add('was-validated');
      });
    });
  });

  // =========================================================================
  // 8. File upload label preview
  // =========================================================================
  document.addEventListener('change', function (event) {
    var input = event.target;
    if (input.classList && input.classList.contains('custom-file-input')) {
      var fileName = input.files[0] ? input.files[0].name : 'Choose file';
      var label = input.nextElementSibling;
      if (label) label.textContent = fileName;
    }
  });

  // =========================================================================
  // 9. Currency input formatting on blur
  // =========================================================================
  document.addEventListener('focusout', function (event) {
    var input = event.target;
    if (input.classList && input.classList.contains('currency-input')) {
      var value = parseFloat(input.value.replace(/[^0-9.]/g, ''));
      if (!isNaN(value)) {
        input.value = value.toFixed(2);
      }
    }
  });

  // =========================================================================
  // 10. Auto-save form drafts
  // =========================================================================
  // Usage: <form data-autosave="60000" action="/save/">...</form>
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-autosave]').forEach(function (form) {
      var interval = parseInt(form.dataset.autosave) || 60000;
      setInterval(function () {
        var formData = new FormData(form);
        formData.append('autosave', 'true');
        fetch(form.action, {
          method: 'POST',
          body: formData,
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (response) {
          if (response.ok) showToast('Draft saved', 'success');
        }).catch(function () { /* silent fail for autosave */ });
      }, interval);
    });
  });

  // =========================================================================
  // Global helpers (attached to window)
  // =========================================================================

  /**
   * Show a Bootstrap toast notification.
   * @param {string} message - Text to display
   * @param {string} [type='info'] - Bootstrap color: success, danger, warning, info
   */
  window.showToast = function (message, type) {
    type = type || 'info';
    var wrapper = document.createElement('div');
    wrapper.className = 'position-fixed bottom-0 end-0 p-3';
    wrapper.style.zIndex = '1080';
    wrapper.innerHTML =
      '<div class="toast show align-items-center text-white bg-' + type + ' border-0" role="alert">' +
      '  <div class="d-flex">' +
      '    <div class="toast-body">' + message + '</div>' +
      '    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(wrapper);
    setTimeout(function () { wrapper.remove(); }, 3000);
  };

  /**
   * Format a number as USD currency (locale-aware).
   * @param {number} amount
   * @returns {string}
   */
  window.formatCurrency = function (amount) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD'
    }).format(amount);
  };

  /**
   * Show a spinner inside a button and disable it.
   * Returns a restore function.
   *
   * Usage:
   *   var restore = btnLoading(btn, 'Saving...');
   *   await doWork();
   *   restore();
   */
  window.btnLoading = function (btn, text) {
    var original = btn.innerHTML;
    var loadingText = text || btn.getAttribute('data-loading-text') || 'Loading\u2026';
    btn.disabled = true;
    btn.classList.add('btn-loading');
    btn.innerHTML =
      '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
      loadingText;
    return function restore() {
      btn.disabled = false;
      btn.classList.remove('btn-loading');
      btn.innerHTML = original;
    };
  };

  // =========================================================================
  // Internal helpers
  // =========================================================================

  function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      var cookies = document.cookie.split(';');
      for (var i = 0; i < cookies.length; i++) {
        var cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

})();


/* ---------------------------------------------------------------------------
   DockLabs namespace — shared helpers available to all products
   --------------------------------------------------------------------------- */
window.DockLabs = window.DockLabs || {};

/**
 * Read embedded JSON data for a Chart.js chart.
 * Expects a <script type="application/json" id="{chartId}-data"> element.
 *
 * Usage:
 *   var data = DockLabs.chartData('statusChart');
 *   new Chart(ctx, { type: 'doughnut', data: data });
 */
DockLabs.chartData = function(chartId) {
    var el = document.getElementById(chartId + '-data');
    return el ? JSON.parse(el.textContent) : {};
};

/**
 * Format a number as compact currency (e.g., $1.2M, $500K).
 */
DockLabs.formatCurrency = function(value) {
    if (value >= 1e9) return '$' + (value / 1e9).toFixed(1) + 'B';
    if (value >= 1e6) return '$' + (value / 1e6).toFixed(1) + 'M';
    if (value >= 1e3) return '$' + (value / 1e3).toFixed(0) + 'K';
    return '$' + value.toLocaleString();
};

/**
 * Format a number with commas.
 */
DockLabs.formatNumber = function(value) {
    return Number(value).toLocaleString();
};
