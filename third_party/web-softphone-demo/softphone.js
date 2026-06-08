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
    accountLabel: $('accountLabel')
  };

  const state = {
    ua: null,
    currentSession: null,
    incomingSession: null,
    remoteStream: null,
    localStream: null,
    isRegistered: false,
    dnd: false,
    autoAnswer: false,
    isMuted: false,
    isSpeakerMuted: false,
    mediaRecorder: null,
    recordedChunks: []
  };

  const DEFAULTS = {
    wsUrl: '',
    sipDomain: '',
    sipUser: '',
    authUser: '',
    sipPass: '',
    displayName: '',
    dnd: false,
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

  function setAccountLabel() {
    els.accountLabel.textContent = els.sipUser.value.trim() || '—';
  }

  function logLine(text) {
    const li = document.createElement('li');
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    li.textContent = `${time}  ${text}`;
    els.callLog.prepend(li);
    while (els.callLog.children.length > 30) els.callLog.lastElementChild.remove();
  }

  function updateCallButtons() {
    els.callBtn.classList.remove('ready', 'incoming', 'busy');
    if (state.incomingSession) {
      els.callBtn.textContent = 'Answer';
      els.callBtn.classList.add('incoming');
      return;
    }
    if (state.currentSession) {
      els.callBtn.textContent = 'In Call';
      els.callBtn.classList.add('busy');
      return;
    }
    els.callBtn.textContent = 'Call';
    if (state.isRegistered) els.callBtn.classList.add('ready');
  }

  function updateToggleButton(button, value) {
    if (!button) return;
    button.dataset.toggle = value ? 'true' : 'false';
  }

  async function saveSettings() {
    await storageSet({
      wsUrl: els.wsUrl.value.trim(),
      sipDomain: els.sipDomain.value.trim(),
      sipUser: els.sipUser.value.trim(),
      authUser: els.authUser.value.trim(),
      sipPass: els.sipPass.value,
      displayName: els.displayName.value.trim(),
      dnd: state.dnd,
      autoAnswer: state.autoAnswer
    });
    setAccountLabel();
  }

  async function loadSettings() {
    const data = { ...DEFAULTS, ...(await storageGet(Object.keys(DEFAULTS).concat(['pendingNumber']))) };
    els.wsUrl.value = data.wsUrl || '';
    els.sipDomain.value = data.sipDomain || '';
    els.sipUser.value = data.sipUser || '';
    els.authUser.value = data.authUser || '';
    els.sipPass.value = data.sipPass || '';
    els.displayName.value = data.displayName || '';
    state.dnd = Boolean(data.dnd);
    state.autoAnswer = Boolean(data.autoAnswer);
    updateToggleButton(els.dndBtn, state.dnd);
    updateToggleButton(els.autoAnswerBtn, state.autoAnswer);
    if (data.pendingNumber) {
      els.dialNumber.value = normalizeNumber(data.pendingNumber);
      storageSet({ pendingNumber: '' });
    }
    setAccountLabel();
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
    if (!validateBeforeRegister()) return;
    await saveSettings();

    try {
      if (state.ua) {
        state.ua.stop();
        state.ua = null;
      }

      const socket = new JsSIP.WebSocketInterface(els.wsUrl.value.trim());
      const config = {
        sockets: [socket],
        uri: currentAccountUri(),
        password: els.sipPass.value,
        display_name: els.displayName.value.trim() || els.sipUser.value.trim(),
        session_timers: false,
        register: true
      };
      if (els.authUser.value.trim()) config.authorization_user = els.authUser.value.trim();

      state.ua = new JsSIP.UA(config);
      bindUAEvents(state.ua);
      state.ua.start();
      setStatus('Connecting...', 'warn');
      logLine('Connecting to SIP WSS');
    } catch (error) {
      console.error(error);
      setStatus(`Register error: ${error.message || error}`, 'bad');
    }
  }

  function unregisterUA() {
    try {
      if (state.currentSession) state.currentSession.terminate();
      if (state.ua) state.ua.stop();
    } catch (error) {
      console.warn(error);
    }
    state.ua = null;
    state.isRegistered = false;
    resetSessionState();
    setStatus('Not registered');
    updateCallButtons();
    logLine('Unregistered');
  }

  function bindUAEvents(ua) {
    ua.on('connected', () => setStatus('Connected, registering...', 'warn'));
    ua.on('disconnected', () => {
      state.isRegistered = false;
      setStatus('Disconnected', 'bad');
      updateCallButtons();
    });
    ua.on('registered', () => {
      state.isRegistered = true;
      setStatus('Registered', 'ok');
      updateCallButtons();
      logLine('Registered successfully');
    });
    ua.on('unregistered', () => {
      state.isRegistered = false;
      setStatus('Unregistered', 'warn');
      updateCallButtons();
    });
    ua.on('registrationFailed', (event) => {
      state.isRegistered = false;
      const cause = event && (event.cause || event.response && event.response.reason_phrase) || 'Registration failed';
      setStatus(String(cause), 'bad');
      updateCallButtons();
      logLine(`Registration failed: ${cause}`);
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
    setupSessionEvents(session);

    if (data.originator === 'remote') {
      const remoteIdentity = session.remote_identity && session.remote_identity.uri
        ? session.remote_identity.uri.toString()
        : 'Unknown caller';
      logLine(`Incoming call from ${remoteIdentity}`);

      if (state.dnd) {
        session.terminate({ status_code: 486, reason_phrase: 'Do Not Disturb' });
        setStatus('Rejected by DND', 'warn');
        return;
      }

      state.incomingSession = session;
      setStatus(`Incoming: ${remoteIdentity}`, 'warn');
      updateCallButtons();

      if (state.autoAnswer) {
        answerCall(false);
      }
    } else {
      setStatus('Calling...', 'warn');
      updateCallButtons();
    }
  }

  function setupSessionEvents(session) {
    session.on('peerconnection', (data) => {
      bindPeerConnection(data.peerconnection || session.connection);
    });
    session.on('progress', () => setStatus('Ringing...', 'warn'));
    session.on('accepted', () => {
      setStatus('Call accepted', 'ok');
      logLine('Call accepted');
      state.incomingSession = null;
      updateCallButtons();
    });
    session.on('confirmed', () => {
      setStatus('In call', 'ok');
      logLine('Call connected');
      state.incomingSession = null;
      updateCallButtons();
      attachLocalPreview(session);
    });
    session.on('ended', (event) => {
      const cause = event && event.cause ? event.cause : 'Ended';
      logLine(`Call ended: ${cause}`);
      setStatus('Call ended', 'warn');
      resetSessionState();
    });
    session.on('failed', (event) => {
      const cause = event && event.cause ? event.cause : 'Failed';
      logLine(`Call failed: ${cause}`);
      setStatus(`Failed: ${cause}`, 'bad');
      resetSessionState();
    });
    session.on('muted', () => setStatus('Microphone muted', 'warn'));
    session.on('unmuted', () => setStatus('In call', 'ok'));
    session.on('hold', () => setStatus('On hold', 'warn'));
    session.on('unhold', () => setStatus('In call', 'ok'));
  }

  function bindPeerConnection(pc) {
    if (!pc || pc.__softphoneBound) return;
    pc.__softphoneBound = true;

    pc.addEventListener('track', (event) => {
      if (!state.remoteStream) state.remoteStream = new MediaStream();
      const incomingStream = event.streams && event.streams[0];
      const tracks = incomingStream ? incomingStream.getTracks() : [event.track];
      tracks.forEach((track) => {
        if (!state.remoteStream.getTracks().some((existing) => existing.id === track.id)) {
          state.remoteStream.addTrack(track);
        }
      });
      els.remoteAudio.srcObject = state.remoteStream;
      els.remoteVideo.srcObject = state.remoteStream;
      if (state.remoteStream.getVideoTracks().length) els.mediaPanel.classList.add('active');
    });
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
    stopRecording(true);
    state.currentSession = null;
    state.incomingSession = null;
    state.remoteStream = null;
    state.localStream = null;
    state.isMuted = false;
    els.remoteAudio.srcObject = null;
    els.remoteVideo.srcObject = null;
    els.localVideo.srcObject = null;
    els.mediaPanel.classList.remove('active');
    updateToggleButton(els.recordBtn, false);
    updateCallButtons();
  }

  function callNumber(withVideo = false) {
    if (state.incomingSession) {
      answerCall(withVideo);
      return;
    }
    if (!state.ua || !state.isRegistered) {
      setStatus('Register first', 'bad');
      els.settingsPanel.classList.add('open');
      return;
    }
    if (state.currentSession) return;

    const destination = targetUri(els.dialNumber.value);
    if (!destination) {
      setStatus('Enter a number', 'bad');
      return;
    }

    const options = {
      mediaConstraints: { audio: true, video: Boolean(withVideo) },
      pcConfig: { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] },
      rtcOfferConstraints: { offerToReceiveAudio: true, offerToReceiveVideo: Boolean(withVideo) }
    };

    try {
      state.ua.call(destination, options);
      logLine(`Calling ${destination}${withVideo ? ' with video' : ''}`);
    } catch (error) {
      console.error(error);
      setStatus(`Call error: ${error.message || error}`, 'bad');
    }
  }

  function answerCall(withVideo = false) {
    const session = state.incomingSession;
    if (!session) return;
    try {
      session.answer({
        mediaConstraints: { audio: true, video: Boolean(withVideo) },
        pcConfig: { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] },
        rtcOfferConstraints: { offerToReceiveAudio: true, offerToReceiveVideo: Boolean(withVideo) }
      });
      setStatus('Answering...', 'warn');
      logLine(`Answered${withVideo ? ' with video' : ''}`);
      state.incomingSession = null;
      updateCallButtons();
    } catch (error) {
      console.error(error);
      setStatus(`Answer failed: ${error.message || error}`, 'bad');
    }
  }

  function hangup() {
    try {
      if (state.currentSession) state.currentSession.terminate();
    } catch (error) {
      console.warn(error);
    } finally {
      resetSessionState();
    }
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
      els.dialNumber.value += key;
      els.dialNumber.focus();
    });

    els.dialNumber.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') callNumber(false);
      if (event.key === 'Escape') hangup();
    });

    els.plusBtn.addEventListener('click', () => {
      els.dialNumber.value += '+';
      els.dialNumber.focus();
    });
    els.clearBtn.addEventListener('click', () => {
      els.dialNumber.value = '';
      els.dialNumber.focus();
    });
    els.backspaceBtn?.addEventListener('click', () => {
      els.dialNumber.value = els.dialNumber.value.slice(0, -1);
      els.dialNumber.focus();
    });
    els.copyNumberBtn.addEventListener('click', copyDialNumber);
    els.messageBtn.addEventListener('click', copyDialNumber);

    els.callBtn.addEventListener('click', () => callNumber(false));
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
      state.dnd = !state.dnd;
      updateToggleButton(els.dndBtn, state.dnd);
      await saveSettings();
      setStatus(state.dnd ? 'DND enabled' : 'DND disabled', state.dnd ? 'warn' : (state.isRegistered ? 'ok' : 'idle'));
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

    if (hasChrome) {
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== 'local' || !changes.pendingNumber?.newValue) return;
        els.dialNumber.value = normalizeNumber(changes.pendingNumber.newValue);
        storageSet({ pendingNumber: '' });
      });
      chrome.runtime.onMessage.addListener((message) => {
        if (message && message.type === 'SOFTPHONE_SET_NUMBER') {
          els.dialNumber.value = normalizeNumber(message.number);
        }
      });
    }
  }

  async function init() {
    await loadSettings();
    bindUI();
    updateCallButtons();
    if (!window.JsSIP || !window.JsSIP.UA) {
      setStatus('Not registered');
    }
  }

  init();
})();
