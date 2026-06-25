# Laravel CRM + OmniPBX Integration Plan

এই ডকুমেন্টের উদ্দেশ্য: Laravel CRM থেকে agent/user manage করা, agent যেন Laravel থেকেই call করতে পারে, incoming call Laravel CRM-এ দেখায়, এবং ৮-১০ জন agent-এর call log/report CRM-এ sync থাকে।

## Target Flow

1. OmniPBX-এ প্রতিটি agent-এর জন্য একটি extension থাকবে।
2. Laravel CRM-এর প্রতিটি user-এর সাথে একটি OmniPBX extension map থাকবে।
3. Agent Laravel CRM-এ login করলে তার extension অনুযায়ী browser webphone বা click-to-call চালু হবে।
4. Incoming call আসলে OmniPBX realtime webhook Laravel-এ পাঠাবে।
5. Laravel CRM incoming popup/customer screen খুলবে এবং call status update করবে।
6. Call শেষ হলে final call log Laravel CRM-এ save/update হবে।

## Recommended Agent Numbering

৮-১০ জন agent-এর জন্য সহজ numbering:

| Agent | Extension |
| --- | --- |
| Agent 1 | 1001 |
| Agent 2 | 1002 |
| Agent 3 | 1003 |
| Agent 4 | 1004 |
| Agent 5 | 1005 |
| Agent 6 | 1006 |
| Agent 7 | 1007 |
| Agent 8 | 1008 |
| Agent 9 | 1009 |
| Agent 10 | 1010 |

Admin extension `10000` permanent আছে। এটা normal CRM agent হিসেবে ব্যবহার না করাই ভালো।

## OmniPBX Side: যা করতে হবে

### 1. Extensions তৈরি

OmniPBX admin panel থেকে `Extensions/Users` পেজে গিয়ে প্রতিটি agent-এর extension তৈরি করতে হবে।

Recommended values:

| Field | Value |
| --- | --- |
| Extension | `1001`, `1002`, ... |
| Display Name | Agent name |
| Phone Type / Transport | `Webphone` হলে `transport-wss` |
| Call Recording | Enabled |
| Simultaneous Device Limit | `1` অথবা প্রয়োজন হলে `2` |
| Enabled | Yes |

Existing internal API:

```http
GET /api/extensions
POST /api/extensions
DELETE /api/extensions/{extension}
```

Note: এই endpoint এখন app session auth-এর জন্য তৈরি। Laravel থেকে direct extension create করতে চাইলে API key secured admin endpoint add করা উচিত।

### 2. Webphone settings configure

OmniPBX admin panel থেকে Softphone/Webphone settings configure করতে হবে।

Required:

| Setting | Example |
| --- | --- |
| Enabled | Yes |
| WebSocket URL | `wss://pbx.example.com/ws` |
| SIP Domain | `pbx.example.com` |
| Public Host | `https://pbx.example.com` |

OmniPBX current bootstrap API:

```http
GET /api/softphone/bootstrap/current
GET /api/softphone/bootstrap/current?extension=1001
GET /api/softphone/bootstrap?extension=1001
POST /api/softphone/dnd/{extension}
```

এই API currently logged-in OmniPBX web session ধরে কাজ করে। Laravel CRM-এর ভেতরে native webphone চালাতে চাইলে নিচের যেকোনো একটি পদ্ধতি নিতে হবে:

1. Laravel CRM থেকে OmniPBX webphone page open/iframe/popup করা।
2. OmniPBX থেকে API-key/JWT protected bootstrap endpoint add করা, যাতে Laravel authenticated user-এর extension bootstrap fetch করতে পারে।
3. Laravel-এ SIP.js/JSSIP দিয়ে নিজস্ব webphone বানিয়ে OmniPBX extension credential ব্যবহার করা।

Recommended production path: option 2 অথবা option 3।

### 3. API Push enable করা

OmniPBX admin panel থেকে API Push settings configure করতে হবে।

Laravel endpoint examples:

| OmniPBX setting | Laravel URL |
| --- | --- |
| Call Logs URL | `https://crm.example.com/api/omnipbx/call-logs` |
| Callbacks URL | `https://crm.example.com/api/omnipbx/callbacks` |
| Realtime Events URL | `https://crm.example.com/api/omnipbx/call-events` |
| API Key | strong shared secret |
| Enabled | Yes |

OmniPBX realtime call event পাঠায় এই event type দিয়ে:

| Event | Meaning |
| --- | --- |
| `call.ringing` | inbound ringing |
| `call.dialing` | outbound dialing |
| `call.answered` | call answered |
| `call.dial_ended` | dial attempt ended |
| `call.hangup` | call ended |

Realtime event payload example:

```json
{
  "source": "omnipbx",
  "hostname": "pbx-host",
  "event": "call.ringing",
  "event_id": "call.ringing|1740000000.12",
  "ami_event": "DialBegin",
  "direction": "inbound",
  "caller": "017XXXXXXXX",
  "callee": "1001",
  "agent_extension": "1001",
  "trunk": "mytrunk",
  "uniqueid": "1740000000.12",
  "linkedid": "1740000000.12",
  "channel": "PJSIP/mytrunk-00000001",
  "dest_channel": "PJSIP/1001-00000002",
  "status": "ringing",
  "dial_status": "",
  "hangup_cause": "",
  "hangup_cause_text": "",
  "timestamp": "2026-06-25T07:00:00+00:00"
}
```

Final/batch call log payload:

```json
{
  "source": "omnipbx",
  "hostname": "pbx-host",
  "entity": "call_logs",
  "generated_at": "2026-06-25 13:00:00",
  "count": 1,
  "records": [
    {
      "linkedid": "1740000000.12",
      "uniqueid": "1740000000.12",
      "direction": "inbound",
      "caller": "017XXXXXXXX",
      "callee": "1001",
      "agent_extension": "1001",
      "disposition": "ANSWERED",
      "duration": 65,
      "billsec": 52
    }
  ]
}
```

### 4. CRM Pull API

Laravel চাইলে push ছাড়াও OmniPBX থেকে call data pull করতে পারে।

Header:

```http
X-API-Key: YOUR_OMNIPBX_API_KEY
```

Available endpoints:

```http
GET /crm-api/health
GET /crm-api/call-data?limit=1000&offset=0&direction=all
GET /crm-api/call-data?linkedid=1740000000.12
GET /crm-api/call-logs?range=7d&direction=all&category=all&limit=250
GET /crm-api/callbacks?open_only=true&limit=500
POST /crm-api/callbacks/{linkedid}
```

Callback update body:

```json
{
  "completed": true,
  "callback_number": "017XXXXXXXX",
  "note": "Customer called back from CRM"
}
```

## Laravel Side: যা করতে হবে

### 1. Database tables

#### users table update

Add fields:

```php
$table->string('pbx_extension', 32)->nullable()->unique();
$table->string('pbx_display_name')->nullable();
$table->boolean('pbx_enabled')->default(false);
```

#### pbx_call_events table

```php
Schema::create('pbx_call_events', function (Blueprint $table) {
    $table->id();
    $table->string('event_id')->unique();
    $table->string('event')->index();
    $table->string('direction')->nullable()->index();
    $table->string('caller')->nullable()->index();
    $table->string('callee')->nullable()->index();
    $table->string('agent_extension', 32)->nullable()->index();
    $table->string('uniqueid')->nullable()->index();
    $table->string('linkedid')->nullable()->index();
    $table->json('payload');
    $table->timestamp('event_at')->nullable();
    $table->timestamps();
});
```

#### pbx_call_logs table

```php
Schema::create('pbx_call_logs', function (Blueprint $table) {
    $table->id();
    $table->string('linkedid')->nullable()->index();
    $table->string('uniqueid')->nullable()->index();
    $table->string('direction')->nullable()->index();
    $table->string('caller')->nullable()->index();
    $table->string('callee')->nullable()->index();
    $table->string('agent_extension', 32)->nullable()->index();
    $table->string('disposition')->nullable()->index();
    $table->integer('duration')->default(0);
    $table->integer('billsec')->default(0);
    $table->json('payload')->nullable();
    $table->timestamp('call_at')->nullable();
    $table->timestamps();

    $table->unique(['linkedid', 'uniqueid']);
});
```

### 2. Environment config

Laravel `.env`:

```env
OMNIPBX_BASE_URL=https://pbx.example.com
OMNIPBX_API_KEY=change-this-strong-secret
OMNIPBX_WEBHOOK_KEY=change-this-strong-secret
```

`config/services.php`:

```php
'omnipbx' => [
    'base_url' => env('OMNIPBX_BASE_URL'),
    'api_key' => env('OMNIPBX_API_KEY'),
    'webhook_key' => env('OMNIPBX_WEBHOOK_KEY'),
],
```

### 3. Webhook routes

`routes/api.php`:

```php
Route::post('/omnipbx/call-events', [OmniPbxWebhookController::class, 'callEvents']);
Route::post('/omnipbx/call-logs', [OmniPbxWebhookController::class, 'callLogs']);
Route::post('/omnipbx/callbacks', [OmniPbxWebhookController::class, 'callbacks']);
```

Controller security check:

```php
private function verifyOmniPbx(Request $request): void
{
    abort_unless(
        hash_equals(config('services.omnipbx.webhook_key'), (string) $request->header('X-API-Key')),
        401
    );
}
```

Realtime event handling:

```php
public function callEvents(Request $request)
{
    $this->verifyOmniPbx($request);

    $payload = $request->all();

    PbxCallEvent::updateOrCreate(
        ['event_id' => $payload['event_id']],
        [
            'event' => $payload['event'] ?? null,
            'direction' => $payload['direction'] ?? null,
            'caller' => $payload['caller'] ?? null,
            'callee' => $payload['callee'] ?? null,
            'agent_extension' => $payload['agent_extension'] ?? null,
            'uniqueid' => $payload['uniqueid'] ?? null,
            'linkedid' => $payload['linkedid'] ?? null,
            'payload' => $payload,
            'event_at' => now(),
        ]
    );

    broadcast(new PbxCallEventReceived($payload))->toOthers();

    return response()->json(['status' => 'ok']);
}
```

Call log handling:

```php
public function callLogs(Request $request)
{
    $this->verifyOmniPbx($request);

    foreach ($request->input('records', []) as $row) {
        PbxCallLog::updateOrCreate(
            [
                'linkedid' => $row['linkedid'] ?? null,
                'uniqueid' => $row['uniqueid'] ?? null,
            ],
            [
                'direction' => $row['direction'] ?? null,
                'caller' => $row['caller'] ?? null,
                'callee' => $row['callee'] ?? null,
                'agent_extension' => $row['agent_extension'] ?? $row['caller_extension'] ?? $row['callee_extension'] ?? null,
                'disposition' => $row['disposition'] ?? null,
                'duration' => (int) ($row['duration'] ?? 0),
                'billsec' => (int) ($row['billsec'] ?? 0),
                'payload' => $row,
                'call_at' => isset($row['calldate']) ? Carbon\Carbon::parse($row['calldate']) : now(),
            ]
        );
    }

    return response()->json(['status' => 'ok']);
}
```

### 4. Incoming call popup in Laravel

Laravel frontend should listen to broadcast events and match by logged-in user extension.

Pseudo logic:

```js
Echo.private(`pbx.agent.${currentUser.pbx_extension}`)
  .listen('PbxCallEventReceived', (event) => {
    const call = event.payload;

    if (call.agent_extension !== currentUser.pbx_extension) return;

    if (call.event === 'call.ringing') {
      showIncomingCallPopup({
        caller: call.caller,
        linkedid: call.linkedid,
        direction: call.direction,
      });
    }

    if (call.event === 'call.answered') {
      markCallAnswered(call.linkedid);
    }

    if (call.event === 'call.hangup') {
      closeCallPopup(call.linkedid);
    }
  });
```

Customer lookup:

1. Normalize caller number.
2. Search customers/leads by phone.
3. If found, open customer profile.
4. If not found, show quick lead/customer create form.
5. Store `linkedid` with note/task so final call log can attach later.

### 5. Calling from Laravel

There are two possible approaches.

#### Option A: Browser webphone inside Laravel

Laravel frontend uses SIP.js/JSSIP and registers the agent extension directly.

Needs from OmniPBX:

| Value | Source |
| --- | --- |
| extension | Laravel user `pbx_extension` |
| secret | OmniPBX extension secret |
| SIP domain | OmniPBX webphone setting |
| WSS URL | OmniPBX webphone setting |

Security note: Do not expose all extension credentials. Return only the logged-in user's own credential through a protected Laravel endpoint.

#### Option B: Server-side click-to-call

Laravel sends request to OmniPBX:

```http
POST /crm-api/calls/originate
X-API-Key: YOUR_OMNIPBX_API_KEY
Content-Type: application/json
```

Body:

```json
{
  "agent_extension": "1001",
  "number": "017XXXXXXXX"
}
```

Expected behavior:

1. OmniPBX calls `PJSIP/1001`.
2. Agent answers.
3. OmniPBX dials customer number through outbound trunk.
4. Laravel receives realtime `call.dialing`, `call.answered`, `call.hangup`.

Current status: this endpoint is not implemented yet. Existing OmniPBX AMI service has originate support internally, so this is a small OmniPBX API addition.

Recommended payload validation:

| Field | Rule |
| --- | --- |
| agent_extension | numeric, exists, enabled |
| number | allowed phone pattern |
| caller_id | optional |
| crm_user_id | optional |

### 6. Laravel admin screen

CRM admin should manage:

| Field | Purpose |
| --- | --- |
| User | CRM login user |
| PBX Extension | `1001` etc. |
| PBX Enabled | agent can use phone |
| Role | admin/supervisor/agent |
| Webphone Allowed | browser calling |
| Call Popup Enabled | incoming popup |

Do not let two CRM users share one extension unless intentional.

## Needed OmniPBX Development Changes

For fully Laravel-managed CRM, add these API-key protected endpoints:

### 1. Extension provisioning API

```http
POST /crm-api/extensions
GET /crm-api/extensions
PATCH /crm-api/extensions/{extension}
DELETE /crm-api/extensions/{extension}
```

Create body:

```json
{
  "extension": "1001",
  "display_name": "Agent One",
  "transport": "transport-wss",
  "call_recording_enabled": true,
  "simultaneous_device_limit": 1,
  "enabled": true
}
```

After create/update/delete, OmniPBX must run `sync_asterisk_config(connection)`.

### 2. Webphone bootstrap API for CRM

```http
GET /crm-api/softphone/bootstrap?extension=1001
```

Response should include only what the CRM user needs:

```json
{
  "status": "ok",
  "config": {
    "extension": "1001",
    "display_name": "Agent One",
    "secret": "extension-secret",
    "sip_domain": "pbx.example.com",
    "websocket_url": "wss://pbx.example.com/ws",
    "webrtc_ready": true
  }
}
```

Security: Laravel must request only for the logged-in user's mapped extension.

### 3. Click-to-call API

```http
POST /crm-api/calls/originate
```

Implementation should use AMI `Originate`.

High-level Asterisk flow:

```text
Channel: PJSIP/{agent_extension}
Context: omnipbx-internal
Exten: {customer_number}
Priority: 1
Async: true
```

Alternatively use a dedicated CRM originate context to apply trunk rules safely.

### 4. Optional call note/tag API

Laravel can attach CRM metadata:

```http
POST /crm-api/calls/{linkedid}/metadata
```

Body:

```json
{
  "crm_user_id": 12,
  "customer_id": 501,
  "lead_id": 99,
  "note": "Customer interested"
}
```

## Security Checklist

- Use HTTPS for both CRM and PBX.
- Use a strong shared `X-API-Key`.
- Restrict OmniPBX CRM API by IP allowlist if possible.
- Never expose all extension secrets to browser.
- Laravel should only fetch/use the logged-in user's own extension.
- Validate outbound dial number before click-to-call.
- Log webhook failures and return HTTP `200` only after save succeeds.
- Use queue jobs for heavy processing so webhook response stays fast.

## Test Checklist

### OmniPBX

1. Create extensions `1001` and `1002`.
2. Set both to Webphone.
3. Enable API Push and set Laravel webhook URLs.
4. Open OmniPBX webphone and confirm extension registers.
5. Make internal call `1001 -> 1002`.
6. Confirm realtime event appears in Laravel.
7. Confirm final call log appears in Laravel.

### Laravel

1. Map CRM user A to extension `1001`.
2. Map CRM user B to extension `1002`.
3. Login as user A and open phone panel.
4. Receive incoming call and show popup only for user A.
5. Answer/hangup and update popup state.
6. Save final call log against customer/lead.
7. Test missed call and callback list.

## Current Ready vs Pending

Ready in OmniPBX:

- Extension management in OmniPBX UI.
- Webphone bootstrap for OmniPBX logged-in users.
- Realtime call event webhook via API Push.
- Batch call log push.
- CRM pull endpoints for call data/logs/callbacks.
- AMI originate helper exists internally.

Pending for full Laravel-managed experience:

- API-key protected extension provisioning.
- API-key/JWT protected webphone bootstrap for Laravel users.
- Public CRM click-to-call endpoint.
- Optional CRM metadata attachment endpoint.

## Recommended Implementation Order

1. First configure extensions and API Push in OmniPBX.
2. Build Laravel webhook receiver and incoming popup.
3. Sync final call logs into Laravel.
4. Add Laravel user-to-extension mapping.
5. Add webphone in Laravel or open OmniPBX detached webphone.
6. Add OmniPBX `crm-api` extension provisioning endpoint.
7. Add OmniPBX `crm-api` click-to-call endpoint.
