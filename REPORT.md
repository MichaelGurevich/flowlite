# Wispr Flow for Windows: how it works, from its shipped files

**Target:** `%LOCALAPPDATA%\WisprFlow\app-1.6.1102` (Squirrel install; older `app-1.6.1074` is also present)

| Artifact | SHA-256 |
|---|---|
| `resources\app.asar` | `5a35c867858fd0c14c643bf3530b0ba928869ff01a1383a437eb255db4969a74` |
| `.webpack\main\index.js` (from the asar) | `780f0b91be2830c236142f220772b158eef9e311b5d7b2d3f891ec93ee6c17b2` |
| `.webpack\renderer\hub\index.js` | `fe875a7352868460f430161355c6d2909980efc8b80e9fc3e2d56937c6a1e8de` |
| `.webpack\renderer\dist\recorderWorklet.js` | `3cd6c33bc2fcb35337fd1a43896fb92aa89ec3066a9d978fc02d8a5292d18d2e` |
| `resources\Release\Wispr Flow Helper.exe` | `c58c61b106c83f7b77efc921b0e849bb7210154898504215f17306c1a6d6abe0` |

**Method:**
- **REA:** `analyze_javascript_application` on `app.asar` (summary Evidence `ev_d3d463f8…`, parent `ev_9b544f91…`). It found 228 relevant files, 213 parsed JavaScript files, 1474 modules and 207 IPC operations. Semantic graph coverage is *partial*: REA hit its resource limits on `main/index.js` and several large chunks. An REA trace of the `dictation:audioChunk` channel returned no match, because the channels are referenced through minified enums (`ev_05d5fe55…`). An REA/Ghidra open of the helper `.exe` worked, but its string search timed out on this 20 MB NativeAOT binary.
- **Manual tracing:** the call chains below were traced by reading the extracted bundle at the byte offsets given. The helper's behaviour comes from its embedded strings: P/Invoke names, .NET type and member names, and log messages.
- Everything here is **static**. Nothing was executed and no network traffic was captured.

Offsets are character offsets into the named file.

---

## 1. Architecture at a glance

```
 ┌──────────────── Electron (wispr-flow 1.6.1102, Electron 42) ───────────────┐
 │  hidden "hub" renderer            main process                              │
 │  getUserMedia 16 kHz mono  ──IPC──► dictation:audioChunk ──► GrpcClient ─────┼──► gRPC bidi stream
 │  AudioWorklet 40 ms chunks        (int16 "wav" or Opus)       flow_api.v1     │    model-<id>.grpc.api.baseten.co
 │  WebCodecs Opus 20 ms (opt.)                                  .Transcription  │    (or inference.wisprflow.com edge)
 │                                   ▲            │              Service/        │
 │                                   │ stdin/stdout JSON         TranscribeStream│◄── State (raw/formatted partials)
 │                                   │ ('|'-framed)              + HTTP fallback │◄── Result (html + plaintext)
 └───────────────────────────────────┼────────────┼────────────────────────────┘
                                     │            ▼
                     Wispr Flow Helper.exe (C# .NET NativeAOT)
                     low-level kbd/mouse hooks → KeypressEvent → main (hotkey logic)
                     UI Automation → TextBoxInfo (before/selected/after text)
                     PasteText → clipboard (delayed rendering) + SendInput Ctrl+V → restore clipboard
```

---

## 2. Speech capture — **proven**

| Claim | Evidence |
|---|---|
| Mic capture lives in the hidden *hub* renderer window (`MediaManager`, minified `mf`). Main tells it to start with IPC `dictation:audioStart {useOpus, transcriptionEntityUuid}`. | hub `index.js` @671746 (`(0,Oe.x)(S.kH.AudioStart, … mf.startRecording(…))`) |
| Constraints are 16 kHz, mono, with **echo cancellation, noise suppression and auto-gain all off**. | hub @668405 `static mediaOptions={audio:{echoCancellation:!1,noiseSuppression:!1,autoGainControl:!1,sampleRate:nf,channelCount:1}}`. `nf=16e3`, `tf=40` @665190 |
| An `AudioWorkletProcessor` (`recorder-processor`) buffers 640 samples (40 ms) and posts Float32 chunks to the page. | `renderer/dist/recorderWorklet.js` (`chunkSize=640`) |
| Chunks are converted to Int16 PCM (`cf()`, clamp ×32767) and sent to main as `dictation:audioChunk {packet, index, volume(dBFS), duration:40, encoding:"wav", transcriptionEntityUuid}`. | hub @753226 |
| Optionally, the same PCM also goes through WebCodecs `AudioEncoder` `{codec:"opus", sampleRate:16000, channels:1, bitrate:64000}`, giving 20 ms Opus packets with `encoding:"opus"`. | hub @758509, `af` @665190 |
| Silence detection: 125 silent chunks (5 s) raise a "no audio" notification and 375 chunks (15 s) escalate it. If the mic goes quiet, it is reopened. | hub, statics near @668405 (`SILENCE_WARNING_THRESHOLD_CHUNKS=125`) |
| Main checks the packet index and the session UUID, drops stale or out-of-order chunks, and appends each chunk to `wavAudioPackets` or `opusAudioPackets`. The first chunk "warms up" the backend. | main @4239595 (`Ln`) |
| Push-to-talk keys come from the **helper's low-level keyboard hook**: the helper sends `KeypressEvent {eventType, key, index}` and main runs the shortcut state machine. | main @4395559. Helper strings `SetWindowsHookExW`, `LowLevelKeyboardProc`, `LowLevelMouseProc`, `CallNextHookEx`, `Failed to create keyboard hook` |

Other audio paths, not used for dictation: Jabra headset buttons through `jabra-device-connector.exe` (a .NET SDK, 4-byte length-prefixed JSON over stdin), BLE mic audio (`BLEAudioData`), and meeting capture (mic plus `getDisplayMedia` loopback) for the "Notetaker".

## 3. Getting transcription results — **proven protocol, hidden models**

**Transport.** `@grpc/grpc-js` with `@protobuf-ts`. The service is `flow_api.v1.TranscriptionService`, with two methods (main @3692528):
- `Transcribe`, unary. Used as a gRPC "HTTP fallback".
- `TranscribeStream`, **bidirectional streaming**. This is the primary path.

**Endpoint selection** (`getDesiredGrpcModelInfo`, inside class `rn` @3695070):
- Default: `model-<id>.grpc.api.baseten.co` with model id `v31pl413`, environment `production`. Wispr's ASR/formatting runs on **Baseten**.
- Feature flags (PostHog) can switch to staging, a geo-optimal model id (`grpcGeo`), or an edge proxy. The edge-proxy host is read from `https://inference-info.wisprflow.com/dictation_url.txt` (@3589044) and must match an allowlist: `inference.wisprflow.com`, `model-v31pl413.grpc.api.baseten.co`, `wispr-ai-prod--prod-grpc-server-flowgrpcserver.us-east.modal.direct`. That last host means **Modal** is also a deployment target.

**Request metadata** (@3714109) includes:
- `authorization: Bearer <user access token>`
- `baseten-authorization: Api-Key <key>`
- `baseten-model-id`, `x-baseten-environment`, `flow-debug`, `disable-formatting`

> **Note:** the Baseten API key is a **constant compiled into the client** (value redacted here). Every install ships the same vendor key; the per-user bearer token is what the Wispr backend presumably checks. I did not use the key.

**Stream protocol** (the full schema was recovered: `Request` @3678546; the complete dump is in the scratch notes):
1. The first `Request` carries `init`:
   - `Metadata`: user/session/request UUIDs, `audio_encoding` (WAV or OPUS), client name, platform and version.
   - `Preferences`: languages; personal and team dictionary words plus starred words; replacement and snippet maps; style config. Style config covers writing style per context (personal, work, email, other), editing strength (verbatim, light, medium), Slack tagging and email signature.
   - Optionally a previous `State`.
2. Then repeated `Request {payload: AudioPackets{items: bytes[]}, context?, commit: FALSE}`. Context is re-sent whenever the textbox changes:
   - `App` (name, bundleId or exe, url, type: email, chatbot, other…)
   - `Textbox` (contents, before, selected, after)
   - `DynamicVocabulary` (screen words from accessibility, **OCR**, VS Code variable and file names)
   - `content_text` and `content_html` (an HTML rendering of the accessibility tree)
   - `Conversation` (chat messages)
   - `screenshot`: always sent as an **empty** `Uint8Array` in this build (@3721139)
3. On key release: `commit: TRUE`, then the client half-closes the stream.
4. Responses:
   - `Heartbeat {audio_received_seconds, commit_ack}` lets the client measure server lag. More than 2 s of lag, or 4 s with no heartbeat, triggers the fallback.
   - `State {raw_text, formatted_text, progress{transcriber, formatter, post_processing}, candidate_beams, audio_snr, audio_volume, mean_alignment_score}` provides streaming partials.
   - `Result {output: Transcription{html, plaintext, languages, confidence}, response_time{transcribe, format, post_process, external_asr_time, external_llm_time…}, status RAW_TRANSCRIPT|FORMATTED|ERROR, transcript_origin ∈ {internal, external, internal_experimental, canto_1.0, canto_1.0.1, canto_1.1}}`.

**Resilience:**
- A **parallel HTTP race** POSTs the WAV packets to `https://chain-o232k03l.api.baseten.co/environments/production/run_remote` (a Baseten *Chain*, JSON or msgpack). Behind a flag it goes to Wispr's own `…/llm/dictation` instead (@3558926, @3562102).
- Whichever answer arrives first wins.
- The HTTP race is skipped for audio of 30 s or more.
- Commit backstop: 20 minutes.

## 4. Inserting text into other apps — **proven (helper by strings)**

| Step | Evidence |
|---|---|
| Main spawns `resources\Release\Wispr Flow Helper.exe` and talks to it over **stdin/stdout**. Messages are JSON (`HelperAPIRequest`/`HelperAPIResponse`, schema generated with quicktype, ~100 request types), framed by `\|` with `+`-escaping (`+`→`+1`, `\|`→`+2`). | main @4436284, @4430392, schema @2486916. A dev-build error message says it is built with `publish-aot.cmd` (C# NativeAOT) |
| Before pasting, main saves the current clipboard text and sends `PasteText {pasteId, text, htmlText?}`. | main @4464917–4465157 |
| The helper: <ul><li>finds the focused element through UI Automation, falling back to `GetForegroundWindow()`</li><li>loads the text into a **delayed-rendering clipboard** (`DelayedClipboardManager`, `ClipboardDelayedRendering`, HTML clipboard format)</li><li>presses **Ctrl+V with `SendInput`**</li><li>treats the target app *reading* the clipboard as proof of a successful paste (`Clipboard read detected! Rendering delayed data...`, `Clipboard not read within timeout -- paste likely failed`)</li><li>restores the previous clipboard unless it changed meanwhile (`Clipboard changed since paste, skipping restoration`)</li></ul> It falls back to a plain clipboard paste if delayed rendering fails. | helper strings |
| Pasted text is marked so it doesn't land in Win+V history or cloud clipboard. | strings `CanIncludeInClipboardHistory`, `CanUploadToCloudClipboard`, `Clipboard Viewer Ignore` |
| Stale modifiers (for example a still-held hotkey) are checked and released before pasting. | `CheckStaleKeys` request, `StaleKeysResponse`, `SendMaskingSequence` |
| Afterwards the helper reports `PasteOutcome {success, timeElapsedMs}`. `DictatedTextVerification` then re-reads the textbox to confirm the text landed. `UpdateEditedText` and `contentObservation*` watch your later edits, which feed the auto-learned dictionary. | schema plus helper strings |

## 5. Local data — **proven**

`%APPDATA%\Wispr Flow\flow.sqlite` (Sequelize, 169 migrations). The `History` table stores, per dictation:
- the ASR text, formatted text and edited text
- **audio** and Opus chunks, plus a `screenshot` column
- `axText` and `axHTML` (accessibility snapshot of the window), textbox contents
- app, url, latencies, and more

Only the schema was read, not your rows. A nightly backup cron copies the DB to `backups\`.

---

## What is inferred (high confidence, not directly observed)

- **The server is a two-stage pipeline: ASR, then LLM "formatter".** `Progress` has separate transcriber and formatter stages, and `ResponseTime` has `external_asr_time` and `external_llm_time`. So some requests go to third-party ASR or LLM vendors, which matches the website's "zero data retention agreements with third-party AI providers".
- **"canto_1.x" is Wispr's in-house ASR model.** It appears as a `transcript_origin` value, and the website links `wisprflow.ai/canto`.
- **The partial results feed a "streaming text" preview.** The client uses them for an instant-classification feature (`instructShortcut`, Command Mode). It does not paste them.
- **The hotkey matching runs in JavaScript.** The helper just forwards raw key events.
- **The user bearer token is a Supabase or WorkOS session JWT that Baseten forwards to Wispr's auth.** The supabase-js and @workos-inc/node dependencies and `api.wisprflow.ai` support this, but I didn't trace the token's validation.

## What remains hidden

- **The models and prompts**: ASR model architecture and weights, the formatting LLM, its prompts, how style and dictionary are applied, and which external vendors are used. All of it is server-side.
- **How OCR words are produced on Windows** (`screen_content_ocr`). The helper does it natively or it isn't populated on Windows; I didn't confirm which without disassembly.
- **The exact helper control flow**: timeouts, retry order, and the UIA heuristics for Electron, Chrome and Office. Ghidra timed out on the 20 MB NativeAOT image, so this needs a longer native session or runtime tracing such as API Monitor or ETW.
- **Feature-flag values**: PostHog decides at runtime which path (gRPC vs. HTTP race, edge proxy, Opus vs. WAV) is live for a given user.
- **Server-side retention and training**, beyond the website's policy statements.
- **Runtime confirmation.** Nothing here was observed running. A passive capture (`list_electron_targets` against a debug port, or an HTTPS/gRPC proxy) would confirm the live endpoint and encoding.
