(() => {
  'use strict';

  if (window.__microSipClickToCallInjected) return;
  window.__microSipClickToCallInjected = true;

  const ROOT_CLASS = 'wsf-click-number';
  const PHONE_CANDIDATE_RE = /(?:\+?\d[\d\s().-]{8,22}\d)/g;
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'BUTTON', 'A', 'CODE', 'PRE', 'SVG', 'CANVAS']);

  function cleanNumber(value) {
    return String(value || '')
      .replace(/^tel:/i, '')
      .replace(/[^\d+*#]/g, '')
      .trim();
  }

  function digitCount(value) {
    return (String(value || '').match(/\d/g) || []).length;
  }

  function isPhoneLike(original) {
    const source = String(original || '').trim();
    const clean = cleanNumber(source);
    const digits = digitCount(clean);

    if (!clean) return false;
    if (digits < 10 || digits > 12) return false;

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

  function canProcessTextNode(node) {
    if (!node || !node.nodeValue || !PHONE_CANDIDATE_RE.test(node.nodeValue)) return false;
    PHONE_CANDIDATE_RE.lastIndex = 0;

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
    const number = cleanNumber(displayText);
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

    text.replace(PHONE_CANDIDATE_RE, (match, offset) => {
      if (!isPhoneLike(match)) return match;
      if (offset > lastIndex) frag.appendChild(document.createTextNode(text.slice(lastIndex, offset)));
      frag.appendChild(makeNumberSpan(match));
      lastIndex = offset + match.length;
      changed = true;
      return match;
    });

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

  function openSoftphone(number) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'SOFTPHONE_OPEN_WINDOW', number }, (response) => {
        resolve(response || { ok: !chrome.runtime.lastError });
      });
    });
  }

  function provisionWebExtension(config) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'SOFTPHONE_PROVISION', config }, (response) => {
        resolve(response || { ok: !chrome.runtime.lastError, error: chrome.runtime.lastError && chrome.runtime.lastError.message });
      });
    });
  }

  async function handleNumber(number) {
    const clean = cleanNumber(number);
    if (!clean || digitCount(clean) < 10 || digitCount(clean) > 12) return;
    await copyNumber(clean);
    await openSoftphone(clean);
    showToast(`Copied and loaded: ${clean}`);
  }

  function bindClicks() {
    document.addEventListener('click', (event) => {
      const telLink = event.target.closest && event.target.closest('a[href^="tel:"]');
      const numberSpan = event.target.closest && event.target.closest(`.${ROOT_CLASS}`);
      const target = numberSpan || telLink;
      if (!target) return;

      const number = numberSpan ? numberSpan.dataset.number : cleanNumber(telLink.getAttribute('href'));
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
      setTimeout(() => openSoftphone(number), 80);
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
