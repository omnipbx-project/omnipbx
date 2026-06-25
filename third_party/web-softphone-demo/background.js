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

function findSoftphoneWindow(callback) {
  chrome.tabs.query({ url: chrome.runtime.getURL('floating.html') }, (tabs) => {
    const tab = (tabs || [])[0];
    callback(tab || null);
  });
}

function focusSoftphoneWindow(tab, callback) {
  if (!tab || !tab.windowId) {
    callback && callback(false);
    return;
  }
  chrome.windows.update(tab.windowId, { focused: true }, () => {
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

function provisionSoftphone(config, callback) {
  const values = {
    wsUrl: String(config.websocket_url || ''),
    sipDomain: String(config.sip_domain || ''),
    sipUser: String(config.extension || ''),
    authUser: String(config.extension || ''),
    sipPass: String(config.secret || ''),
    displayName: String(config.display_name || config.extension || ''),
    autoRegister: true
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

function createSoftphoneWindow(callback) {
  chrome.windows.create({
    url: chrome.runtime.getURL('floating.html'),
    type: 'popup',
    width: 380,
    height: 650,
    focused: true
  }, (createdWindow) => {
    if (chrome.runtime.lastError) {
      callback && callback({ ok: false, error: chrome.runtime.lastError.message });
      return;
    }
    callback && callback({ ok: true, reused: false, windowId: createdWindow && createdWindow.id });
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

  if (message && message.type === 'SOFTPHONE_PROVISION') {
    provisionSoftphone(message.config || {}, sendResponse);
    return true;
  }
});
