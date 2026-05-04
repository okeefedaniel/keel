/* Live username-availability checker.
 *
 * Auto-binds to any <input data-username-check="true"> on the page. The
 * input must carry these data attributes (rendered by the form widget):
 *
 *   data-username-check="true"
 *   data-username-check-url="/keel/username-available/"   (optional; defaults to that path)
 *
 * The script:
 *   1. Inserts a status icon span next to the input.
 *   2. Inserts a feedback line below the input.
 *   3. Debounces input events at 300ms; cancels in-flight fetches via AbortController.
 *   4. Disables the nearest enclosing form's submit button until status is "available".
 *
 * Server contract — GET <url>?u=<candidate> returns 200 with JSON:
 *   { available: bool, reason: "taken"|"reserved"|"invalid_format"|"unchanged"|null,
 *     normalized: string }
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 300;
  var DEFAULT_URL = '/keel/username-available/';

  var REASON_MESSAGES = {
    taken: 'That username is already taken.',
    reserved: 'That username is reserved.',
    invalid_format: 'Use 3–32 lowercase letters, numbers, dash, or underscore.',
    unchanged: 'That is already your username.'
  };

  function makeStatusEl() {
    var el = document.createElement('span');
    el.className = 'username-check-status ms-2';
    el.setAttribute('aria-live', 'polite');
    return el;
  }

  function makeFeedbackEl() {
    var el = document.createElement('small');
    el.className = 'form-text username-check-feedback';
    return el;
  }

  function findSubmitButton(input) {
    var form = input.closest('form');
    if (!form) return null;
    return form.querySelector('button[type="submit"], input[type="submit"]');
  }

  function setState(state, statusEl, feedbackEl, submitBtn, message) {
    // state ∈ { idle, checking, available, unavailable }
    statusEl.textContent = '';
    statusEl.classList.remove(
      'text-success', 'text-danger', 'text-muted', 'spinner-border', 'spinner-border-sm'
    );
    feedbackEl.classList.remove('text-success', 'text-danger', 'text-muted');
    feedbackEl.textContent = '';

    if (state === 'checking') {
      statusEl.classList.add('spinner-border', 'spinner-border-sm', 'text-muted');
      statusEl.setAttribute('role', 'status');
      if (submitBtn) submitBtn.disabled = true;
    } else if (state === 'available') {
      statusEl.textContent = '✓';
      statusEl.classList.add('text-success');
      feedbackEl.textContent = 'Available.';
      feedbackEl.classList.add('text-success');
      if (submitBtn) submitBtn.disabled = false;
    } else if (state === 'unavailable') {
      statusEl.textContent = '✗';
      statusEl.classList.add('text-danger');
      feedbackEl.textContent = message || 'Not available.';
      feedbackEl.classList.add('text-danger');
      if (submitBtn) submitBtn.disabled = true;
    } else {
      // idle
      if (submitBtn) submitBtn.disabled = true;
    }
  }

  function bind(input) {
    if (input.dataset.usernameCheckBound === '1') return;
    input.dataset.usernameCheckBound = '1';

    var url = input.dataset.usernameCheckUrl || DEFAULT_URL;
    var statusEl = makeStatusEl();
    var feedbackEl = makeFeedbackEl();

    // Insert the status icon directly after the input. Use the
    // surrounding parent's flex layout if present; otherwise wrap.
    var parent = input.parentNode;
    parent.insertBefore(statusEl, input.nextSibling);
    parent.insertBefore(feedbackEl, statusEl.nextSibling);

    var submitBtn = findSubmitButton(input);
    var initialValue = input.value;

    // Initial state: empty / unchanged → idle (submit disabled).
    setState('idle', statusEl, feedbackEl, submitBtn);

    var timer = null;
    var controller = null;

    function check() {
      var candidate = (input.value || '').trim().toLowerCase();
      // Mirror back the normalized value so users see what's being
      // evaluated server-side.
      if (candidate !== input.value) {
        // Don't fight the user mid-keystroke; just normalize on blur.
      }
      if (!candidate || candidate === initialValue.toLowerCase()) {
        setState('idle', statusEl, feedbackEl, submitBtn);
        return;
      }

      setState('checking', statusEl, feedbackEl, submitBtn);

      if (controller) controller.abort();
      controller = new AbortController();

      var qs = '?u=' + encodeURIComponent(candidate);
      fetch(url + qs, {
        method: 'GET',
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' },
        signal: controller.signal
      }).then(function (resp) {
        if (resp.status === 429) {
          setState('unavailable', statusEl, feedbackEl, submitBtn,
            'Too many checks. Slow down for a moment.');
          return null;
        }
        return resp.json();
      }).then(function (data) {
        if (!data) return;
        // Stale-response guard: if the input changed since we fired,
        // discard.
        if ((input.value || '').trim().toLowerCase() !== data.normalized) {
          return;
        }
        if (data.available) {
          setState('available', statusEl, feedbackEl, submitBtn);
        } else {
          var msg = REASON_MESSAGES[data.reason] || 'Not available.';
          setState('unavailable', statusEl, feedbackEl, submitBtn, msg);
        }
      }).catch(function (err) {
        if (err && err.name === 'AbortError') return;
        setState('idle', statusEl, feedbackEl, submitBtn);
      });
    }

    input.addEventListener('input', function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(check, DEBOUNCE_MS);
    });

    input.addEventListener('blur', function () {
      // Snap to lowercase so the submitted value matches what the
      // server normalized.
      input.value = (input.value || '').trim().toLowerCase();
    });
  }

  function init() {
    var inputs = document.querySelectorAll('input[data-username-check="true"]');
    for (var i = 0; i < inputs.length; i++) bind(inputs[i]);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
