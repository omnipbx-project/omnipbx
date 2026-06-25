# MicroSIP Style Web Softphone

Chrome extension softphone UI inspired by MicroSIP.

## Current behavior

- Clicking the browser extension icon opens one standalone full softphone window.
- The softphone window is reused instead of opening again for every tab.
- The softphone window stays open while you switch tabs or navigate pages.
- There is no floating phone icon on webpages.
- 10 to 12 digit numbers found in normal page text are underlined and become clickable.
- One click on a detected number copies it, opens/focuses the softphone window, and loads the number into the dial box.
- `tel:` links are also intercepted and loaded into the softphone.
- Right-click selected text -> Copy and dial selected number.

## Google Sheets note

Google Sheets often renders cells in a canvas-like grid instead of normal page text. When a cell number is not exposed as real DOM text, Chrome extensions cannot turn that cell itself into a clickable span. In that case, copy the cell number or use the formula/input bar text; the extension will still load copied/selected 10 to 12 digit numbers into the softphone.

## Important: JsSIP file required

This package still contains a placeholder `jssip.min.js`. Replace it with the official JsSIP browser build before real SIP/WSS/WebRTC calling.

Typical SIP/WebRTC requirements:

- WSS URL, for example `wss://pbx.example.com:8089/ws`
- SIP domain / PBX host
- SIP extension / username
- SIP password
- PBX WebRTC support enabled
- Valid TLS certificate for WSS


## Version 2.0.6

- Replaced the demo placeholder `jssip.min.js` with a real bundled JsSIP browser build.
- Registration no longer shows the placeholder warning when the extension is loaded fresh.
- You still need a PBX/SIP server that supports SIP over secure WebSocket (`wss://`) for WebRTC calling.
