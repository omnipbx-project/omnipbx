(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const hasChrome = typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local;

  const els = {
    settingsToggle: $('settingsToggle'),
    settingsPanel: $('settingsPanel'),
    wsUrl: $('wsUrl'),
    sipDomain: $('sipDomain'),
    sipUser: $('sipUser'),
    authUser: $('authUser'),
    sipPass: $('sipPass'),
    displayName: $('displayName'),
    registerBtn: $('registerBtn'),
    unregisterBtn: $('unregisterBtn'),
    dialNumber: $('dialNumber'),
    backspaceBtn: $('backspaceBtn'),
    copyNumberBtn: $('copyNumberBtn'),
    keypad: document.querySelector('.keypad'),
    transferBtn: $('transferBtn'),
    plusBtn: $('plusBtn'),
    clearBtn: $('clearBtn'),
    videoCallBtn: $('videoCallBtn'),
    callBtn: $('callBtn'),
    messageBtn: $('messageBtn'),
    speakerVolume: $('speakerVolume'),
    speakerMuteBtn: $('speakerMuteBtn'),
    micMuteBtn: $('micMuteBtn'),
    dndBtn: $('dndBtn'),
    autoAnswerBtn: $('autoAnswerBtn'),
    confBtn: $('confBtn'),
    recordBtn: $('recordBtn'),
    mediaPanel: $('mediaPanel'),
    remoteAudio: $('remoteAudio'),
    remoteVideo: $('remoteVideo'),
    localVideo: $('localVideo'),
    logPanel: $('logPanel'),
    callLog: $('callLog'),
    statusText: $('statusText'),
    statusDot: $('statusDot'),
    accountLabel: $('accountLabel'),
    callTimer: $('callTimer')
  };

  const state = {
    ua: null,
    currentSession: null,
    incomingSession: null,
    remoteStream: null,
    localStream: null,
    isRegistered: false,
    autoAnswer: false,
    isMuted: false,
    isSpeakerMuted: false,
    mediaRecorder: null,
    recordedChunks: [],
    registering: false,
    accountKey: '',
    iceServers: [],
    retryTimer: null,
    manualUnregister: false,
    pendingCall: null,
    ringtone: null,
    ringback: null,
    callStartedAt: 0,
    callAnswered: false,
    statsTimer: null,
    talkStartedAt: 0,
    talkTimer: null,
    hangupResetTimer: null
  };

  const DEFAULTS = {
    wsUrl: '',
    sipDomain: '',
    sipUser: '',
    authUser: '',
    sipPass: '',
    displayName: '',
    iceServers: [],
    autoRegister: false,
    autoAnswer: false
  };

  function storageGet(keys) {
    return new Promise((resolve) => {
      if (!hasChrome) return resolve({});
      chrome.storage.local.get(keys, resolve);
    });
  }

  function storageSet(values) {
    return new Promise((resolve) => {
      if (!hasChrome) return resolve();
      chrome.storage.local.set(values, resolve);
    });
  }

  function runtimeMessage(message) {
    if (!hasChrome || !chrome.runtime || !chrome.runtime.sendMessage) return;
    chrome.runtime.sendMessage(message, () => void chrome.runtime.lastError);
  }

  function rememberWindowSize() {
    if (!hasChrome) return;
    clearTimeout(rememberWindowSize.timer);
    rememberWindowSize.timer = setTimeout(() => {
      const width = Math.round(window.outerWidth || window.innerWidth || 0);
      const height = Math.round(window.outerHeight || window.innerHeight || 0);
      if (width < 180 || height < 260) return;
      storageSet({
        softphoneWindowWidth: width,
        softphoneWindowHeight: height
      });
    }, 300);
  }

  function normalizeNumber(raw) {
    return String(raw || '')
      .replace(/^sip:/i, '')
      .replace(/[<>"']/g, '')
      .trim();
  }

  function currentAccountUri() {
    const user = els.sipUser.value.trim();
    const domain = els.sipDomain.value.trim();
    if (!user) return '';
    if (user.includes('@')) return `sip:${user}`;
    if (!domain) return '';
    return `sip:${user}@${domain}`;
  }

  function targetUri(number) {
    const clean = normalizeNumber(number);
    if (!clean) return '';
    if (clean.includes('@')) return clean.startsWith('sip:') ? clean : `sip:${clean}`;
    const domain = els.sipDomain.value.trim();
    return domain ? `sip:${clean}@${domain}` : `sip:${clean}`;
  }

  function setStatus(text, tone = 'idle') {
    els.statusText.textContent = text;
    els.statusDot.className = 'status-dot';
    if (tone === 'ok') els.statusDot.classList.add('ok');
    if (tone === 'warn') els.statusDot.classList.add('warn');
    if (tone === 'bad') els.statusDot.classList.add('bad');
  }

  function setCallStatus(text, tone = 'idle') {
    if (state.callAnswered && /ringing/i.test(String(text || ''))) return;
    setStatus(text, tone);
  }

  function setAccountLabel() {
    els.accountLabel.textContent = els.sipUser.value.trim() || '—';
  }

  function setDialNumber(value, focus = true) {
    if (!canEditDialNumber()) return;
    els.dialNumber.value = normalizeNumber(value);
    if (focus) els.dialNumber.focus();
  }

  function canEditDialNumber() {
    return !state.currentSession && !state.incomingSession;
  }

  function accountKey() {
    return [
      els.wsUrl.value.trim(),
      els.sipDomain.value.trim(),
      els.sipUser.value.trim(),
      els.authUser.value.trim(),
      els.displayName.value.trim()
    ].join('|');
  }

  function logLine(text) {
    console.log(`OmniPBX softphone: ${text}`);
    const li = document.createElement('li');
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    li.textContent = `${time}  ${text}`;
    els.callLog.prepend(li);
    while (els.callLog.children.length > 30) els.callLog.lastElementChild.remove();
  }

  function callTiming(label) {
    if (!state.callStartedAt) return;
    const elapsed = Math.round(performance.now() - state.callStartedAt);
    logLine(`${label} (+${elapsed} ms)`);
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(seconds || 0));
    const minutes = Math.floor(total / 60);
    const secs = total % 60;
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function updateTalkTimer() {
    if (!els.callTimer) return;
    if (!state.talkStartedAt) {
      els.callTimer.textContent = '00:00';
      els.callTimer.classList.remove('active');
      return;
    }
    els.callTimer.textContent = formatDuration((Date.now() - state.talkStartedAt) / 1000);
    els.callTimer.classList.add('active');
  }

  function startTalkTimer() {
    state.talkStartedAt = Date.now();
    updateTalkTimer();
    if (state.talkTimer) clearInterval(state.talkTimer);
    state.talkTimer = setInterval(updateTalkTimer, 1000);
  }

  function stopTalkTimer() {
    if (state.talkTimer) clearInterval(state.talkTimer);
    state.talkTimer = null;
    state.talkStartedAt = 0;
    updateTalkTimer();
  }

  function sipFirstLine(message) {
    const text = typeof message === 'string'
      ? message
      : new TextDecoder('utf-8').decode(message || new ArrayBuffer(0));
    return text.split(/\r\n|\n/)[0] || '';
  }

  function safeSipUser(value) {
    return String(value || '').replace(/[^A-Za-z0-9_.!~*'()%+\-]/g, '') || 'webphone';
  }

  function randomContactHost() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return `${window.crypto.randomUUID()}.invalid`;
    }
    return `${Math.random().toString(36).slice(2)}.invalid`;
  }

  function sipMessageText(message) {
    if (typeof message === 'string') return message;
    return new TextDecoder('utf-8').decode(message || new ArrayBuffer(0));
  }

  function looksLikeDockerHost(host) {
    return /^[a-z0-9-]+$/i.test(host)
      && /[a-z]/i.test(host)
      && /\d/.test(host)
      && !host.includes('.');
  }

  function sanitizeInboundSipMessage(message) {
    const text = sipMessageText(message);
    if (!/^INVITE\s/i.test(text)) return message;
    const sipDomain = (els.sipDomain.value || '').trim();
    if (!sipDomain) return message;
    let changed = false;
    const sanitized = text.replace(/^(From|f|Contact|m):([^\r\n]*)$/gmi, (line, header, value) => {
      const nextValue = value.replace(/@([A-Za-z0-9-]+)(?=[:;>])/g, (match, host) => {
        if (!looksLikeDockerHost(host)) return match;
        changed = true;
        return `@${sipDomain}`;
      });
      return `${header}:${nextValue}`;
    });
    if (changed) logLine(`WS in: sanitized SIP host to ${sipDomain}`);
    return changed ? sanitized : message;
  }

  function bindSocketDiagnostics(socket) {
    if (!socket || socket.__softphoneDiagnostics) return;
    socket.__softphoneDiagnostics = true;
    const originalSend = socket.send.bind(socket);
    socket.send = (message) => {
      const firstLine = sipFirstLine(message);
      if (firstLine) logLine(`WS out: ${firstLine}`);
      return originalSend(message);
    };
    if (typeof socket._onMessage === 'function') {
      const originalOnMessage = socket._onMessage.bind(socket);
      socket._onMessage = (event) => {
        const firstLine = sipFirstLine(event && event.data);
        if (firstLine) logLine(`WS in: ${firstLine}`);
        if (/^(CANCEL|BYE)\s/i.test(firstLine)) {
          logLine(`Incoming call cleared by ${firstLine.split(/\s+/)[0]}`);
          setCallStatus('Call ended', 'warn');
          resetSessionState();
        }
        const data = sanitizeInboundSipMessage(event && event.data);
        try {
          return originalOnMessage({ data });
        } catch (error) {
          const detail = error && (error.stack || error.message) ? (error.stack || error.message) : error;
          logLine(`WS handler error: ${String(detail).slice(0, 220)}`);
          throw error;
        }
      };
    }
  }

  function updateCallButtons() {
    els.callBtn.classList.remove('ready', 'incoming', 'busy');
    const dialLocked = Boolean(state.currentSession || state.incomingSession);
    els.dialNumber.readOnly = dialLocked;
    if (state.incomingSession) {
      els.callBtn.textContent = 'Answer';
      els.callBtn.classList.add('incoming');
      return;
    }
    if (state.currentSession) {
      els.callBtn.textContent = 'Hang Up';
      els.callBtn.classList.add('busy');
      return;
    }
    els.callBtn.textContent = 'Call';
    if (state.isRegistered) els.callBtn.classList.add('ready');
  }

  function startRingtone() {
    if (state.ringtone) return;
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) {
      logLine('Incoming ringtone is not supported in this browser');
      return;
    }
    try {
      const ctx = new AudioContext();
      const gain = ctx.createGain();
      const filter = ctx.createBiquadFilter();
      const oscillators = [440, 480].map((frequency) => {
        const osc = ctx.createOscillator();
        osc.type = 'sine';
        osc.frequency.value = frequency;
        osc.connect(filter);
        osc.start();
        return osc;
      });
      filter.type = 'lowpass';
      filter.frequency.value = 1200;
      gain.gain.value = 0;
      filter.connect(gain);
      gain.connect(ctx.destination);

      const setLevel = (delay, level) => {
        const time = ctx.currentTime + delay;
        gain.gain.cancelScheduledValues(time);
        gain.gain.setTargetAtTime(level, time, 0.035);
      };
      const playPattern = () => {
        setLevel(0.0, 0.075);
        setLevel(0.42, 0.0);
        setLevel(0.72, 0.075);
        setLevel(1.14, 0.0);
      };
      playPattern();
      const interval = setInterval(playPattern, 3200);
      state.ringtone = { ctx, gain, oscillators, interval };
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {
          logLine('Click the webphone once to allow ringtone audio');
        });
      }
    } catch (error) {
      console.warn(error);
      logLine('Incoming ringtone could not start');
    }
  }

  function stopRingtone() {
    if (!state.ringtone) return;
    const ringtone = state.ringtone;
    state.ringtone = null;
    clearInterval(ringtone.interval);
    try {
      const now = ringtone.ctx.currentTime;
      ringtone.gain.gain.cancelScheduledValues(now);
      ringtone.gain.gain.setValueAtTime(0, now);
      (ringtone.oscillators || []).forEach((osc) => {
        try {
          osc.stop(now + 0.02);
        } catch (error) {
          console.warn(error);
        }
      });
      setTimeout(() => ringtone.ctx.close().catch(() => {}), 60);
    } catch (error) {
      console.warn(error);
    }
  }

  function startRingbackTone() {
    if (state.ringback) return;
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    try {
      const ctx = new AudioContext();
      const gain = ctx.createGain();
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = 425;
      gain.gain.value = 0;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();

      const setLevel = (delay, level) => {
        const time = ctx.currentTime + delay;
        gain.gain.cancelScheduledValues(time);
        gain.gain.setTargetAtTime(level, time, 0.04);
      };
      const playPattern = () => {
        setLevel(0.0, 0.055);
        setLevel(0.9, 0.0);
      };
      playPattern();
      const interval = setInterval(playPattern, 3000);
      state.ringback = { ctx, gain, osc, interval };
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {
          logLine('Click the webphone once to allow call audio');
        });
      }
    } catch (error) {
      console.warn(error);
    }
  }

  function stopRingbackTone() {
    if (!state.ringback) return;
    const ringback = state.ringback;
    state.ringback = null;
    clearInterval(ringback.interval);
    try {
      const now = ringback.ctx.currentTime;
      ringback.gain.gain.cancelScheduledValues(now);
      ringback.gain.gain.setValueAtTime(0, now);
      ringback.osc.stop(now + 0.02);
      setTimeout(() => ringback.ctx.close().catch(() => {}), 60);
    } catch (error) {
      console.warn(error);
    }
  }

  function prepareCallAudio() {
    try {
      els.remoteAudio.muted = false;
      els.remoteAudio.volume = Number(els.speakerVolume.value || 1);
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        const ctx = new AudioContext();
        ctx.resume().finally(() => ctx.close().catch(() => {}));
      }
    } catch (error) {
      console.warn(error);
    }
  }

  function updateToggleButton(button, value) {
    if (!button) return;
    button.dataset.toggle = value ? 'true' : 'false';
  }

  function updateRegisterToggle() {
    updateToggleButton(els.dndBtn, !state.isRegistered);
    els.dndBtn.textContent = 'DND';
    els.dndBtn.title = state.isRegistered ? 'Turn on DND and unregister this webphone' : 'Turn off DND and register this webphone';
  }

  async function saveSettings() {
    await storageSet({
      wsUrl: els.wsUrl.value.trim(),
      sipDomain: els.sipDomain.value.trim(),
      sipUser: els.sipUser.value.trim(),
      authUser: els.authUser.value.trim(),
      sipPass: els.sipPass.value,
      displayName: els.displayName.value.trim(),
      autoAnswer: state.autoAnswer
    });
    setAccountLabel();
  }

  async function loadSettings(consumeAutoRegister = true) {
    const data = { ...DEFAULTS, ...(await storageGet(Object.keys(DEFAULTS).concat(['pendingNumber']))) };
    els.wsUrl.value = data.wsUrl || '';
    els.sipDomain.value = data.sipDomain || '';
    els.sipUser.value = data.sipUser || '';
    els.authUser.value = data.authUser || '';
    els.sipPass.value = data.sipPass || '';
    els.displayName.value = data.displayName || '';
    state.autoAnswer = Boolean(data.autoAnswer);
    state.iceServers = Array.isArray(data.iceServers) ? data.iceServers : [];
    updateRegisterToggle();
    updateToggleButton(els.autoAnswerBtn, state.autoAnswer);
    if (data.pendingNumber) {
      setDialNumber(data.pendingNumber, false);
      storageSet({ pendingNumber: '' });
    }
    setAccountLabel();
    if (consumeAutoRegister && data.autoRegister) {
      await storageSet({ autoRegister: false });
      setTimeout(registerUA, 250);
    }
  }

  function validateBeforeRegister() {
    if (!window.JsSIP || !window.JsSIP.UA) {
      setStatus('JsSIP file missing', 'bad');
      alert('jssip.min.js is only a placeholder in this demo. Replace it with the official JsSIP browser build, then reload the extension.');
      return false;
    }
    if (!els.wsUrl.value.trim().startsWith('wss://')) {
      setStatus('Use a wss:// WebSocket URL', 'bad');
      alert('WebRTC SIP registration requires a secure WSS URL, for example: wss://pbx.example.com:8089/ws');
      return false;
    }
    if (!currentAccountUri()) {
      setStatus('SIP account incomplete', 'bad');
      alert('Enter extension and SIP domain/PBX host.');
      return false;
    }
    return true;
  }

  async function registerUA() {
    if (state.registering) return;
    if (!validateBeforeRegister()) return;
    state.manualUnregister = false;
    clearRegisterRetry();
    await saveSettings();
    const nextAccountKey = accountKey();
    if (state.ua && state.isRegistered && state.accountKey === nextAccountKey) {
      setStatus('Registered', 'ok');
      updateCallButtons();
      logLine('Already registered');
      return;
    }

    try {
      state.registering = true;
      if (state.ua) {
        state.ua.stop();
        state.ua = null;
      }

      const socket = new JsSIP.WebSocketInterface(els.wsUrl.value.trim());
      bindSocketDiagnostics(socket);
      const contactUri = `sip:${safeSipUser(els.sipUser.value.trim())}@${randomContactHost()};transport=ws`;
      const config = {
        sockets: [socket],
        uri: currentAccountUri(),
        contact_uri: contactUri,
        password: els.sipPass.value,
        display_name: els.displayName.value.trim() || els.sipUser.value.trim(),
        session_timers: false,
        register: true
      };
      if (els.authUser.value.trim()) config.authorization_user = els.authUser.value.trim();

      state.ua = new JsSIP.UA(config);
      state.accountKey = nextAccountKey;
      bindUAEvents(state.ua);
      state.ua.start();
      setStatus('Connecting...', 'warn');
      logLine('Connecting to SIP WSS');
      logLine(`SIP contact user: ${safeSipUser(els.sipUser.value.trim())}`);
    } catch (error) {
      console.error(error);
      setStatus(`Register error: ${error.message || error}`, 'bad');
      scheduleRegisterRetry('register error');
    } finally {
      state.registering = false;
    }
  }

  function unregisterUA() {
    state.manualUnregister = true;
    clearRegisterRetry();
    storageSet({ keepRegistered: false, autoRegister: false });
    try {
      if (state.currentSession) state.currentSession.terminate();
      if (state.ua) state.ua.stop();
    } catch (error) {
      console.warn(error);
    }
    state.ua = null;
    state.isRegistered = false;
    state.accountKey = '';
    resetSessionState();
    setStatus('Not registered');
    updateRegisterToggle();
    updateCallButtons();
    logLine('Unregistered');
  }

  function clearRegisterRetry() {
    if (!state.retryTimer) return;
    clearTimeout(state.retryTimer);
    state.retryTimer = null;
  }

  async function scheduleRegisterRetry(reason) {
    if (state.manualUnregister || state.retryTimer) return;
    const values = await storageGet(['keepRegistered']);
    if (!values.keepRegistered) return;
    state.retryTimer = setTimeout(() => {
      state.retryTimer = null;
      logLine(`Retrying registration after ${reason}`);
      registerUA();
    }, 2500);
  }

  function bindUAEvents(ua) {
    ua.on('connected', () => {
      setStatus('Connected, registering...', 'warn');
      callTiming('SIP WebSocket connected');
    });
    ua.on('disconnected', () => {
      state.isRegistered = false;
      runtimeMessage({ type: 'SOFTPHONE_PAGE_UNREGISTERED' });
      setStatus('Disconnected', 'bad');
      updateRegisterToggle();
      updateCallButtons();
      scheduleRegisterRetry('disconnect');
    });
    ua.on('registered', () => {
      state.isRegistered = true;
      clearRegisterRetry();
      storageSet({ keepRegistered: true, autoRegister: false });
      setStatus('Registered', 'ok');
      updateRegisterToggle();
      updateCallButtons();
      logLine('Registered successfully');
      runtimeMessage({ type: 'SOFTPHONE_PAGE_REGISTERED' });
      callTiming('SIP registered');
      if (state.pendingCall) {
        const pending = state.pendingCall;
        state.pendingCall = null;
        setDialNumber(pending.number, false);
        setTimeout(() => callNumber(pending.withVideo), 150);
      }
    });
    ua.on('unregistered', () => {
      state.isRegistered = false;
      runtimeMessage({ type: 'SOFTPHONE_PAGE_UNREGISTERED' });
      setStatus('Unregistered', 'warn');
      updateRegisterToggle();
      updateCallButtons();
      scheduleRegisterRetry('unregister');
    });
    ua.on('registrationFailed', (event) => {
      state.isRegistered = false;
      runtimeMessage({ type: 'SOFTPHONE_PAGE_UNREGISTERED' });
      const cause = event && (event.cause || event.response && event.response.reason_phrase) || 'Registration failed';
      setStatus(String(cause), 'bad');
      updateRegisterToggle();
      updateCallButtons();
      logLine(`Registration failed: ${cause}`);
      callTiming(`Registration failed: ${cause}`);
      scheduleRegisterRetry(String(cause));
    });
    ua.on('newRTCSession', handleRTCSession);
  }

  function handleRTCSession(data) {
    const session = data.session;

    if (state.currentSession && state.currentSession !== session) {
      session.terminate({ status_code: 486, reason_phrase: 'Busy Here' });
      return;
    }

    state.currentSession = session;
    state.callAnswered = false;
    setupSessionEvents(session);

    if (data.originator === 'remote') {
      const remoteIdentity = session.remote_identity && session.remote_identity.uri
        ? session.remote_identity.uri.toString()
        : 'Unknown caller';
      state.callStartedAt = performance.now();
      callTiming('Incoming RTC session received');
      logLine(`Incoming call from ${remoteIdentity}`);

      state.incomingSession = session;
      setStatus(`Incoming: ${remoteIdentity}`, 'warn');
      updateCallButtons();
      startRingtone();
      runtimeMessage({ type: 'SOFTPHONE_INCOMING_CALL', caller: remoteIdentity });

      if (state.autoAnswer) {
        answerCall(false);
      }
    } else {
      setCallStatus('Calling...', 'warn');
      updateCallButtons();
      callTiming('RTC session created');
    }
  }

  function setupSessionEvents(session) {
    let iceReadyTimer = null;
    let iceReadyDone = false;
    const markIceReady = (ready, reason) => {
      if (iceReadyDone || typeof ready !== 'function') return;
      iceReadyDone = true;
      if (iceReadyTimer) clearTimeout(iceReadyTimer);
      callTiming(`ICE ready: ${reason}`);
      ready();
    };
    session.on('icecandidate', (event) => {
      const candidate = event && event.candidate && event.candidate.candidate || '';
      const typeMatch = candidate.match(/\btyp\s+(\w+)/);
      const candidateType = typeMatch ? typeMatch[1] : 'unknown';
      callTiming(`ICE candidate ${candidateType}`);
      if (candidateType === 'srflx' || candidateType === 'relay') {
        markIceReady(event.ready, candidateType);
      } else if (!iceReadyTimer && event && typeof event.ready === 'function') {
        iceReadyTimer = setTimeout(() => markIceReady(event.ready, 'timeout'), 1200);
      }
    });
    session.on('sdp', (event) => {
      if (event && event.originator === 'local') {
        event.sdp = preferG711Audio(event.sdp);
        callTiming('Local SDP ready');
      }
    });
    session.on('getusermediafailed', (error) => {
      callTiming(`Microphone failed: ${error && error.message ? error.message : error}`);
    });
    session.on('peerconnection', (data) => {
      callTiming('Peer connection created');
      bindPeerConnection(data.peerconnection || session.connection);
    });
    session.on('progress', () => {
      if (state.callAnswered) return;
      setCallStatus('Ringing...', 'warn');
      callTiming('SIP progress/ringing');
      if (!state.incomingSession) startRingbackTone();
    });
    session.on('accepted', () => {
      stopRingtone();
      stopRingbackTone();
      state.callAnswered = true;
      setCallStatus('In call', 'ok');
      logLine('Call accepted');
      callTiming('Call accepted');
      startTalkTimer();
      attachRemoteReceivers(session, 'accepted');
      playRemoteAudio('accepted');
      state.incomingSession = null;
      updateCallButtons();
    });
    session.on('confirmed', () => {
      stopRingtone();
      stopRingbackTone();
      state.callAnswered = true;
      setCallStatus('In call', 'ok');
      logLine('Call connected');
      callTiming('Call connected');
      if (!state.talkStartedAt) startTalkTimer();
      state.incomingSession = null;
      updateCallButtons();
      attachRemoteReceivers(session, 'confirmed');
      playRemoteAudio('confirmed');
      attachLocalPreview(session);
      startInboundAudioStats(session);
    });
    session.on('ended', (event) => {
      stopRingbackTone();
      const detail = sessionEventDetail(event, 'Ended');
      logLine(`Call ended: ${detail}`);
      setStatus(`Ended: ${shortStatus(detail)}`, 'warn');
      resetSessionState();
    });
    session.on('failed', (event) => {
      stopRingbackTone();
      const detail = sessionEventDetail(event, 'Failed');
      logLine(`Call failed: ${detail}`);
      callTiming(`Call failed: ${detail}`);
      setStatus(`Failed: ${shortStatus(detail)}`, 'bad');
      resetSessionState();
    });
    session.on('muted', () => setStatus('Microphone muted', 'warn'));
    session.on('unmuted', () => setStatus('In call', 'ok'));
    session.on('hold', () => setStatus('On hold', 'warn'));
    session.on('unhold', () => setStatus('In call', 'ok'));
  }

  function sessionEventDetail(event, fallback) {
    if (!event) return fallback;
    const parts = [];
    const cause = event.cause || fallback;
    if (cause) parts.push(String(cause));
    const response = event.response || event.message;
    const statusCode = response && (response.status_code || response.statusCode);
    const reason = response && (response.reason_phrase || response.reasonPhrase);
    if (statusCode || reason) {
      parts.push(`SIP ${[statusCode, reason].filter(Boolean).join(' ')}`);
    }
    if (event.originator) parts.push(`by ${event.originator}`);
    return parts.join(' - ') || fallback;
  }

  function shortStatus(text) {
    const value = String(text || '');
    return value.length > 42 ? `${value.slice(0, 39)}...` : value;
  }

  function bindPeerConnection(pc) {
    if (!pc || pc.__softphoneBound) return;
    pc.__softphoneBound = true;
    pc.addEventListener('icegatheringstatechange', () => {
      callTiming(`ICE gathering ${pc.iceGatheringState}`);
    });
    pc.addEventListener('iceconnectionstatechange', () => {
      callTiming(`ICE connection ${pc.iceConnectionState}`);
    });

    pc.addEventListener('track', (event) => {
      const incomingStream = event.streams && event.streams[0];
      const tracks = incomingStream ? incomingStream.getTracks() : [event.track];
      attachRemoteTracks(tracks, 'track');
    });
  }

  function attachRemoteReceivers(session, reason) {
    try {
      const pc = session && session.connection;
      if (!pc || typeof pc.getReceivers !== 'function') return;
      const tracks = pc.getReceivers().map((receiver) => receiver.track).filter(Boolean);
      if (tracks.length) attachRemoteTracks(tracks, reason);
      else callTiming(`No remote receivers yet: ${reason}`);
    } catch (error) {
      console.warn(error);
      callTiming(`Remote receiver check failed: ${reason}`);
    }
  }

  function attachRemoteTracks(tracks, reason) {
    if (!tracks || !tracks.length) return;
    if (!state.remoteStream) state.remoteStream = new MediaStream();
    tracks.forEach((track) => {
      if (!state.remoteStream.getTracks().some((existing) => existing.id === track.id)) {
        state.remoteStream.addTrack(track);
        callTiming(`Remote ${track.kind} track received: ${reason}`);
        track.addEventListener('mute', () => callTiming(`Remote ${track.kind} muted`));
        track.addEventListener('unmute', () => callTiming(`Remote ${track.kind} unmuted`));
        track.addEventListener('ended', () => callTiming(`Remote ${track.kind} ended`));
      }
    });
    els.remoteAudio.srcObject = state.remoteStream;
    els.remoteVideo.srcObject = state.remoteStream;
    playRemoteAudio(reason);
    if (state.remoteStream.getVideoTracks().length) els.mediaPanel.classList.add('active');
  }

  function playRemoteAudio(reason) {
    if (!els.remoteAudio.srcObject) return;
    els.remoteAudio.muted = false;
    els.remoteAudio.volume = Number(els.speakerVolume.value || 1);
    if (!els.remoteAudio.paused && !els.remoteAudio.ended) return;
    const playPromise = els.remoteAudio.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise
        .then(() => callTiming(`Remote audio playing: ${reason}`))
        .catch((error) => callTiming(`Remote audio blocked: ${error && error.message ? error.message : error}`));
    }
  }

  function startInboundAudioStats(session) {
    stopInboundAudioStats();
    const pc = session && session.connection;
    if (!pc || typeof pc.getStats !== 'function') return;
    let lastPackets = null;
    let lastBytes = null;
    state.statsTimer = setInterval(async () => {
      try {
        const report = await pc.getStats();
        report.forEach((stat) => {
          if (stat.type !== 'inbound-rtp' || stat.kind !== 'audio') return;
          const packets = Number(stat.packetsReceived || 0);
          const bytes = Number(stat.bytesReceived || 0);
          const packetsDelta = lastPackets === null ? 0 : packets - lastPackets;
          const bytesDelta = lastBytes === null ? 0 : bytes - lastBytes;
          lastPackets = packets;
          lastBytes = bytes;
          callTiming(`Inbound audio packets=${packets} (+${packetsDelta}) bytes=${bytes} (+${bytesDelta}) level=${stat.audioLevel ?? 'n/a'}`);
        });
      } catch (error) {
        callTiming(`Inbound audio stats failed: ${error && error.message ? error.message : error}`);
      }
    }, 3000);
  }

  function stopInboundAudioStats() {
    if (!state.statsTimer) return;
    clearInterval(state.statsTimer);
    state.statsTimer = null;
  }

  function attachLocalPreview(session) {
    try {
      const pc = session.connection;
      if (!pc) return;
      const local = new MediaStream();
      pc.getSenders().forEach((sender) => {
        if (sender.track) local.addTrack(sender.track);
      });
      state.localStream = local;
      els.localVideo.srcObject = local;
      if (local.getVideoTracks().length) els.mediaPanel.classList.add('active');
    } catch (error) {
      console.warn(error);
    }
  }

  function resetSessionState() {
    if (state.hangupResetTimer) {
      clearTimeout(state.hangupResetTimer);
      state.hangupResetTimer = null;
    }
    stopRingtone();
    stopRingbackTone();
    stopRecording(true);
    stopInboundAudioStats();
    stopTalkTimer();
    state.currentSession = null;
    state.incomingSession = null;
    state.callAnswered = false;
    state.remoteStream = null;
    state.localStream = null;
    state.isMuted = false;
    els.remoteAudio.srcObject = null;
    els.remoteVideo.srcObject = null;
    els.localVideo.srcObject = null;
    els.mediaPanel.classList.remove('active');
    els.dialNumber.value = '';
    updateToggleButton(els.recordBtn, false);
    updateCallButtons();
  }

  function callNumber(withVideo = false) {
    if (state.incomingSession) {
      answerCall(withVideo);
      return;
    }
    if (state.currentSession) return;

    const destination = targetUri(els.dialNumber.value);
    if (!destination) {
      setStatus('Enter a number', 'bad');
      return;
    }
    if (!state.ua || !state.isRegistered) {
      if (validateBeforeRegister()) {
        state.callStartedAt = performance.now();
        state.pendingCall = { number: els.dialNumber.value, withVideo };
        setStatus('Registering before call...', 'warn');
        callTiming('Call clicked; registering first');
        registerUA();
      } else {
        els.settingsPanel.classList.add('open');
      }
      return;
    }

    const options = {
      mediaConstraints: { audio: true, video: Boolean(withVideo) },
      pcConfig: currentPeerConnectionConfig(),
      rtcOfferConstraints: { offerToReceiveAudio: true, offerToReceiveVideo: Boolean(withVideo) }
    };

    try {
      prepareCallAudio();
      state.callStartedAt = performance.now();
      setStatus('Starting call...', 'warn');
      callTiming('Call clicked; invoking JsSIP');
      callTiming(`ICE policy: ${options.pcConfig.iceTransportPolicy || 'default'} (${(options.pcConfig.iceServers || []).length} servers)`);
      state.ua.call(destination, options);
      logLine(`Calling ${destination}${withVideo ? ' with video' : ''}`);
    } catch (error) {
      console.error(error);
      setStatus(`Call error: ${error.message || error}`, 'bad');
    }
  }

  async function answerCall(withVideo = false) {
    const session = state.incomingSession;
    if (!session) return;
    try {
      session.answer({
        mediaConstraints: { audio: true, video: Boolean(withVideo) },
        pcConfig: currentPeerConnectionConfig(),
        rtcOfferConstraints: { offerToReceiveAudio: true, offerToReceiveVideo: Boolean(withVideo) }
      });
      setStatus('Answering...', 'warn');
      logLine(`Answered${withVideo ? ' with video' : ''}`);
      state.incomingSession = null;
      stopRingtone();
      updateCallButtons();
    } catch (error) {
      console.error(error);
      setStatus(`Answer failed: ${error.message || error}`, 'bad');
    }
  }

  function currentPeerConnectionConfig() {
    const config = {};
    if (state.iceServers && state.iceServers.length) {
      config.iceServers = state.iceServers;
      if (hasTurnServer(state.iceServers)) {
        config.iceTransportPolicy = 'relay';
      }
    }
    return config;
  }

  function hasTurnServer(iceServers) {
    return iceServers.some((server) => {
      const urls = Array.isArray(server.urls) ? server.urls : [server.urls];
      return urls.some((url) => String(url || '').toLowerCase().startsWith('turn:'));
    });
  }

  function preferG711Audio(sdp) {
    const lines = String(sdp || '').split(/\r\n|\n/);
    const audioIndex = lines.findIndex((line) => line.startsWith('m=audio '));
    if (audioIndex < 0) return sdp;
    const nextMediaIndex = lines.findIndex((line, index) => index > audioIndex && line.startsWith('m='));
    const endIndex = nextMediaIndex < 0 ? lines.length : nextMediaIndex;
    const audioLines = lines.slice(audioIndex, endIndex);
    const codecByPayload = new Map();

    audioLines.forEach((line) => {
      const match = line.match(/^a=rtpmap:(\d+)\s+([^/]+)/i);
      if (match) codecByPayload.set(match[1], match[2].toLowerCase());
    });

    const mParts = lines[audioIndex].trim().split(/\s+/);
    const payloads = mParts.slice(3);
    const g711Payloads = payloads.filter((payload) => ['pcmu', 'pcma'].includes(codecByPayload.get(payload)));
    if (!g711Payloads.length) return sdp;

    const dtmfPayloads = payloads.filter((payload) => codecByPayload.get(payload) === 'telephone-event');
    const allowedPayloads = [...g711Payloads, ...dtmfPayloads.filter((payload) => !g711Payloads.includes(payload))];
    const allowed = new Set(allowedPayloads);
    const filteredLines = lines.filter((line, index) => {
      if (index === audioIndex) return true;
      if (index < audioIndex || index >= endIndex) return true;
      const payloadMatch = line.match(/^a=(?:rtpmap|fmtp|rtcp-fb):(\d+)/i);
      return !payloadMatch || allowed.has(payloadMatch[1]);
    });
    filteredLines[audioIndex] = [...mParts.slice(0, 3), ...allowedPayloads].join(' ');
    return filteredLines.join('\r\n');
  }

  function sendDtmfTone(tone) {
    const session = state.currentSession;
    if (!session || state.incomingSession) return false;
    try {
      if (typeof session.sendDTMF === 'function') {
        session.sendDTMF(tone);
        logLine(`DTMF ${tone}`);
        return true;
      }
    } catch (error) {
      console.warn(error);
      setStatus('DTMF failed', 'bad');
    }
    return false;
  }

  function hangup() {
    const session = state.currentSession || state.incomingSession;
    if (!session) {
      resetSessionState();
      return;
    }
    setStatus('Ending call...', 'warn');
    logLine('Hangup requested');
    try {
      const options = state.incomingSession
        ? { status_code: 486, reason_phrase: 'Busy Here' }
        : { reason_phrase: 'Normal Clearing' };
      session.terminate(options);
    } catch (error) {
      console.warn(error);
      try {
        if (state.ua && typeof state.ua.terminateSessions === 'function') {
          state.ua.terminateSessions({ reason_phrase: 'Normal Clearing' });
        }
      } catch (fallbackError) {
        console.warn(fallbackError);
      }
    }
    state.hangupResetTimer = setTimeout(resetSessionState, 1200);
  }

  function toggleMicMute() {
    const session = state.currentSession;
    if (!session) return;
    try {
      if (state.isMuted) {
        session.unmute({ audio: true });
        state.isMuted = false;
        els.micMuteBtn.textContent = 'Mic';
      } else {
        session.mute({ audio: true });
        state.isMuted = true;
        els.micMuteBtn.textContent = 'Muted';
      }
    } catch (error) {
      console.warn(error);
    }
  }

  function toggleSpeakerMute() {
    state.isSpeakerMuted = !state.isSpeakerMuted;
    els.remoteAudio.muted = state.isSpeakerMuted;
    els.remoteVideo.muted = state.isSpeakerMuted;
    els.speakerMuteBtn.textContent = state.isSpeakerMuted ? 'Muted' : 'Speaker';
  }

  function transferCall() {
    if (!state.currentSession) return;
    const number = prompt('Transfer current call to:');
    if (!number) return;
    const destination = targetUri(number);
    try {
      state.currentSession.refer(destination);
      logLine(`Transfer requested to ${destination}`);
    } catch (error) {
      alert(`Transfer failed: ${error.message || error}`);
    }
  }

  async function copyDialNumber() {
    const number = normalizeNumber(els.dialNumber.value);
    if (!number) return;
    try {
      await navigator.clipboard.writeText(number);
      setStatus('Number copied', 'ok');
      logLine(`Copied ${number}`);
    } catch (error) {
      setStatus('Copy failed', 'bad');
    }
  }

  function toggleRecording() {
    if (state.mediaRecorder && state.mediaRecorder.state === 'recording') {
      stopRecording(false);
      return;
    }
    if (!state.remoteStream) {
      setStatus('No media to record', 'bad');
      return;
    }
    try {
      state.recordedChunks = [];
      state.mediaRecorder = new MediaRecorder(state.remoteStream);
      state.mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size) state.recordedChunks.push(event.data);
      };
      state.mediaRecorder.onstop = () => {
        if (!state.recordedChunks.length) return;
        const blob = new Blob(state.recordedChunks, { type: 'audio/webm' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `softphone-recording-${Date.now()}.webm`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      state.mediaRecorder.start();
      updateToggleButton(els.recordBtn, true);
      setStatus('Recording', 'warn');
      logLine('Recording started');
    } catch (error) {
      console.error(error);
      setStatus('Recording not supported', 'bad');
    }
  }

  function stopRecording(silent) {
    if (state.mediaRecorder && state.mediaRecorder.state === 'recording') {
      state.mediaRecorder.stop();
      if (!silent) logLine('Recording stopped');
    }
    state.mediaRecorder = null;
    updateToggleButton(els.recordBtn, false);
  }

  function showLogs() {
    els.logPanel.hidden = !els.logPanel.hidden;
  }

  function bindUI() {
    els.settingsToggle.addEventListener('click', () => {
      els.settingsPanel.classList.toggle('open');
    });

    [els.wsUrl, els.sipDomain, els.sipUser, els.authUser, els.sipPass, els.displayName]
      .forEach((input) => input.addEventListener('change', saveSettings));

    els.registerBtn.addEventListener('click', registerUA);
    els.unregisterBtn.addEventListener('click', unregisterUA);

    els.keypad.addEventListener('click', (event) => {
      const key = event.target.closest('button')?.dataset.key;
      if (!key) return;
      if (sendDtmfTone(key)) return;
      if (!canEditDialNumber()) return;
      els.dialNumber.value += key;
      els.dialNumber.focus();
    });

    els.dialNumber.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') callNumber(false);
      if (event.key === 'Escape') hangup();
      const allowedKeys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'Tab', 'Enter', 'Escape'];
      if (!canEditDialNumber() && !allowedKeys.includes(event.key) && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
      }
    });

    els.plusBtn.addEventListener('click', () => {
      if (!canEditDialNumber()) return;
      els.dialNumber.value += '+';
      els.dialNumber.focus();
    });
    els.clearBtn.addEventListener('click', () => {
      if (!canEditDialNumber()) return;
      els.dialNumber.value = '';
      els.dialNumber.focus();
    });
    els.backspaceBtn?.addEventListener('click', () => {
      if (!canEditDialNumber()) return;
      els.dialNumber.value = els.dialNumber.value.slice(0, -1);
      els.dialNumber.focus();
    });
    els.copyNumberBtn.addEventListener('click', copyDialNumber);
    els.messageBtn.addEventListener('click', copyDialNumber);

    els.callBtn.addEventListener('click', () => {
      if (state.currentSession && !state.incomingSession) {
        hangup();
        return;
      }
      callNumber(false);
    });
    els.videoCallBtn.addEventListener('click', () => callNumber(true));
    els.transferBtn.addEventListener('click', transferCall);

    els.speakerVolume.addEventListener('input', () => {
      const volume = Number(els.speakerVolume.value);
      els.remoteAudio.volume = volume;
      els.remoteVideo.volume = volume;
    });
    els.speakerMuteBtn.addEventListener('click', toggleSpeakerMute);
    els.micMuteBtn.addEventListener('click', toggleMicMute);

    els.dndBtn.addEventListener('click', async () => {
      if (state.isRegistered || state.ua) {
        unregisterUA();
        setStatus('DND on', 'warn');
        return;
      }
      await registerUA();
    });

    els.autoAnswerBtn.addEventListener('click', async () => {
      state.autoAnswer = !state.autoAnswer;
      updateToggleButton(els.autoAnswerBtn, state.autoAnswer);
      await saveSettings();
      setStatus(state.autoAnswer ? 'Auto-answer enabled' : 'Auto-answer disabled', state.autoAnswer ? 'warn' : (state.isRegistered ? 'ok' : 'idle'));
    });

    els.confBtn.addEventListener('click', () => {
      const next = els.confBtn.dataset.toggle !== 'true';
      updateToggleButton(els.confBtn, next);
      setStatus(next ? 'Conference UI enabled' : 'Conference UI disabled', 'warn');
      alert('Conference mixing depends on PBX support. This button is a UI placeholder; use PBX feature codes or server-side conference rooms.');
    });

    if (els.recordBtn) els.recordBtn.addEventListener('click', toggleRecording);

    document.querySelector('[data-view="logs"]')?.addEventListener('click', showLogs);
    document.querySelector('[data-view="contacts"]')?.addEventListener('click', () => {
      alert('Contacts tab is ready for your CRM/contact-list integration.');
    });

    window.addEventListener('beforeunload', saveSettings);
    window.addEventListener('resize', rememberWindowSize);
    rememberWindowSize();

    if (hasChrome) {
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== 'local' || !changes.pendingNumber?.newValue) return;
        if (!canEditDialNumber()) return;
        setDialNumber(changes.pendingNumber.newValue);
        storageSet({ pendingNumber: '' });
      });
      chrome.runtime.onMessage.addListener((message) => {
        if (message && message.type === 'SOFTPHONE_SET_NUMBER' && canEditDialNumber()) {
          setDialNumber(message.number);
        }
        if (message && message.type === 'SOFTPHONE_REGISTER_NOW') {
          loadSettings(false).then(async () => {
            await storageSet({ autoRegister: false });
            registerUA();
          });
        }
      });
    }
  }

  async function init() {
    await loadSettings();
    bindUI();
    updateRegisterToggle();
    updateCallButtons();
    if (!window.JsSIP || !window.JsSIP.UA) {
      setStatus('Not registered');
    }
  }

  init();
})();
