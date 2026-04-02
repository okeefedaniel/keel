/**
 * Keel Instant Search — typeahead with live results.
 *
 * Usage:
 *   <div id="keel-search-app"
 *        data-instant-url="/opportunities/instant/"
 *        data-detail-url-prefix="/opportunities/">
 *     <input type="text" id="keel-search-input" ...>
 *     <div id="keel-instant-results"></div>
 *   </div>
 *
 * The product provides a renderResult(result, query) function on
 * window.keelSearchConfig, or the default renderer is used.
 */
(function () {
  var app = document.getElementById('keel-search-app');
  if (!app) return;

  var instantUrl = app.dataset.instantUrl;
  var input = document.getElementById('keel-search-input');
  var dropdown = document.getElementById('keel-instant-results');
  if (!input || !dropdown || !instantUrl) return;

  var debounceTimer = null;
  var selectedIndex = -1;
  var currentResults = [];
  var config = window.keelSearchConfig || {};

  // --- Utilities ---

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function highlight(text, query) {
    if (!query) return escapeHtml(text);
    var escaped = escapeHtml(text);
    var words = query.trim().split(/\s+/).map(function (w) {
      return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    });
    var re = new RegExp('(' + words.join('|') + ')', 'gi');
    return escaped.replace(re, '<mark>$1</mark>');
  }

  function statusBadge(status) {
    var colors = {
      'Posted': 'bg-success', 'Open': 'bg-success',
      'Closed': 'bg-secondary', 'Archived': 'bg-secondary',
      'Forecasted': 'bg-info',
    };
    if (!status) return '';
    return '<span class="badge ' + (colors[status] || 'bg-secondary') + ' ms-1" style="font-size:0.7rem;">' + escapeHtml(status) + '</span>';
  }

  // --- Default result renderer ---

  function defaultRenderResult(r, query) {
    var title = highlight(r.title || r.title_short || '', query);
    var subtitle = r.agency || r.subtitle || '';
    var status = r.status_display || r.status || '';
    var extra = r.funding || r.extra || '';
    var url = r.url || '#';

    return '<a href="' + url + '" class="keel-instant-item d-block px-3 py-2 text-decoration-none border-bottom" data-index="__IDX__">' +
      '<div class="d-flex justify-content-between align-items-start">' +
      '<div style="flex:1; min-width:0;">' +
      (subtitle ? '<div class="text-muted" style="font-size:0.75rem;">' + escapeHtml(subtitle) + '</div>' : '') +
      '<div class="text-dark small text-truncate">' + title + '</div>' +
      (extra ? '<div class="text-muted" style="font-size:0.7rem;">' + escapeHtml(extra) + '</div>' : '') +
      '</div>' +
      '<div class="ms-2 text-nowrap">' + statusBadge(status) + '</div>' +
      '</div>' +
      '</a>';
  }

  var renderResult = config.renderResult || defaultRenderResult;

  // --- Dropdown rendering ---

  function renderDropdown(results, query) {
    currentResults = results;
    selectedIndex = -1;

    if (!results.length) {
      if (query.length >= 2) {
        dropdown.innerHTML = '<div class="p-3 text-muted text-center small">No matches for \u201c' + escapeHtml(query) + '\u201d</div>';
        dropdown.style.display = 'block';
      } else {
        dropdown.style.display = 'none';
      }
      return;
    }

    var html = '';
    for (var i = 0; i < results.length; i++) {
      html += renderResult(results[i], query).replace('__IDX__', i);
    }
    html += '<div class="px-3 py-2 bg-light text-center">' +
      '<small class="text-muted">' + results.length + ' results \u2014 press Enter for full search</small></div>';

    dropdown.innerHTML = html;
    dropdown.style.display = 'block';

    // Hover highlighting
    var items = dropdown.querySelectorAll('.keel-instant-item');
    for (var j = 0; j < items.length; j++) {
      items[j].addEventListener('mouseenter', function () {
        clearSelected();
        this.classList.add('bg-primary', 'bg-opacity-10');
        selectedIndex = parseInt(this.dataset.index);
      });
      items[j].addEventListener('mouseleave', function () {
        this.classList.remove('bg-primary', 'bg-opacity-10');
      });
    }
  }

  function clearSelected() {
    var items = dropdown.querySelectorAll('.keel-instant-item');
    for (var i = 0; i < items.length; i++) {
      items[i].classList.remove('bg-primary', 'bg-opacity-10');
    }
  }

  // --- Fetch ---

  function fetchInstant(query) {
    var url = instantUrl + '?q=' + encodeURIComponent(query);
    // Append current filter values from form
    var form = input.closest('form');
    if (form) {
      var selects = form.querySelectorAll('select');
      for (var i = 0; i < selects.length; i++) {
        if (selects[i].value && selects[i].name !== 'view') {
          url += '&' + encodeURIComponent(selects[i].name) + '=' + encodeURIComponent(selects[i].value);
        }
      }
    }
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (input.value.trim() === query) {
          renderDropdown(data.results || [], query);
        }
      })
      .catch(function () { dropdown.style.display = 'none'; });
  }

  // --- Event handlers ---

  input.addEventListener('input', function () {
    var q = this.value.trim();
    clearTimeout(debounceTimer);
    if (q.length < 2) {
      dropdown.style.display = 'none';
      return;
    }
    debounceTimer = setTimeout(function () { fetchInstant(q); }, 150);
  });

  input.addEventListener('keydown', function (e) {
    var items = dropdown.querySelectorAll('.keel-instant-item');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
      clearSelected();
      items[selectedIndex].classList.add('bg-primary', 'bg-opacity-10');
      items[selectedIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
      clearSelected();
      items[selectedIndex].classList.add('bg-primary', 'bg-opacity-10');
      items[selectedIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
      e.preventDefault();
      window.location.href = items[selectedIndex].href;
    } else if (e.key === 'Escape') {
      dropdown.style.display = 'none';
    }
  });

  document.addEventListener('click', function (e) {
    if (!dropdown.contains(e.target) && e.target !== input) {
      dropdown.style.display = 'none';
    }
  });

  input.addEventListener('focus', function () {
    if (this.value.trim().length >= 2 && currentResults.length) {
      dropdown.style.display = 'block';
    }
  });
})();
