(() => {
  'use strict';

  if (window.__microSipClickToCallInjected) return;
  window.__microSipClickToCallInjected = true;

  const ROOT_CLASS = 'wsf-click-number';
  const PHONE_CANDIDATE_RE = /(?<![\d+])(?:\+\d{1,3}|00\d{1,3}|880|0[129])[\d\s().-]{5,24}\d(?!\d)/g;
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'BUTTON', 'A', 'CODE', 'PRE', 'SVG', 'CANVAS']);
  const DUPLICATE_DIAL_MS = 1800;
  let lastDial = { number: '', at: 0 };

  function hasPhoneCandidate(value) {
    PHONE_CANDIDATE_RE.lastIndex = 0;
    const ok = PHONE_CANDIDATE_RE.test(String(value || ''));
    PHONE_CANDIDATE_RE.lastIndex = 0;
    return ok;
  }

  function cleanNumber(value) {
    return String(value || '')
      .replace(/^tel:/i, '')
      .replace(/^callto:/i, '')
      .replace(/^sip:/i, '')
      .replace(/[^\d+*#]/g, '')
      .trim();
  }

  function compactDigits(value) {
    return cleanNumber(value).replace(/^\+/, '');
  }

  function normalizeDialNumber(value) {
    const clean = cleanNumber(value);
    const digits = compactDigits(clean);
    if (clean.startsWith('+8801') && digits.length === 13) return `0${digits.slice(3)}`;
    if (digits.startsWith('8801') && digits.length === 13) return `0${digits.slice(3)}`;
    if (clean.startsWith('+')) return digits;
    if (digits.startsWith('00')) return digits;
    return digits;
  }

  function digitCount(value) {
    return (String(value || '').match(/\d/g) || []).length;
  }

  function isAllowedDialPrefix(value) {
    const clean = cleanNumber(value);
    const digits = compactDigits(clean);
    return clean.startsWith('+') || digits.startsWith('00') || digits.startsWith('880') || digits.startsWith('01') || digits.startsWith('02') || digits.startsWith('09');
  }

  function hasValidLengthForPrefix(value) {
    const clean = cleanNumber(value);
    const digits = compactDigits(clean);
    if (clean.startsWith('+')) return digits.length >= 8 && digits.length <= 15;
    if (digits.startsWith('00')) return digits.length >= 10 && digits.length <= 17;
    if (digits.startsWith('880')) return digits.length >= 10 && digits.length <= 13;
    if (digits.startsWith('01')) return digits.length === 11;
    if (digits.startsWith('02') || digits.startsWith('09')) return digits.length >= 7 && digits.length <= 11;
    return false;
  }

  function isPhoneLike(original) {
    const source = String(original || '').trim();
    const clean = cleanNumber(source);

    if (!clean) return false;
    if (!isAllowedDialPrefix(clean)) return false;
    if (!hasValidLengthForPrefix(clean)) return false;

    // Avoid common date/time formats being turned into calls.
    if (/^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}$/.test(source)) return false;
    if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(source)) return false;

    return true;
  }

  function extractPhone(value) {
    const text = String(value || '').replace(/\u00a0/g, ' ').trim();
    if (!text || text.length > 160) return '';

    if (isPhoneLike(text)) return cleanNumber(text);

    const matches = text.match(PHONE_CANDIDATE_RE) || [];
    for (const match of matches) {
      if (isPhoneLike(match)) return cleanNumber(match);
    }
    return '';
  }

  function phoneFromElement(element) {
    if (!element) return '';
    const values = [
      element.getAttribute && element.getAttribute('href'),
      element.dataset && (element.dataset.number || element.dataset.phone || element.dataset.value),
      element.getAttribute && element.getAttribute('aria-label'),
      element.getAttribute && element.getAttribute('title'),
      element.textContent
    ];
    for (const value of values) {
      const number = extractPhone(value);
      if (number) return number;
    }
    return '';
  }

  function canProcessTextNode(node) {
    if (!node || !node.nodeValue || !hasPhoneCandidate(node.nodeValue)) return false;

    const parent = node.parentElement;
    if (!parent) return false;
    if (parent.closest(`.${ROOT_CLASS}`)) return false;
    if (parent.closest('[contenteditable="true"]')) return false;

    let current = parent;
    while (current && current !== document.body && current !== document.documentElement) {
      if (SKIP_TAGS.has(current.tagName)) return false;
      current = current.parentElement;
    }
    return true;
  }

  function makeNumberSpan(displayText) {
    const number = normalizeDialNumber(displayText);
    const span = document.createElement('span');
    span.className = ROOT_CLASS;
    span.dataset.number = number;
    span.title = `Click to copy and open softphone: ${number}`;
    span.textContent = displayText;
    return span;
  }

  function wrapTextNode(node) {
    if (!canProcessTextNode(node)) return;

    const text = node.nodeValue;
    const frag = document.createDocumentFragment();
    let lastIndex = 0;
    let changed = false;

    PHONE_CANDIDATE_RE.lastIndex = 0;
    text.replace(PHONE_CANDIDATE_RE, (match, offset) => {
      if (!isPhoneLike(match)) return match;
      if (offset > lastIndex) frag.appendChild(document.createTextNode(text.slice(lastIndex, offset)));
      frag.appendChild(makeNumberSpan(match));
      lastIndex = offset + match.length;
      changed = true;
      return match;
    });
    PHONE_CANDIDATE_RE.lastIndex = 0;

    if (!changed) return;
    if (lastIndex < text.length) frag.appendChild(document.createTextNode(text.slice(lastIndex)));
    node.parentNode.replaceChild(frag, node);
  }

  function scan(root) {
    if (!root || root.nodeType !== Node.ELEMENT_NODE) return;
    if (SKIP_TAGS.has(root.tagName)) return;

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        return canProcessTextNode(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });

    const nodes = [];
    let node;
    while ((node = walker.nextNode())) nodes.push(node);
    nodes.forEach(wrapTextNode);
  }

  let scanTimer = null;
  const queuedRoots = new Set();

  function queueScan(root) {
    if (!root || root.nodeType !== Node.ELEMENT_NODE) return;
    queuedRoots.add(root);
    if (scanTimer) return;
    scanTimer = setTimeout(() => {
      const roots = Array.from(queuedRoots);
      queuedRoots.clear();
      scanTimer = null;
      roots.forEach(scan);
    }, 250);
  }

  function injectStyles() {
    if (document.getElementById('wsf-click-style')) return;
    const style = document.createElement('style');
    style.id = 'wsf-click-style';
    style.textContent = `
      .${ROOT_CLASS} {
        cursor: pointer !important;
        text-decoration: underline dotted #0ea5e9 !important;
        text-underline-offset: 2px !important;
        background: rgba(14, 165, 233, 0.12) !important;
        border-radius: 3px !important;
      }
      .${ROOT_CLASS}:hover {
        background: rgba(14, 165, 233, 0.25) !important;
      }
      #wsf-copy-toast {
        position: fixed !important;
        right: 18px !important;
        bottom: 18px !important;
        z-index: 2147483647 !important;
        background: #111827 !important;
        color: #ffffff !important;
        padding: 8px 10px !important;
        border-radius: 8px !important;
        font: 12px Arial, sans-serif !important;
        box-shadow: 0 8px 22px rgba(0,0,0,.25) !important;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function showToast(text) {
    let toast = document.getElementById('wsf-copy-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'wsf-copy-toast';
      (document.body || document.documentElement).appendChild(toast);
    }
    toast.textContent = text;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.remove(), 1800);
  }

  async function copyNumber(number) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(number);
        return true;
      }
    } catch (_) {}

    try {
      const textarea = document.createElement('textarea');
      textarea.value = number;
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.documentElement.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const ok = document.execCommand('copy');
      textarea.remove();
      return ok;
    } catch (_) {
      return false;
    }
  }

  function canMessageRuntime() {
    return Boolean(
      typeof chrome !== 'undefined' &&
      chrome.runtime &&
      chrome.runtime.id &&
      typeof chrome.runtime.sendMessage === 'function'
    );
  }

  function sendRuntimeMessage(message) {
    return new Promise((resolve) => {
      if (!canMessageRuntime()) {
        resolve({ ok: false, error: 'Browser extension context is not ready. Reload the extension, then refresh this page.' });
        return;
      }
      try {
        chrome.runtime.sendMessage(message, (response) => {
          const error = chrome.runtime.lastError;
          if (error) {
            resolve({ ok: false, error: error.message || 'Browser extension did not respond.' });
            return;
          }
          resolve(response || { ok: true });
        });
      } catch (error) {
        resolve({ ok: false, error: error.message || 'Browser extension messaging failed.' });
      }
    });
  }

  function openSoftphone(number) {
    return sendRuntimeMessage({ type: 'SOFTPHONE_OPEN_WINDOW', number });
  }

  function provisionWebExtension(config) {
    return sendRuntimeMessage({ type: 'SOFTPHONE_PROVISION', config });
  }

  async function handleNumber(number) {
    if (!isPhoneLike(number)) return;
    const normalized = normalizeDialNumber(number);
    const now = Date.now();
    if (lastDial.number === normalized && now - lastDial.at < DUPLICATE_DIAL_MS) {
      showToast(`Already loaded: ${normalized}`);
      return;
    }
    lastDial = { number: normalized, at: now };
    await copyNumber(normalized);
    const result = await openSoftphone(normalized);
    showToast(result.ok ? `Copied and loaded: ${normalized}` : (result.error || 'Copied, but softphone did not open'));
  }

  function bindClicks() {
    document.addEventListener('click', (event) => {
      const link = event.target.closest && event.target.closest('a[href]');
      const numberSpan = event.target.closest && event.target.closest(`.${ROOT_CLASS}`);
      const target = numberSpan || link;
      if (!target) return;

      const number = numberSpan ? numberSpan.dataset.number : phoneFromElement(link);
      if (!number) return;

      event.preventDefault();
      event.stopPropagation();
      handleNumber(number);
    }, true);
  }

  function bindSelectionFallback() {
    document.addEventListener('copy', (event) => {
      let copiedText = '';
      try {
        copiedText = event.clipboardData && event.clipboardData.getData('text/plain');
      } catch (_) {}
      const selectedText = copiedText || String(window.getSelection ? window.getSelection() : '');
      const number = extractPhone(selectedText);
      if (!number) return;
      setTimeout(() => handleNumber(number), 80);
    }, true);
  }

  function bindClipboardReadFallback() {
    document.addEventListener('keyup', (event) => {
      const isCopy = (event.ctrlKey || event.metaKey) && String(event.key || '').toLowerCase() === 'c';
      if (!isCopy || !navigator.clipboard || !navigator.clipboard.readText) return;
      setTimeout(async () => {
        try {
          const text = await navigator.clipboard.readText();
          const number = extractPhone(text);
          if (number) await handleNumber(number);
        } catch (_) {}
      }, 120);
    }, true);
  }

  function bindGoogleSheetsFallback() {
    if (!/docs\.google\.com$/.test(location.hostname) || !location.pathname.includes('/spreadsheets/')) return;

    function googleSheetsCandidates(target) {
      const active = document.activeElement;
      const formulaInput = document.querySelector('[aria-label="Formula bar"], [aria-label="Formula bar input"], input[name="formula"], textarea[name="formula"]');
      const selectedCell = document.querySelector('[role="gridcell"][aria-selected="true"], [aria-selected="true"], .cell-input, .waffle-cell-input, .grid-cell-selected');
      return [
        target && target.textContent,
        target && target.getAttribute && target.getAttribute('aria-label'),
        target && target.getAttribute && target.getAttribute('data-tooltip'),
        active && active.textContent,
        active && active.getAttribute && active.getAttribute('aria-label'),
        active && active.getAttribute && active.getAttribute('data-tooltip'),
        formulaInput && (formulaInput.value || formulaInput.textContent || formulaInput.getAttribute('aria-label')),
        selectedCell && selectedCell.textContent,
        selectedCell && selectedCell.getAttribute && selectedCell.getAttribute('aria-label'),
        selectedCell && selectedCell.getAttribute && selectedCell.getAttribute('data-tooltip'),
        String(window.getSelection ? window.getSelection() : '')
      ];
    }

    function handleGoogleSheetsTarget(target) {
      const candidates = googleSheetsCandidates(target);
      for (const candidate of candidates) {
        const number = extractPhone(candidate);
        if (number) {
          handleNumber(number);
          return true;
        }
      }
      return false;
    }

    document.addEventListener('dblclick', (event) => {
      handleGoogleSheetsTarget(event.target);
    }, true);

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') handleGoogleSheetsTarget(event.target);
    }, true);

    document.addEventListener('mouseup', (event) => {
      const selected = String(window.getSelection ? window.getSelection() : '').trim();
      if (extractPhone(selected)) setTimeout(() => handleGoogleSheetsTarget(event.target), 80);
    }, true);
  }

  function bindOmniPbxProvisioning() {
    window.addEventListener('message', async (event) => {
      if (event.source !== window) return;
      if (event.origin !== window.location.origin) return;
      const message = event.data || {};
      if (message.source !== 'OMNIPBX' || message.type !== 'OMNIPBX_PROVISION_WEB_EXTENSION') return;
      const result = await provisionWebExtension(message.config || {});
      window.postMessage({
        source: 'OMNIPBX_EXTENSION',
        type: 'OMNIPBX_PROVISION_WEB_EXTENSION_RESULT',
        requestId: message.requestId || '',
        ok: Boolean(result.ok),
        error: result.error || ''
      }, window.location.origin);
      showToast(result.ok ? 'Web extension provisioned' : (result.error || 'Provision failed'));
    });
  }

  function observeDom() {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.TEXT_NODE && node.parentElement) queueScan(node.parentElement);
          if (node.nodeType === Node.ELEMENT_NODE) queueScan(node);
        }
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  function boot() {
    injectStyles();
    bindClicks();
    bindSelectionFallback();
    bindClipboardReadFallback();
    bindGoogleSheetsFallback();
    bindOmniPbxProvisioning();
    queueScan(document.body || document.documentElement);
    observeDom();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
