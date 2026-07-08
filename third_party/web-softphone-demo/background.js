chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: 'softphone-dial-selection',
      title: 'Copy and dial selected number',
      contexts: ['selection']
    });
  });
});

function cleanNumber(value) {
  return String(value || '')
    .replace(/^tel:/i, '')
    .replace(/[^\d+*#]/g, '')
    .trim();
}

function savePendingNumber(number, callback) {
  const clean = cleanNumber(number);
  if (!clean) {
    callback && callback({ ok: false, error: 'No valid number found' });
    return;
  }
  chrome.storage.local.set({ pendingNumber: clean }, () => {
    // Also notify any already-open softphone extension page.
    chrome.runtime.sendMessage({ type: 'SOFTPHONE_SET_NUMBER', number: clean }, () => void chrome.runtime.lastError);
    callback && callback({ ok: true, number: clean });
  });
}

function isSoftphoneTab(tab) {
  return Boolean(tab && tab.id && tab.url === chrome.runtime.getURL('floating.html'));
}

function getStoredSoftphoneTab(callback) {
  chrome.storage.local.get(['registeredSoftphoneTabId'], (values) => {
    const tabId = Number(values.registeredSoftphoneTabId || 0);
    if (!tabId) {
      callback(null);
      return;
    }
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError || !isSoftphoneTab(tab)) {
        chrome.storage.local.remove(['registeredSoftphoneTabId', 'registeredSoftphoneWindowId']);
        callback(null);
        return;
      }
      callback(tab);
    });
  });
}

function rememberSoftphoneTab(tab) {
  if (!isSoftphoneTab(tab)) return;
  chrome.storage.local.set({
    registeredSoftphoneTabId: tab.id,
    registeredSoftphoneWindowId: tab.windowId
  });
}

function forgetSoftphoneTab(tab) {
  if (!tab || !tab.id) return;
  chrome.storage.local.get(['registeredSoftphoneTabId'], (values) => {
    if (Number(values.registeredSoftphoneTabId || 0) === tab.id) {
      chrome.storage.local.remove(['registeredSoftphoneTabId', 'registeredSoftphoneWindowId']);
    }
  });
}

function findSoftphoneWindow(callback) {
  getStoredSoftphoneTab((registeredTab) => {
    if (registeredTab) {
      callback(registeredTab);
      return;
    }
    chrome.tabs.query({ url: chrome.runtime.getURL('floating.html') }, (tabs) => {
      const list = tabs || [];
      const activeTab = list.find((tab) => tab.active);
      const tab = activeTab || list[0];
      callback(tab || null);
    });
  });
}

function focusSoftphoneWindow(tab, callback) {
  if (!tab || !tab.windowId) {
    callback && callback(false);
    return;
  }
  rememberSoftphoneTab(tab);
  chrome.windows.update(tab.windowId, { focused: true, state: 'normal' }, () => {
    if (chrome.runtime.lastError) {
      callback && callback(false);
      return;
    }
    chrome.tabs.update(tab.id, { active: true }, () => void chrome.runtime.lastError);
    callback && callback(true);
  });
}

function openSoftphoneWindow(number = '', callback) {
  const clean = cleanNumber(number);
  const afterNumberSaved = () => {
    findSoftphoneWindow((existingTab) => {
      if (existingTab) {
        focusSoftphoneWindow(existingTab, (focused) => {
          if (!focused) createSoftphoneWindow(callback);
          else callback && callback({ ok: true, reused: true, number: clean });
        });
        return;
      }
      createSoftphoneWindow((result) => {
        callback && callback({ ...(result || {}), number: clean });
      });
    });
  };

  if (clean) savePendingNumber(clean, afterNumberSaved);
  else afterNumberSaved();
}

function ensureKeepaliveSoftphone() {
  chrome.storage.local.get(['keepRegistered', 'wsUrl', 'sipDomain', 'sipUser', 'sipPass'], (values) => {
    if (!values.keepRegistered || !values.wsUrl || !values.sipDomain || !values.sipUser || !values.sipPass) return;
    findSoftphoneWindow((existingTab) => {
      if (existingTab) return;
      chrome.storage.local.set({ autoRegister: true }, () => {
        createSoftphoneWindow(() => {}, { minimized: true });
      });
    });
  });
}

function provisionSoftphone(config, callback) {
  const values = {
    wsUrl: String(config.websocket_url || ''),
    sipDomain: String(config.sip_domain || ''),
    sipUser: String(config.extension || ''),
    authUser: String(config.extension || ''),
    sipPass: String(config.secret || ''),
    displayName: String(config.display_name || config.extension || ''),
    iceServers: Array.isArray(config.ice_servers) ? config.ice_servers : [],
    autoRegister: true,
    keepRegistered: true
  };
  if (!values.wsUrl || !values.sipDomain || !values.sipUser || !values.sipPass) {
    callback && callback({ ok: false, error: 'Webphone settings are incomplete.' });
    return;
  }
  chrome.storage.local.set(values, () => {
    if (chrome.runtime.lastError) {
      callback && callback({ ok: false, error: chrome.runtime.lastError.message });
      return;
    }
    openSoftphoneWindow('', (result) => {
      if (result && result.reused) {
        chrome.runtime.sendMessage({ type: 'SOFTPHONE_REGISTER_NOW' }, () => void chrome.runtime.lastError);
      }
      callback && callback({ ...(result || {}), ok: Boolean(result && result.ok) });
    });
  });
}

function clampWindowSize(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}

function createSoftphoneWindow(callback, options = {}) {
  chrome.storage.local.get(['softphoneWindowWidth', 'softphoneWindowHeight'], (values) => {
    const width = clampWindowSize(values.softphoneWindowWidth, 190, 620, 380);
    const height = clampWindowSize(values.softphoneWindowHeight, 320, 900, 650);
    chrome.windows.create({
      url: chrome.runtime.getURL('floating.html'),
      type: 'popup',
      width,
      height,
      focused: !options.minimized
    }, (createdWindow) => {
      if (chrome.runtime.lastError) {
        callback && callback({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      if (options.minimized && createdWindow && createdWindow.id) {
        chrome.windows.update(createdWindow.id, { state: 'minimized' }, () => void chrome.runtime.lastError);
      }
      callback && callback({ ok: true, reused: false, windowId: createdWindow && createdWindow.id });
    });
  });
}

function notify(message) {
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icon128.png',
    title: 'Web Softphone',
    message
  }, () => void chrome.runtime.lastError);
}

chrome.action.onClicked.addListener(() => {
  openSoftphoneWindow('');
});

chrome.contextMenus.onClicked.addListener((info) => {
  const number = cleanNumber(info.selectionText);
  if (!number) return;

  if (info.menuItemId === 'softphone-dial-selection') {
    openSoftphoneWindow(number, () => notify(`Copied and loaded ${number}`));
  }
});

chrome.tabs.onRemoved.addListener(() => {
  setTimeout(ensureKeepaliveSoftphone, 600);
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.local.get(['registeredSoftphoneTabId'], (values) => {
    if (Number(values.registeredSoftphoneTabId || 0) === tabId) {
      chrome.storage.local.remove(['registeredSoftphoneTabId', 'registeredSoftphoneWindowId']);
    }
  });
});

chrome.runtime.onStartup.addListener(() => {
  setTimeout(ensureKeepaliveSoftphone, 1000);
});

chrome.notifications.onClicked.addListener((notificationId) => {
  if (notificationId !== 'omnipbx-incoming-call') return;
  openSoftphoneWindow('');
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === 'SOFTPHONE_SET_PENDING_NUMBER') {
    savePendingNumber(message.number, sendResponse);
    return true;
  }

  if (message && message.type === 'SOFTPHONE_OPEN_WINDOW') {
    openSoftphoneWindow(message.number || '', sendResponse);
    return true;
  }

  if (message && message.type === 'SOFTPHONE_NOTIFY') {
    notify(message.message || '');
    sendResponse({ ok: true });
    return true;
  }

  if (message && message.type === 'SOFTPHONE_PAGE_REGISTERED') {
    rememberSoftphoneTab(sender && sender.tab);
    sendResponse({ ok: true });
    return true;
  }

  if (message && message.type === 'SOFTPHONE_PAGE_UNREGISTERED') {
    forgetSoftphoneTab(sender && sender.tab);
    sendResponse({ ok: true });
    return true;
  }

  if (message && message.type === 'SOFTPHONE_INCOMING_CALL') {
    const caller = String(message.caller || 'Unknown caller');
    chrome.notifications.create('omnipbx-incoming-call', {
      type: 'basic',
      iconUrl: 'icon128.png',
      title: 'Incoming call',
      message: caller
    }, () => void chrome.runtime.lastError);
    if (isSoftphoneTab(sender && sender.tab)) {
      focusSoftphoneWindow(sender.tab, (focused) => {
        if (!focused) openSoftphoneWindow('', () => {});
      });
    } else {
      openSoftphoneWindow('', () => {});
    }
    sendResponse({ ok: true });
    return true;
  }

  if (message && message.type === 'SOFTPHONE_PROVISION') {
    provisionSoftphone(message.config || {}, sendResponse);
    return true;
  }
});
