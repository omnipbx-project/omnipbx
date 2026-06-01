(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const dock = $("webphone-dock");
  const panel = $("webphone-panel");
  if (!dock || !panel) return;

  const detached = Boolean($("webphone-detached-bootstrap"));
  const state = {
    config: null,
    ua: null,
    session: null,
    incoming: null,
    registered: false,
    muted: false,
    speakerMuted: false,
    held: false,
    dnd: false,
    remoteStream: null,
    localStream: null,
    disconnectTimer: null,
  };

  const els = {
    trigger: $("webphone-trigger"),
    triggerDot: $("webphone-trigger-dot"),
    close: $("webphone-close"),
    detach: $("webphone-detach"),
    attach: $("webphone-attach"),
    account: $("webphone-account"),
    status: $("webphone-status"),
    dot: $("webphone-dot"),
    picker: $("webphone-picker"),
    extension: $("webphone-extension"),
    number: $("webphone-number"),
    copy: $("webphone-copy"),
    keypad: $("webphone-keypad"),
    call: $("webphone-call"),
    video: $("webphone-video"),
    hangup: $("webphone-hangup"),
    mute: $("webphone-mute"),
    speaker: $("webphone-speaker"),
    hold: $("webphone-hold"),
    transfer: $("webphone-transfer"),
    dnd: $("webphone-dnd"),
    volume: $("webphone-volume"),
    log: $("webphone-log"),
    audio: $("webphone-remote-audio"),
    remoteVideo: $("webphone-remote-video"),
    localVideo: $("webphone-local-video"),
    videoBox: $("webphone-video-box"),
  };

  function setOpen(open) {
    dock.hidden = false;
    dock.classList.toggle("open", open || detached);
    if (open && !els.number.value) {
      const selected = normalizeNumber(String(window.getSelection ? window.getSelection() : ""));
      if (/^[+0-9().\-\s]{3,}$/.test(selected)) els.number.value = selected.replace(/[().\-\s]/g, "");
    }
    if (detached) {
      dock.classList.add("detached");
      panel.dataset.detached = "true";
    }
  }

  function setStatus(text, tone) {
    if (els.status) els.status.textContent = text;
    if (els.dot) els.dot.dataset.tone = tone || "idle";
    if (els.triggerDot) els.triggerDot.dataset.tone = tone || "idle";
  }

  function log(text) {
    if (!els.log) return;
    const item = document.createElement("li");
    item.textContent = `${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})} ${text}`;
    els.log.prepend(item);
    while (els.log.children.length > 6) els.log.lastElementChild.remove();
  }

  function normalizeNumber(value) {
    return String(value || "").replace(/^sip:/i, "").replace(/[<>"']/g, "").trim();
  }

  function targetUri(value) {
    const number = normalizeNumber(value);
    if (!number) return "";
    if (number.includes("@")) return number.startsWith("sip:") ? number : `sip:${number}`;
    return `sip:${number}@${state.config.sip_domain}`;
  }

  function setAccount(config) {
    if (!config) {
      els.account.textContent = "Not ready";
      return;
    }
    const label = config.display_name || config.extension || "Webphone";
    els.account.textContent = config.extension && config.extension !== label ? `${label} · ${config.extension}` : label;
    state.dnd = Boolean(config.dnd_enabled);
    toggleButton(els.dnd, state.dnd);
  }

  function toggleButton(button, enabled) {
    if (!button) return;
    button.dataset.active = enabled ? "true" : "false";
  }

  async function loadBootstrap(extension) {
    const detachedBootstrap = $("webphone-detached-bootstrap");
    if (detachedBootstrap && !extension) {
      try {
        const data = JSON.parse(detachedBootstrap.textContent || "{}");
        applyBootstrap(data);
        return;
      } catch (error) {
        console.warn(error);
      }
    }
    const params = extension ? `?extension=${encodeURIComponent(extension)}` : "";
    const response = await fetch(`/api/softphone/bootstrap/current${params}`, {cache: "no-store"});
    if (!response.ok) throw new Error("Unable to load webphone settings.");
    applyBootstrap(await response.json());
  }

  function applyBootstrap(data) {
    const config = data.config || null;
    state.config = config;
    setAccount(config);
    renderExtensionPicker(data.extensions || [], config && config.extension, Boolean(data.can_switch));
    if (!data.available || !config) {
      setStatus(data.message || "Webphone not ready", "warn");
      return;
    }
    if (!window.JsSIP || !window.JsSIP.UA) {
      setStatus("Phone engine not loaded", "bad");
      return;
    }
    register();
  }

  function renderExtensionPicker(extensions, selected, canSwitch) {
    if (!els.picker || !els.extension || !canSwitch || extensions.length <= 1) {
      if (els.picker) els.picker.hidden = true;
      return;
    }
    els.extension.innerHTML = extensions.map((item) => (
      `<option value="${escapeHtml(item.extension)}" ${item.extension === selected ? "selected" : ""}>${escapeHtml(item.extension)} - ${escapeHtml(item.display_name || "")}</option>`
    )).join("");
    els.picker.hidden = false;
  }

  function register() {
    const config = state.config;
    if (!config || !config.webrtc_ready) return;
    if (state.ua) {
      try { state.ua.stop(); } catch (error) { console.warn(error); }
    }
    const socket = new JsSIP.WebSocketInterface(config.websocket_url);
    state.ua = new JsSIP.UA({
      sockets: [socket],
      uri: `sip:${config.extension}@${config.sip_domain}`,
      authorization_user: config.extension,
      password: config.secret,
      display_name: config.display_name || config.extension,
      session_timers: false,
      register: true,
    });
    bindUa(state.ua);
    state.ua.start();
    setStatus("Connecting...", "warn");
  }

  function bindUa(ua) {
    ua.on("connected", () => setStatus("Registering...", "warn"));
    ua.on("registered", () => {
      state.registered = true;
      setStatus("Ready", "ok");
      updateCallButton();
      log("Registered");
    });
    ua.on("unregistered", () => {
      state.registered = false;
      setStatus("Offline", "warn");
      updateCallButton();
    });
    ua.on("disconnected", () => {
      state.registered = false;
      setStatus("Disconnected", "bad");
      updateCallButton();
    });
    ua.on("registrationFailed", (event) => {
      state.registered = false;
      setStatus((event && event.cause) || "Registration failed", "bad");
      updateCallButton();
    });
    ua.on("newRTCSession", handleSession);
  }

  function handleSession(data) {
    const session = data.session;
    if (state.session && state.session !== session) {
      session.terminate({status_code: 486, reason_phrase: "Busy Here"});
      return;
    }
    state.session = session;
    bindSession(session);
    if (data.originator === "remote") {
      if (state.dnd) {
        session.terminate({status_code: 486, reason_phrase: "Do Not Disturb"});
        return;
      }
      state.incoming = session;
      const caller = session.remote_identity?.uri?.user || "caller";
      setStatus(`Incoming ${caller}`, "warn");
      log(`Incoming ${caller}`);
      setOpen(true);
    } else {
      setStatus("Calling...", "warn");
    }
    updateCallButton();
  }

  function bindSession(session) {
    session.on("peerconnection", (data) => bindPeerConnection(data.peerconnection || session.connection));
    session.on("progress", () => setStatus("Ringing...", "warn"));
    session.on("accepted", () => setStatus("Connected", "ok"));
    session.on("confirmed", () => {
      state.incoming = null;
      attachLocalPreview(session);
      setStatus("In call", "ok");
      updateCallButton();
    });
    session.on("ended", () => resetCall("Call ended"));
    session.on("failed", (event) => resetCall((event && event.cause) || "Call failed"));
    session.on("hold", () => {
      state.held = true;
      toggleButton(els.hold, true);
      setStatus("On hold", "warn");
    });
    session.on("unhold", () => {
      state.held = false;
      toggleButton(els.hold, false);
      setStatus("In call", "ok");
    });
  }

  function bindPeerConnection(pc) {
    if (!pc || pc.__omniWebphoneBound) return;
    pc.__omniWebphoneBound = true;
    pc.addEventListener("connectionstatechange", () => handlePeerConnectionState(pc));
    pc.addEventListener("iceconnectionstatechange", () => handlePeerConnectionState(pc));
    pc.addEventListener("track", (event) => {
      if (!state.remoteStream) state.remoteStream = new MediaStream();
      const incoming = event.streams && event.streams[0];
      const tracks = incoming ? incoming.getTracks() : [event.track];
      tracks.forEach((track) => {
        if (!state.remoteStream.getTracks().some((existing) => existing.id === track.id)) {
          state.remoteStream.addTrack(track);
        }
        track.addEventListener("ended", () => {
          if (state.session && state.remoteStream && state.remoteStream.getTracks().every((item) => item.readyState === "ended")) {
            resetCall("Call ended");
          }
        }, {once: true});
      });
      els.audio.srcObject = state.remoteStream;
      els.remoteVideo.srcObject = state.remoteStream;
      if (state.remoteStream.getVideoTracks().length) els.videoBox.hidden = false;
    });
  }

  function handlePeerConnectionState(pc) {
    if (!state.session || !pc) return;
    const connectionState = pc.connectionState || "";
    const iceState = pc.iceConnectionState || "";
    if (["closed", "failed"].includes(connectionState) || ["closed", "failed"].includes(iceState)) {
      resetCall("Call ended");
      return;
    }
    if (connectionState === "disconnected" || iceState === "disconnected") {
      clearTimeout(state.disconnectTimer);
      state.disconnectTimer = setTimeout(() => {
        if (state.session && (pc.connectionState === "disconnected" || pc.iceConnectionState === "disconnected")) {
          resetCall("Call ended");
        }
      }, 1500);
      return;
    }
    if (state.disconnectTimer) {
      clearTimeout(state.disconnectTimer);
      state.disconnectTimer = null;
    }
  }

  function attachLocalPreview(session) {
    const pc = session.connection;
    if (!pc) return;
    const stream = new MediaStream();
    pc.getSenders().forEach((sender) => {
      if (sender.track) stream.addTrack(sender.track);
    });
    state.localStream = stream;
    els.localVideo.srcObject = stream;
    if (stream.getVideoTracks().length) els.videoBox.hidden = false;
  }

  async function call(withVideo) {
    if (state.incoming) {
      await answer(withVideo);
      return;
    }
    if (!state.ua || !state.registered) {
      setStatus("Phone not ready", "bad");
      return;
    }
    const destination = targetUri(els.number.value);
    if (!destination) {
      setStatus("Enter a number", "bad");
      return;
    }
    const stream = await requestMedia(withVideo);
    if (!stream) return;
    state.ua.call(destination, mediaOptions(withVideo, stream));
    log(`Calling ${normalizeNumber(els.number.value)}`);
  }

  async function answer(withVideo) {
    if (!state.incoming) return;
    const stream = await requestMedia(withVideo);
    if (!stream) return;
    state.incoming.answer(mediaOptions(withVideo, stream));
    state.incoming = null;
    setStatus("Answering...", "warn");
    updateCallButton();
  }

  async function requestMedia(withVideo) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("Microphone not available", "bad");
      log("Microphone not available");
      return null;
    }
    try {
      return await navigator.mediaDevices.getUserMedia({audio: true, video: Boolean(withVideo)});
    } catch (error) {
      const denied = error && ["NotAllowedError", "SecurityError", "PermissionDeniedError"].includes(error.name);
      const message = denied ? "Allow microphone" : "Microphone failed";
      setStatus(message, "bad");
      log(message);
      return null;
    }
  }

  function mediaOptions(withVideo, stream) {
    const options = {
      mediaConstraints: {audio: true, video: Boolean(withVideo)},
      pcConfig: {iceServers: [{urls: "stun:stun.l.google.com:19302"}]},
      rtcOfferConstraints: {offerToReceiveAudio: true, offerToReceiveVideo: Boolean(withVideo)},
    };
    if (stream) options.mediaStream = stream;
    return options;
  }

  function hangup() {
    if (state.session) {
      try { state.session.terminate(); } catch (error) { console.warn(error); }
    }
    resetCall("Idle");
  }

  function resetCall(message) {
    if (state.disconnectTimer) {
      clearTimeout(state.disconnectTimer);
      state.disconnectTimer = null;
    }
    state.session = null;
    state.incoming = null;
    if (state.localStream) state.localStream.getTracks().forEach((track) => track.stop());
    state.remoteStream = null;
    state.localStream = null;
    state.held = false;
    state.muted = false;
    els.audio.srcObject = null;
    els.remoteVideo.srcObject = null;
    els.localVideo.srcObject = null;
    els.videoBox.hidden = true;
    toggleButton(els.hold, false);
    toggleButton(els.mute, false);
    setStatus(state.registered ? "Ready" : message, state.registered ? "ok" : "idle");
    updateCallButton();
    if (message && message !== "Idle") log(message);
  }

  function updateCallButton() {
    if (!els.call) return;
    els.call.dataset.state = state.incoming ? "incoming" : state.session ? "busy" : state.registered ? "ready" : "idle";
    els.call.textContent = state.incoming ? "Answer" : state.session ? "In Call" : "Call";
  }

  function toggleMute() {
    if (!state.session) return;
    state.muted = !state.muted;
    state.muted ? state.session.mute({audio: true}) : state.session.unmute({audio: true});
    toggleButton(els.mute, state.muted);
  }

  function toggleSpeaker() {
    state.speakerMuted = !state.speakerMuted;
    els.audio.muted = state.speakerMuted;
    els.remoteVideo.muted = state.speakerMuted;
    toggleButton(els.speaker, state.speakerMuted);
  }

  function toggleHold() {
    if (!state.session) return;
    state.held ? state.session.unhold() : state.session.hold();
  }

  function transfer() {
    if (!state.session) return;
    const number = prompt("Transfer to extension or number:");
    if (!number) return;
    state.session.refer(targetUri(number));
    log(`Transfer to ${number}`);
  }

  async function toggleDnd() {
    state.dnd = !state.dnd;
    toggleButton(els.dnd, state.dnd);
    if (state.config?.extension) {
      await fetch(`/api/softphone/dnd/${encodeURIComponent(state.config.extension)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enabled: state.dnd}),
      });
    }
    setStatus(state.dnd ? "DND on" : (state.registered ? "Ready" : "DND off"), state.dnd ? "warn" : "ok");
  }

  function bindUi() {
    els.trigger?.addEventListener("click", () => setOpen(!dock.classList.contains("open")));
    els.close?.addEventListener("click", () => {
      if (detached) window.close();
      else setOpen(false);
    });
    els.detach?.addEventListener("click", () => {
      window.open("/webphone/detached", "omnipbx-webphone", "width=360,height=720,resizable=yes,scrollbars=no");
      setOpen(false);
    });
    els.attach?.addEventListener("click", () => {
      if (detached) window.close();
      else setOpen(true);
    });
    els.extension?.addEventListener("change", () => loadBootstrap(els.extension.value));
    els.keypad?.addEventListener("click", (event) => {
      const key = event.target.closest("button")?.dataset.key;
      if (!key) return;
      els.number.value += key;
      els.number.focus();
    });
    els.number?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") call(false);
      if (event.key === "Escape") hangup();
    });
    els.copy?.addEventListener("click", async () => {
      const number = normalizeNumber(els.number.value);
      if (!number) return;
      await navigator.clipboard.writeText(number);
      setStatus("Number copied", "ok");
    });
    els.call?.addEventListener("click", () => call(false));
    els.video?.addEventListener("click", () => call(true));
    els.hangup?.addEventListener("click", hangup);
    els.mute?.addEventListener("click", toggleMute);
    els.speaker?.addEventListener("click", toggleSpeaker);
    els.hold?.addEventListener("click", toggleHold);
    els.transfer?.addEventListener("click", transfer);
    els.dnd?.addEventListener("click", toggleDnd);
    els.volume?.addEventListener("input", () => {
      const value = Number(els.volume.value || 1);
      els.audio.volume = value;
      els.remoteVideo.volume = value;
    });
    document.addEventListener("click", (event) => {
      const link = event.target.closest && event.target.closest("a[href^='tel:'], [data-phone-number]");
      if (!link) return;
      const number = link.dataset.phoneNumber || link.getAttribute("href").replace(/^tel:/i, "");
      els.number.value = normalizeNumber(number);
      setOpen(true);
      event.preventDefault();
    });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }

  bindUi();
  setOpen(detached);
  loadBootstrap().catch((error) => {
    console.error(error);
    setStatus(error.message || "Webphone unavailable", "bad");
  });
})();
