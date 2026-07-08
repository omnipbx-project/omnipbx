# MicroSIP Style Web Softphone

Chrome extension softphone UI inspired by MicroSIP.

## Current behavior

- Clicking the browser extension icon opens one standalone full softphone window.
- The softphone window is reused instead of opening again for every tab.
- The softphone window stays open while you switch tabs or navigate pages.
- After successful registration, closing the softphone window keeps the webphone registered by reopening a minimized keepalive window.
- Use `Unregister` or `DND` before closing when you want to stop receiving incoming call popups.
- There is no floating phone icon on webpages.
- Numbers starting with local `01`, `02`, `09`, Bangladesh `880`, or international `+<country code>` / `00<country code>` are underlined and become clickable.
- One click on a detected number normalizes it, copies it, opens/focuses the softphone window, and loads the number into the dial box.
- `tel:` links and ordinary hyperlinks whose text or URL contains a matching phone number are intercepted and loaded into the softphone.
- Right-click selected text -> Copy and dial selected number.

## Development install and updates

You do not need to delete and add the extension after every code change.

For local development:

1. Open `chrome://extensions` or `edge://extensions`.
2. Turn on Developer mode.
3. Click `Load unpacked` once and choose this folder: `third_party/web-softphone-demo`.
4. After editing files, go back to the extensions page and click `Reload` on `OmniPBX Webphone`.

Keeping the same unpacked folder keeps the same local extension install, so Chrome keeps `chrome.storage.local` settings such as SIP credentials and webphone options.

For a real upgradeable install package:

1. In `chrome://extensions`, use `Pack extension` for `third_party/web-softphone-demo`.
2. Save the generated `.pem` private key somewhere safe.
3. For every future release, increase `version` in `manifest.json`.
4. Pack the extension again with the same `.pem` key.

Using the same `.pem` key gives the CRX the same extension ID, so installing the newer CRX upgrades the old one instead of creating a separate extension. If the `.pem` key is lost, Chrome treats the package as a different extension.

For automatic updates across machines, publish through the Chrome Web Store/Microsoft Edge Add-ons, or host a CRX with an extension update manifest and add an `update_url`. Local development usually only needs the `Reload` button.

## Google Sheets note

Google Sheets often renders cells in a canvas-like grid instead of normal page text. When a cell number is not exposed as real DOM text, Chrome extensions cannot turn that cell itself into a clickable span. The extension also checks exposed selection, link text, accessible cell labels on double-click, and copied cell text after `Ctrl+C`; if Google Sheets does not expose the cell value, use the formula/input bar text.

## Important: JsSIP file required

This package still contains a placeholder `jssip.min.js`. Replace it with the official JsSIP browser build before real SIP/WSS/WebRTC calling.

Typical SIP/WebRTC requirements:

- WSS URL, for example `wss://pbx.example.com:8089/ws`
- SIP domain / PBX host
- SIP extension / username
- SIP password
- PBX WebRTC support enabled
- Valid TLS certificate for WSS


## Version 2.1.13

- The dial box now clears automatically after a call ends, fails, or is hung up.

## Version 2.1.12

- Failed and ended calls now log SIP status code, reason phrase, and originator when JsSIP provides them.

## Version 2.1.11

- Removed the extra media preflight and capture permissions so JsSIP can create inbound/outbound sessions directly.

## Version 2.1.10

- Incoming calls now play a local ringtone in the softphone window.
- The dial number is locked during active/incoming calls while keypad digits still send DTMF.

## Version 2.1.9

- Registration now retries automatically when keep-registered mode is enabled and the WebSocket/registration drops.
- Calls now use the PBX-provided STUN/TURN ICE servers from provisioning when available.
- Pressing Call while unregistered now registers first and then places the pending call.

## Version 2.1.8

- Softphone window size is now remembered and reused when the extension opens the phone again.
- The keypad, text, status bar, and video areas now shrink cleanly in narrow/small windows.

## Version 2.1.7

- International `+` numbers now dial without the plus sign; for example `+44 20 7123 4567` becomes `442071234567`.

## Version 2.1.6

- Dialed numbers are now normalized before copy/dial; for example `017-1111-1111` becomes `01711111111`, and `+8801711111111` becomes `01711111111`.
- Duplicate calls to the same normalized number are ignored for a short window to prevent accidental double dialing.
- Google Sheets fallback now checks active/selected cells, formula bar text, accessible labels, selected text, copied text, double-click, and Enter.

## Version 2.1.5

- International numbers with any `+<country code>` or `00<country code>` prefix are now supported, while local BD `01`, `02`, `09`, and bare `880` rules remain.
- Hyphenated numbers such as `017-1111-1111` are supported.

## Version 2.1.4

- Click-to-call detection now only accepts numbers beginning with `01`, `02`, `09`, `880`, or `+880`.
- Ordinary hyperlinks with matching phone numbers in the text, title, aria label, dataset, or URL are now handled.
- Google Sheets fallback now checks exposed selected text, accessible labels on double-click, and copied cell text after `Ctrl+C`.

## Version 2.1.3

- Provisioning and click-to-call now handle stale page content scripts after extension reloads without throwing `sendMessage` errors.

## Version 2.1.2

- Closing a registered softphone window now keeps registration alive by reopening a minimized keepalive window.
- Incoming calls now raise a browser notification and restore/focus the softphone window.

## Version 2.1.1

- Active calls now turn the main call button into a hangup action instead of a passive status label.
- Keypad digits, `*`, and `#` send DTMF tones during an active SIP call.
- Click-to-call scanning now resets regex state between DOM scans, improving reliability on dynamic pages.
- Numbers sent to an already-open softphone window are normalized through one shared helper and focused in the dial box.

## Version 2.0.6

- Replaced the demo placeholder `jssip.min.js` with a real bundled JsSIP browser build.
- Registration no longer shows the placeholder warning when the extension is loaded fresh.
- You still need a PBX/SIP server that supports SIP over secure WebSocket (`wss://`) for WebRTC calling.
