# Connecting to the IKEA TRADFRI Gateway via DTLS on macOS — Nine Pitfalls, One Hard-Won Chronicle

This document records every pitfall encountered while establishing a DTLS + CoAP connection to a TRADFRI E1526 gateway on macOS using Python, along with the root cause and fix for each one. If nine pitfalls sounds like a lot, I assure you — each one made me believe the previous one was the last.

**Final goal achieved**: list all devices (lights, sockets, remotes), groups, and scenes under the gateway without relying on the pytradfri model layer. Sounds simple, right? Ha.

**Libraries used**: [DTLSSocket 0.2.3](https://github.com/mclunis/DTLSSocket) (Cython wrapper around TinyDTLS) + [aiocoap](https://github.com/chrysn/aiocoap)

Target audience: developers who want to write a custom TRADFRI client on macOS but find that sample code silently fails or times out indefinitely. Welcome to the club.

---

## Environment

| Component | Version / Notes |
|-----------|----------------|
| OS | macOS 15 (Apple Silicon) |
| Python | 3.9 (system, `/usr/bin/python3`) |
| DTLSSocket | 0.2.3 (built from source) |
| TinyDTLS | bundled with DTLSSocket |
| pytradfri | latest pip version |
| aiocoap | latest pip version |
| Gateway model | IKEA TRADFRI E1526 |
| Gateway firmware | 1.21.x |

---

## #1 — OpenSSL 3 does not support `TLS_PSK_WITH_AES_128_CCM_8` (punched in the face at the opening)

### Symptom
Using **libcoap** (e.g. `coap-client` or aiocoap's libcoap backend):

```
DTLS_ALERT_HANDSHAKE_FAILURE
```

The handshake fails immediately at cipher negotiation. Rejected before the handshake even begins.

### Root cause
The TRADFRI gateway supports only two DTLS cipher suites:
- `TLS_PSK_WITH_AES_128_CCM_8` (0xC0A8)
- `TLS_ECDHE_ECDSA_WITH_AES_128_CCM_8` (0xC0AC)

Both use **AES-CCM**, which OpenSSL 3.x removed from its default cipher provider. Any DTLS stack built against OpenSSL 3 (Homebrew `libcoap`, aiocoap's libcoap backend, etc.) cannot complete the handshake.

### Fix
Switch to **TinyDTLS**. TinyDTLS is a self-contained C library with its own AES-CCM implementation that has no OpenSSL dependency. DTLSSocket wraps TinyDTLS as a Cython extension callable from Python.

---

## #2 — Build fails because Cython was never run (welcome to C extension hell)

### Symptom
```
clang: error: no such file or directory: 'DTLSSocket/dtls.c'
```

### Root cause
The DTLSSocket 0.2.3 repo only ships `dtls.pyx`, not the pre-generated `dtls.c`. Running `python setup.py develop` directly fails because the compiler has no `.c` file to work with. You have the recipe but no kitchen.

### Fix
Install Cython first, compile `.pyx` to `.c` manually, then build:

```bash
pip3 install --user cython
~/.local/bin/cython DTLSSocket/dtls.pyx   # generates dtls.c
python3 setup.py develop --user            # compiles dtls.c → .so
```

> Note: DTLSSocket 0.2.3 uses `# cython: language_level=2`; Cython 3 will warn but still builds fine.

---

## #3 — `APIFactory.generate_psk()` silently returns the security code unchanged (the gentlest backstab)

### Symptom
After calling pytradfri's `APIFactory.init(psk=SECURITY_CODE)` and then `generate_psk(SECURITY_CODE)`, the return value equals the security code itself. The `psk` field written to the PSK file is actually the security code, and all subsequent connections fail silently.

### Root cause
`APIFactory` internal logic:

```python
async def generate_psk(self, security_code):
    if not self._psk:       # ← this guard decides everything
        ...
    return self._psk        # ← if _psk is already set, return it directly without any network request
```

Calling `APIFactory.init(host=..., psk_id=..., psk=SECURITY_CODE)` sets `self._psk` to the security code. `if not self._psk` is False, so `generate_psk` returns the security code directly — no request to the gateway, no new PSK generated. Creative API design.

### Fix
When generating a new PSK, pass `None` for the `psk` parameter in `APIFactory.init`:

```python
factory = await APIFactory.init(host=GATEWAY_IP, psk_id=identity, psk=None)
psk = await factory.generate_psk(SECURITY_CODE)
```

---

## #4 — macOS AF_INET6 socket does not receive IPv4 UDP responses (a platform-specific trap)

### Symptom
Connecting to an IPv4 gateway via aiocoap (tinydtls transport):

```
aiocoap.error.ConRetransmitsExceeded
```

The client keeps sending packets but receives no response — even though Wireshark/tcpdump confirms the gateway is replying. The packets are there. You are there. But you're in different worlds.

### Root cause
DTLSSocket (and aiocoap's tinydtls transport) internally creates an **AF_INET6** socket and passes addresses in IPv4-mapped IPv6 format (`::ffff:192.168.x.x`).

On **macOS**, the kernel does **not** automatically unwrap IPv4 UDP responses and deliver them to an AF_INET6 socket (Linux does this). The gateway replies with a plain IPv4 UDP packet, macOS finds no matching socket, and silently drops it.

tcpdump can see the gateway's response; the AF_INET6 socket never does. The despair of watching packets arrive and having the program claim nothing came — you have to live it to understand it.

### Fix
Create an **AF_INET** socket manually as the underlying transport. In `write_cb`, strip the `::ffff:` prefix before calling `sendto`:

```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(5)
sock.bind(('0.0.0.0', 0))

def write_cb(addr, data):
    host = addr[0].split('%')[0]
    if host.startswith('::ffff:'):
        host = host[7:]          # IPv4-mapped → plain IPv4
    return sock.sendto(bytes(data), (host, addr[1]))
```

When feeding raw bytes from `sock.recvfrom` back to TinyDTLS, re-add the `::ffff:` prefix:

```python
data, addr = sock.recvfrom(4096)
d.handleMessageAddr('::ffff:' + addr[0], addr[1], data)
```

---

## #5 — `Connection` object is immediately GC'd, sending `close_notify` (the most absurd one)

### Symptom
After `d.connect(...)` returns, TinyDTLS **immediately** sends a DTLS Alert `close_notify` (level=1 warning, desc=0), closing the connection before any server response arrives. Like hanging up the phone right after dialling.

Packet trace:
```
SEND Handshake 77B   ← ClientHello
EVENT code=0x01DC    ← DTLS_EVENT_CONNECT fires
SEND Alert level=1 desc=0   ← close_notify! (should not happen)
RECV 60B             ← ServerHello arrives too late
```

### Root cause
`d.connect()` returns a `Connection` object. If the return value is not assigned to a variable, Python immediately GCs it. `Connection.__dealloc__` calls `dtls_reset_peer()`, which calls `dtls_destroy_peer(ctx, peer, DTLS_DESTROY_CLOSE)`, sending `close_notify`.

The `close_notify` races ahead of the DTLS handshake and terminates the session. A network connection killed by the garbage collector — probably the most absurd bug of my career.

Relevant Cython code (`dtls.pyx`):
```python
cdef class Connection(Session):
    def __dealloc__(self):
        peer = tdtls.dtls_get_peer(self.d.ctx, &self.session)
        if peer:
            tdtls.dtls_reset_peer(self.d.ctx, peer)   # ← sends close_notify
```

### Fix
**Always** assign the return value of `d.connect()` to a variable to keep `Connection` alive:

```python
conn = d.connect('::ffff:192.168.x.x', 5684, 0, 0)   # ← must be assigned
```

---

## #6 — TinyDTLS misidentifies ServerHello as a duplicate and drops it (record seq=0 collision)

### Symptom
After receiving `HelloVerifyRequest` and sending the second `ClientHello` with a cookie, the handshake stalls. `handle_handshake_msg` is never called for `ServerHello`. Eventually when a retransmitted `ServerHello` arrives, the wrong state triggers handshake_failure.

Debug trace:
```
RECV 60B  hs=3  ← HelloVerifyRequest   (record seq=0, mseq=0)
SEND 109B hs=1  ← ClientHello+cookie
RECV 101B hs=2  ← ServerHello          (record seq=0, mseq=1)
  → silently dropped! (dedup logic considers seq=0 already seen)
RECV 25B  hs=14 ← ServerHelloDone      (mseq=2, buffered in reorder queue)
RECV 101B hs=2  ← ServerHello retransmit (record seq=2, mseq=1)
  → processed this time, but state machine is now confused
SEND Alert level=2 desc=40  ← handshake_failure
```

### Root cause
TinyDTLS uses a **per-security-context sequence number bitfield** (`security->cseq`) to detect duplicate packets. Both `HelloVerifyRequest` (first server flight) and `ServerHello` (second server flight) **use record sequence number 0**, because the gateway resets its record sequence counter between flights.

`ServerHello` (seq=0) arrives after `HelloVerifyRequest` (seq=0) was already processed:
```c
int64_t seqn_diff = pkt_seq_nr - security->cseq.cseq;  // = 0 - 0 = 0
if (seqn_diff == 0) {
    return 0;  // drop: "duplicate packet"
}
```

`ServerHello` is silently dropped. The state machine stays at `DTLS_STATE_CLIENTHELLO`. `ServerHelloDone` (mseq=2) is buffered waiting because `mseq_r` is still at 1. Like a queue where the person ahead disappears and everyone behind gets stuck.

### Fix (patch TinyDTLS source `dtls.c`)
After successfully processing `DTLS_HT_HELLO_VERIFY_REQUEST`, reset the sequence deduplication state so the server's next flight (starting from seq=0) is not falsely dropped:

```c
case DTLS_HT_HELLO_VERIFY_REQUEST:
    err = check_server_hello_verify_request(ctx, peer, data, data_length);
    if (err < 0) { ... }

    /* reset seq dedup: server's next flight restarts record seq from 0 */
    dtls_security_params(peer)->cseq.bitfield = 0;

    break;
```

---

## #7 — TinyDTLS requires `renegotiation_info` by default, but TRADFRI gateway doesn't send it (a standards dispute)

### Symptom
After fixing #5 and #6, `check_server_hello` still fails — ServerHello is processed and immediately followed by a fatal alert closing the session. Victory in sight, then tripped again.

With debug output:
```
DEBUG check_server_hello data_length=88
DEBUG dtls_check_tls_extension returned -552  ← fatal HANDSHAKE_FAILURE
```

`-552` decodes to `dtls_alert_fatal_create(DTLS_ALERT_HANDSHAKE_FAILURE)`
(`-(2 * 256 + 40) = -552`).

### Root cause
TinyDTLS `default_user_parameters` defaults:
```c
.force_extended_master_secret = 1,
.force_renegotiation_info     = 1,
```

`check_forced_extensions` inside `dtls_check_tls_extension` validates both. The TRADFRI gateway's `ServerHello` **does not include** the `renegotiation_info` extension (0xFF01). The gateway signals RFC 5746 compliance via `TLS_EMPTY_RENEGOTIATION_INFO_SCSV` in the ClientHello cipher list, without echoing the extension in ServerHello. Technically valid — TinyDTLS disagrees.

With `force_renegotiation_info = 1` and `config->renegotiation_info == 0`:
```c
if (config->user_parameters.force_renegotiation_info) {
    if (!config->renegotiation_info) {
        goto error;   // → DTLS_ALERT_HANDSHAKE_FAILURE
    }
}
```

### Fix (patch TinyDTLS source `dtls.c`)
Disable both forced checks in `default_user_parameters`:

```c
static const dtls_user_parameters_t default_user_parameters = {
    ...
    .force_extended_master_secret = 0,   // was 1
    .force_renegotiation_info     = 0,   // was 1
};
```

> The gateway does send the `extended_master_secret` extension (0x0017), so that check would have passed anyway. Both set to 0 is safe when connecting to a known, trusted local gateway.

---

## #8 — Latest pytradfri is incompatible with gateway firmware 1.21.x via pydantic (the straw that broke the camel's back)

### Symptom
After installing `pip install pytradfri`, any device enumeration throws:

```
pydantic.error_wrappers.ValidationError: N validation errors
  - field required (type=value_error.missing)  ← fields like 15025, 15015, 3.3, 3.9
```

Or (pydantic v2):

```
pydantic_core._pydantic_core.ValidationError: N validation errors for ...
  15025
    Field required [type=missing, ...]
```

### Root cause
Recent pytradfri versions parse raw gateway JSON through pydantic models designed for newer firmware. These models expect fields (e.g. `15025`, `15015`, `3.3`, `3.9`) that gateway firmware 1.21.x does **not** return.

pydantic's `Field required` means mandatory field missing; the entire model fails with no fallback. The library says "I need this field." The gateway says "I don't have it." End of story.

### Fix
**Abandon the pytradfri model layer entirely.** Use aiocoap to send CoAP GET directly and parse the JSON response by dict key. Sometimes the best abstraction layer is no abstraction layer:

```python
import aiocoap, json

ctx = await aiocoap.Context.create_client_context()
# ... load credentials (see #9)

async def get(ctx, path):
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(code=aiocoap.GET, uri=uri)
    res = await ctx.request(req).response
    return json.loads(res.payload)

device_ids = await get(ctx, "/15001")
for did in device_ids:
    d = await get(ctx, f"/15001/{did}")
    name = d.get("9001")   # KEY_NAME
    # ...
```

Gateway CoAP keys are plain integer strings (`"9001"`, `"5850"`, etc.) — read them directly from the dict, no model validation needed.

---

## #9 — aiocoap credential URI must not include a port number (the grand finale)

### Symptom
When configuring PSK credentials with `ctx.client_credentials.load_from_dict()`, CoAP requests throw:

```
aiocoap.error.CredentialsMissingError:
  No suitable credentials for coaps://192.168.x.x/15001
```

Correct PSK, correct address — fails every time. By pitfall nine you're immune to "everything looks right but it doesn't work."

### Root cause
The key in `load_from_dict` is a glob pattern matched against the request URI. Configuring:

```python
ctx.client_credentials.load_from_dict({
    "coaps://192.168.x.x:5684/*": { ... }   # ← includes :5684
})
```

But aiocoap internally constructs request URIs as `coaps://192.168.x.x/15001` — the default port 5684 is not written into the URI. The patterns don't match, credentials are not found.

### Fix
Do **not** include the port in the credential key URI:

```python
ctx.client_credentials.load_from_dict({
    f"coaps://{GATEWAY_IP}/*": {    # ← no port
        "dtls": {
            "psk":             psk.encode(),
            "client-identity": identity.encode(),
        }
    }
})
```

aiocoap's URI matching: a credential key pattern matches a request URI only when scheme, host, port (or scheme default port), and path all align. The default port for `coaps` is 5684, so `coaps://host/*` matches `coaps://host/path`, but `coaps://host:5684/*` does not. Yes, this is counterintuitive.

---

## Summary of all changes ("the map left for those who come after")

| # | File | Change |
|---|------|--------|
| 1 | `dtls.c` | Add `cseq.bitfield = 0` after `check_server_hello_verify_request` |
| 2 | `dtls.c` | Set `force_extended_master_secret` and `force_renegotiation_info` to 0 in `default_user_parameters` |
| 3 | call-site code | Assign `conn = d.connect(...)` to prevent GC from triggering `close_notify` |
| 4 | call-site code | Use AF_INET socket; strip `::ffff:` prefix in `write_cb` (macOS only) |

---

## Minimal working DTLS handshake example (the prize after nine pitfalls)

```python
import socket
from DTLSSocket import dtls
from DTLSSocket.dtls import Session

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(5)
sock.bind(('0.0.0.0', 0))

GATEWAY_IP    = "192.168.x.x"
GATEWAY_PORT  = 5684
SECURITY_CODE = b"<16-character Security Code>"

received_data = []

def write_cb(addr, data):
    host = addr[0].split('%')[0]
    if host.startswith('::ffff:'):
        host = host[7:]
    return sock.sendto(bytes(data), (host, addr[1]))

def read_cb(addr, data):
    received_data.append(bytes(data))
    return len(data)

def event_cb(level, code):
    if code == 0x01DE:
        print("DTLS handshake complete")

d = dtls.DTLS(
    read=read_cb, write=write_cb, event=event_cb,
    pskId=b"Client_identity",
    pskStore={b"Client_identity": SECURITY_CODE, b"": SECURITY_CODE},
)
conn = d.connect(f'::ffff:{GATEWAY_IP}', GATEWAY_PORT, 0, 0)  # must be assigned!

for _ in range(10):
    try:
        data, addr = sock.recvfrom(4096)
        d.handleMessageAddr(f'::ffff:{addr[0]}', addr[1], data)
        if received_data:   # read_cb was called = application-layer data arrived
            break
    except socket.timeout:
        break
```

---

## PSK generation (CoAP POST over a DTLS session)

After completing the handshake as `Client_identity` + security code, register a permanent identity via CoAP POST. This is one of the few parts of the process that just works:

```
POST coaps://192.168.x.x:5684/15011/9063
Content-Format: application/json
{"9090": "<custom identity name>"}

→ 2.01 Created
{"9091": "<generated PSK>", "9029": "1.21.xxxx"}
```

Store the returned identity + PSK; use them for all subsequent connections instead of `Client_identity` + security code.

---

## Final working solution ("the survivor's victory declaration")

**Goal**: list all devices, groups, and scenes under the gateway.

**Approach**:
- DTLS handshake and PSK generation: manual DTLSSocket (patched TinyDTLS) with AF_INET socket (bypassing macOS AF_INET6 limitations)
- Device enumeration: aiocoap `Context.create_client_context()` + `load_from_dict()` sending CoAP GET directly, parsing JSON keys manually
- **No pytradfri model layer** (pydantic incompatibility from #8)

This solution:
- Requires no changes to aiocoap itself
- Has no dependency on pytradfri's pydantic models
- Generates the DTLS PSK once, stores it in a JSON file, reuses it indefinitely

If you made it this far, congratulations. The rest is straightforward (compared to what came before).

## Notes on pytradfri / aiocoap integration on macOS (historical record for the sceptics)

`pytradfri` connects via `aiocoap`, which has its own tinydtls transport (`aiocoap.transports.tinydtls`). That transport creates its own DTLSSocket using an AF_INET6 socket, which hits **#4** (IPv4 responses not received) on macOS.

Even after fixing #4, pytradfri's model layer still fails due to **#8** (pydantic field incompatibility). The final decision was to bypass pytradfri entirely. Don't say you weren't warned.

If you want to stay on the pytradfri path, options include:
1. **Patch aiocoap's tinydtls transport** to use AF_INET + plain IPv4 addresses.
2. **Pin pytradfri to an older version**, or patch its models to remove the mandatory field validation.
3. **Run on Linux**, where AF_INET6 / IPv4-mapped behaviour works correctly and #4 is not an issue.

---

*Tested against TRADFRI gateway firmware 1.21.0051*

---

## Appendix — Debugging methodology ("a detective story where the detective keeps guessing wrong")

This appendix is not about answers — it's about how to find them. Each problem's first symptom is usually one error message; the investigation that follows is where the real time goes. If you're curious how an engineer can spend an entire weekend in a controlled fashion (spoiler: not controlled), read on.

### Phase 1: choosing a DTLS library (first impressions are wrong)

Started with aiocoap's default backend (libcoap), ran the pytradfri example, got `DTLS_ALERT_HANDSHAKE_FAILURE`.

First instinct: "wrong PSK or address." Spent time confirming parameters were correct, then started looking at ciphers. Listed OpenSSL 3 supported ciphers with `openssl ciphers` — no `TLS_PSK_WITH_AES_128_CCM_8`. Checked the OpenSSL changelog, confirmed AES-CCM was removed from the default provider in 3.0. Realised this wasn't a configuration problem — the library simply **doesn't support this cipher**.

Pivoted to TinyDTLS / DTLSSocket. The story had barely begun.

### Phase 2: confirming packets are actually received ("Schrödinger's UDP packet")

After installing DTLSSocket, aiocoap still timed out (`ConRetransmitsExceeded`). Two possibilities: wrong configuration, or packets genuinely not arriving or not being received.

**Key action: run tcpdump.** Always the right first step.

```bash
tcpdump -i any udp port 5684
```

tcpdump clearly showed: client sent ClientHello, gateway replied with HelloVerifyRequest, Python program showed no sign of receiving it. This ruled out "gateway not reachable." The problem was in the socket's receive layer.

Wrote a minimal test bypassing aiocoap, using `socket.recvfrom` directly. AF_INET socket received the response; AF_INET6 did not. Confirmed on macOS that IPv4-mapped behaviour differs from Linux.

### Phase 3: close_notify sent before handshake ("I didn't tell you to hang up")

After fixing the socket issue, using a custom AF_INET socket with DTLSSocket, ClientHello was actually being sent and HelloVerifyRequest received. But immediately **before any server response arrived**, DTLSSocket sent `close_notify` itself.

This was counterintuitive. ClientHello just left, the handshake hadn't started — why close the connection?

First suspicion: code in the event callback. Callback was one print statement. Impossible. Next thought: **maybe this isn't an active action but a destructor**. Some bugs aren't caused by what you wrote — they're caused by what you didn't write.

Checked `dtls.pyx` `Connection` class, found `__dealloc__` calling `dtls_reset_peer`, whose implementation is:

```c
void dtls_reset_peer(...) {
    dtls_destroy_peer(ctx, peer, DTLS_DESTROY_CLOSE);
}
```

`DTLS_DESTROY_CLOSE` sends `close_notify`. Tracing back up: `d.connect()` return value was not assigned in the test program, so Python immediately GC'd the `Connection` object. The whole chain was clear.

### Phase 4: handshake stalls after ServerHello ("the longest debugging marathon")

After fixing close_notify, the handshake progressed further but still ended with `handshake_failure`, and the PSK callback was never invoked. This meant the state machine never reached ClientKeyExchange.

Trace at this point:
```
← HelloVerifyRequest
→ ClientHello+cookie
← ServerHello          (triggered no callback)
← ServerHelloDone      (triggered no callback)
← ServerHello retransmit
→ Alert handshake_failure
```

**First suspicion**: PSK callback was called but output not appearing. Confirmed stderr was merged, confirmed .so was rebuilt. No issue.

**Second suspicion**: peer not found at all. Added `fprintf(stderr, "PEER FOUND/NOT FOUND")` inside `dtls_handle_message`. Result: FOUND every time. Ruled out.

**Third suspicion**: `handle_handshake_msg` not being called at all. Added debug print at function entry. Confirmed: ServerHello and ServerHelloDone did **not** trigger this function; only HelloVerifyRequest and the later retransmitted ServerHello did.

This made the problem concrete: **why do some packets reach `handle_handshake_msg` and others don't, even though the peer is found and the packets arrive?** Like having the right ticket but being refused entry.

What filter sits in between? Traced the call path upward, found the sequence deduplication logic. Manually decoded the record headers of HelloVerifyRequest and ServerHello, found both had **record sequence number 0**.

```python
hvr_seq = int.from_bytes(hvr_bytes[5:11], 'big')   # → 0
sh_seq  = int.from_bytes(sh_bytes[5:11],  'big')   # → 0 (!)
```

Complete explanation: the gateway resets its record sequence counter between flights, and TinyDTLS's deduplication logic doesn't recognise these as two different flights.

### Phase 5: ServerHello processed but still fails ("there's more?!")

After adding the `cseq.bitfield = 0` fix, ServerHello finally entered `handle_handshake_msg`, but returned an error immediately — still no ClientKeyExchange sent. Just as you see the light, the tunnel turns again.

Added debug at `check_server_hello` exit, printed the return value of `dtls_check_tls_extension`: `-552`.

Decoding `-552`: `-(2 * 256 + 40)`. Looking up TinyDTLS alert codes: `40 = 0x28 = DTLS_ALERT_HANDSHAKE_FAILURE`, level 2 = fatal.

Only one `error:` label in `dtls_check_tls_extension`. Traced back to find which `goto error` fired. Used debug prints to narrow it down to `check_forced_extensions`, where two force checks exist: `force_extended_master_secret` and `force_renegotiation_info`.

Manually decoded the ServerHello extension list (last 6 bytes: `00 04 00 17 00 00`) — only `0x0017` (extended_master_secret), no `0xFF01` (renegotiation_info).

Confirmed: `force_renegotiation_info` check was the culprit. Looked up RFC 5746, understood that the gateway's use of `TLS_EMPTY_RENEGOTIATION_INFO_SCSV` instead of the extension is perfectly valid. Neither side is wrong — they're just incompatible. Life is sometimes like that.

### Debugging methodology summary ("lies I tell myself about being faster next time")

Key techniques used throughout:

1. **tcpdump first**: before questioning any library behaviour, confirm the facts at the packet level. "Did the gateway respond?" is a network-layer question — don't rely on library timeout messages.

2. **`fprintf(stderr, ...)` in C source**: TinyDTLS's `dtls_set_log_level` output isn't granular enough. When behaviour is inexplicable, add `fprintf` at the entry point of the suspect function and rebuild. Crude but fast.

3. **Manually decode packet bytes**: the DTLS record and handshake header formats are fixed. A few lines of Python decode record seq, handshake type, and message seq. When facing "why wasn't this packet processed?", decode first, then correlate with source code — far more intuitive than strace.

4. **Trace GC-triggered side effects**: when Python calls a C extension, object dealloc can trigger C-level side effects (like sending network packets). When something happens that you didn't ask for, suspect GC timing first. This bug doesn't appear in textbooks.

5. **Decode error codes into meaningful values**: TinyDTLS return values use the encoding `-(level * 256 + code)`. `-552` means nothing at a glance; `(2, 40)` → `(fatal, handshake_failure)` gives you direction immediately. Never trust a number you can't read.
