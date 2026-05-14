/**
 * keel.mentions — @-mention autocomplete picker.
 *
 * Activates on every `<textarea class="mentionable">` element. Reads
 * `data-mentions-search-url` for the autocomplete endpoint, fetches when
 * the user types `@`, and renders a floating menu styled with
 * docklabs-v2.css tokens. Insert on Enter / click.
 *
 * Vanilla JS, no React, no framework — matches suite convention.
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 150;
  var MIN_QUERY = 2;
  var MENU_MAX_HEIGHT_VH = 40;
  var MOBILE_BREAKPOINT = 768;

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function initialsFor(name) {
    var parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  /**
   * Find the @-token the caret is currently positioned in (if any).
   * Returns {start, end, query, prefix} or null.
   *
   * Accepts both `@username` and `@beacon:contact-slug` shapes — the
   * `prefix` is everything between `@` and the caret (used as the
   * search query).
   */
  function activeMentionToken(textarea) {
    var pos = textarea.selectionStart;
    var value = textarea.value;
    // Find the most recent '@' before the caret that isn't preceded by
    // a word character or dot.
    for (var i = pos - 1; i >= 0; i--) {
      var ch = value.charAt(i);
      if (/\s/.test(ch)) return null;
      if (ch === '@') {
        if (i > 0) {
          var prev = value.charAt(i - 1);
          if (/[\w.]/.test(prev)) return null;
        }
        return {
          start: i,
          end: pos,
          prefix: value.substring(i + 1, pos),
        };
      }
    }
    return null;
  }

  function MentionPicker(textarea) {
    this.textarea = textarea;
    this.searchUrl = textarea.getAttribute('data-mentions-search-url');
    this.menu = null;
    this.results = { users: [], contacts: [] };
    this.flat = []; // flat list for keyboard nav: [{kind, item}, ...]
    this.activeIdx = -1;
    this.state = 'idle';
    this.token = null;
    this.bind();
  }

  MentionPicker.prototype.bind = function () {
    var self = this;
    var onInput = debounce(function () { self.onInput(); }, DEBOUNCE_MS);
    this.textarea.addEventListener('input', onInput);
    this.textarea.addEventListener('keydown', function (e) { self.onKeyDown(e); });
    this.textarea.addEventListener('blur', function () {
      // Slight delay so mousedown on the menu fires first.
      setTimeout(function () { self.close(); }, 100);
    });
    this.textarea.setAttribute('role', 'combobox');
    this.textarea.setAttribute('aria-haspopup', 'listbox');
    this.textarea.setAttribute('aria-expanded', 'false');
  };

  MentionPicker.prototype.onInput = function () {
    var token = activeMentionToken(this.textarea);
    if (!token) { this.close(); return; }
    this.token = token;
    if (token.prefix.length < MIN_QUERY) {
      this.setState('idle');
      this.close();
      return;
    }
    this.fetch(token.prefix);
  };

  MentionPicker.prototype.fetch = function (query) {
    var self = this;
    this.setState('loading');
    var url = this.searchUrl + (this.searchUrl.indexOf('?') < 0 ? '?' : '&') + 'q=' + encodeURIComponent(query);
    fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (resp) {
        if (resp.status === 429) { self.setState('throttled'); return null; }
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(function (data) {
        if (data === null) return; // throttled — keep prior results
        self.results = {
          users: (data && data.users) || [],
          contacts: (data && data.contacts) || [],
        };
        if (self.results.users.length === 0 && self.results.contacts.length === 0) {
          self.setState('empty');
        } else {
          self.setState('results');
        }
        self.render();
      })
      .catch(function () {
        self.setState('error');
        self.render();
      });
  };

  MentionPicker.prototype.setState = function (state) {
    this.state = state;
  };

  MentionPicker.prototype.ensureMenu = function () {
    if (this.menu) return this.menu;
    var menu = document.createElement('div');
    menu.className = 'dl-mention-menu';
    menu.setAttribute('role', 'listbox');
    menu.id = 'dl-mention-menu-' + Math.random().toString(36).slice(2, 8);
    menu.addEventListener('mousedown', function (e) {
      // Prevent textarea blur from closing the menu before click fires.
      e.preventDefault();
    });
    document.body.appendChild(menu);
    this.menu = menu;
    this.textarea.setAttribute('aria-controls', menu.id);
    return menu;
  };

  MentionPicker.prototype.render = function () {
    var menu = this.ensureMenu();
    menu.innerHTML = '';
    this.flat = [];

    if (this.state === 'loading') {
      menu.innerHTML = '<div class="dl-mention-status">Searching…</div>';
    } else if (this.state === 'empty') {
      menu.innerHTML = '<div class="dl-mention-status">No matches — type a colleague\'s name</div>';
    } else if (this.state === 'error') {
      menu.innerHTML = '<div class="dl-mention-status">Couldn\'t load — try again</div>';
    } else if (this.state === 'results') {
      var idx = 0;
      var html = [];
      var users = this.results.users || [];
      var contacts = this.results.contacts || [];

      if (users.length) {
        html.push('<div class="dl-mention-section">Teammates</div>');
        for (var i = 0; i < users.length; i++) {
          var u = users[i];
          this.flat.push({ kind: 'user', item: u });
          html.push(this.userRowHtml(u, idx));
          idx++;
        }
      }
      if (contacts.length) {
        html.push('<div class="dl-mention-section">Contacts (Beacon)</div>');
        for (var j = 0; j < contacts.length; j++) {
          var c = contacts[j];
          this.flat.push({ kind: 'contact', item: c });
          html.push(this.contactRowHtml(c, idx));
          idx++;
        }
      }
      menu.innerHTML = html.join('');
      this.activeIdx = 0;
      this.bindRowEvents();
      this.updateActive();
    }

    if (this.state === 'idle') {
      this.close();
      return;
    }

    this.position();
    menu.style.display = 'block';
    this.textarea.setAttribute('aria-expanded', 'true');
  };

  MentionPicker.prototype.userRowHtml = function (u, idx) {
    var avatar = u.avatar_url
      ? '<img class="dl-mention-avatar" src="' + escapeHtml(u.avatar_url) + '" alt="">'
      : '<span class="dl-mention-avatar dl-mention-initials">' + escapeHtml(initialsFor(u.display_name || u.username)) + '</span>';
    return [
      '<div class="dl-mention-row" role="option" id="dl-mention-opt-', idx, '" data-idx="', idx, '" data-kind="user" data-ref="', escapeHtml(u.username), '" title="', escapeHtml(u.display_name), '">',
        avatar,
        '<span class="dl-mention-identity">',
          '<span class="dl-mention-name">', escapeHtml(u.display_name || u.username), '</span>',
          '<span class="dl-mention-username">@', escapeHtml(u.username), '</span>',
        '</span>',
      '</div>',
    ].join('');
  };

  MentionPicker.prototype.contactRowHtml = function (c, idx) {
    var initials = initialsFor(c.display_name || c.slug);
    return [
      '<div class="dl-mention-row" role="option" id="dl-mention-opt-', idx, '" data-idx="', idx, '" data-kind="contact" data-ref="', escapeHtml(c.slug), '" title="', escapeHtml(c.display_name), '">',
        '<span class="dl-mention-avatar dl-mention-initials">', escapeHtml(initials), '</span>',
        '<span class="dl-mention-identity">',
          '<span class="dl-mention-name">', escapeHtml(c.display_name || c.slug), '</span>',
          '<span class="dl-mention-username">', escapeHtml(c.organization || 'Beacon contact'), '</span>',
        '</span>',
      '</div>',
    ].join('');
  };

  MentionPicker.prototype.bindRowEvents = function () {
    var self = this;
    var rows = this.menu.querySelectorAll('.dl-mention-row');
    rows.forEach(function (row) {
      row.addEventListener('click', function () {
        var kind = row.getAttribute('data-kind');
        var ref = row.getAttribute('data-ref');
        self.insert(kind, ref);
      });
      row.addEventListener('mouseover', function () {
        self.activeIdx = parseInt(row.getAttribute('data-idx'), 10);
        self.updateActive();
      });
    });
  };

  MentionPicker.prototype.updateActive = function () {
    var rows = this.menu.querySelectorAll('.dl-mention-row');
    rows.forEach(function (r) { r.classList.remove('is-active'); });
    if (this.activeIdx >= 0 && this.activeIdx < rows.length) {
      rows[this.activeIdx].classList.add('is-active');
      this.textarea.setAttribute('aria-activedescendant', rows[this.activeIdx].id);
    }
  };

  MentionPicker.prototype.position = function () {
    var rect = this.textarea.getBoundingClientRect();
    var menu = this.menu;
    if (window.innerWidth < MOBILE_BREAKPOINT) {
      // Mobile: full-width sheet anchored to the textarea bottom.
      menu.classList.add('dl-mention-menu--mobile');
      menu.style.left = rect.left + window.scrollX + 'px';
      menu.style.top = (rect.bottom + window.scrollY) + 'px';
      menu.style.width = rect.width + 'px';
    } else {
      menu.classList.remove('dl-mention-menu--mobile');
      // Desktop: float under the textarea. Flip above if near viewport bottom.
      var below = window.innerHeight - rect.bottom;
      var menuHeight = menu.offsetHeight || 200;
      if (below < menuHeight + 20 && rect.top > menuHeight + 20) {
        menu.style.top = (rect.top + window.scrollY - menuHeight - 4) + 'px';
      } else {
        menu.style.top = (rect.bottom + window.scrollY + 4) + 'px';
      }
      menu.style.left = (rect.left + window.scrollX) + 'px';
      menu.style.width = Math.max(280, rect.width / 2) + 'px';
    }
    menu.style.maxHeight = MENU_MAX_HEIGHT_VH + 'vh';
  };

  MentionPicker.prototype.onKeyDown = function (e) {
    if (!this.menu || this.menu.style.display !== 'block') return;
    if (this.state !== 'results') return;
    var rows = this.menu.querySelectorAll('.dl-mention-row');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      this.activeIdx = Math.min(rows.length - 1, this.activeIdx + 1);
      this.updateActive();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      this.activeIdx = Math.max(0, this.activeIdx - 1);
      this.updateActive();
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      if (this.activeIdx >= 0 && this.activeIdx < this.flat.length) {
        e.preventDefault();
        var pick = this.flat[this.activeIdx];
        var ref = pick.kind === 'user' ? pick.item.username : pick.item.slug;
        this.insert(pick.kind, ref);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      this.close();
    }
  };

  MentionPicker.prototype.insert = function (kind, ref) {
    if (!this.token) return;
    var ta = this.textarea;
    var before = ta.value.substring(0, this.token.start);
    var after = ta.value.substring(this.token.end);
    var inserted = kind === 'contact' ? '@beacon:' + ref : '@' + ref;
    // Append a trailing space if not already there.
    if (after.length === 0 || after.charAt(0) !== ' ') inserted += ' ';
    ta.value = before + inserted + after;
    var caret = before.length + inserted.length;
    ta.setSelectionRange(caret, caret);
    ta.focus();
    this.close();
    // Fire input so any host listeners see the change.
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  };

  MentionPicker.prototype.close = function () {
    if (this.menu) {
      this.menu.style.display = 'none';
    }
    this.textarea.setAttribute('aria-expanded', 'false');
    this.textarea.removeAttribute('aria-activedescendant');
    this.token = null;
    this.state = 'idle';
  };

  function init() {
    var textareas = document.querySelectorAll('textarea.mentionable[data-mentions-search-url]');
    textareas.forEach(function (ta) {
      if (ta.dataset.mentionsBound === '1') return;
      ta.dataset.mentionsBound = '1';
      new MentionPicker(ta);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
