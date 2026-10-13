# FlowLite 2

FlowLite is a private, fully offline recreation of Wispr Flow's desktop experience on Windows: the same floating Flow Bar, the same shortcuts and gestures, and the same hub pages. Speech recognition (Whisper) and formatting (a local Ollama model) run on your PC, and a runtime guard blocks every non-loopback network connection.

The look and behaviour were reverse-engineered with REA from Wispr Flow 1.6.1102:
- static analysis of its `app.asar`;
- live Chrome DevTools Protocol inspection of its windows (DOM, computed design tokens, screenshots);
- the inventories in `docs/UI_SPEC.md` and `REPORT.md`.

All code, copy and artwork are original; nothing from Wispr was copied. Figtree and EB Garamond are OFL fonts and the icons are Lucide-style (ISC); see `flowlite/assets/LICENSES.md`.

## Run

Double-click **FlowLite** on the Desktop. FlowLite runs in the background with the Flow Bar and a tray icon. Opening it again shows the hub window.

First-time setup (already done on this PC):
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m flowlite.setup --whisper small   # downloads models once (the only online step)
.venv\Scripts\python -m flowlite.shortcut                # Desktop + Start menu icon
```

## What's included

| | Same as Wispr |
|---|---|
| **Flow Bar** | All of its states, at Wispr's measured sizes:<ul><li>40×8 resting pill</li><li>hover with a "Hold Ctrl + Win" tooltip</li><li>73×30 push-to-talk waveform</li><li>hands-free with cancel/stop buttons</li><li>amber Command Mode</li><li>processing spinner</li><li>red error state</li></ul>Notification cards rise above the pill. Right-click menu: Hide for 1 hour, Settings, Microphone, Transcript history, Paste last. |
| **Shortcuts** | Hold **Ctrl+Win** to talk. Double-tap it or press **Ctrl+Win+Space** for hands-free. **Ctrl+Win+Alt** for Command Mode on selected text. **Shift+Alt+Z/X** to paste/copy the last dictation. **Win+Alt+1/2** to run Transforms (Polish / Prompt Engineer) on selected text. **Esc** cancels. Same 500 ms debounce and lock rules as Wispr. |
| **Home** | Welcome header, tip banner, stats card (words, WPM, streak), history grouped by day. Each history row can play its audio, copy, show the original, retry or delete. |
| **Insights** | WPM gauge, fixes, total words, usage by app type, streak heatmap, and a "Your voice" tab. |
| **Dictionary / Snippets** | Words, misspelling→correct replacements, auto-learned words (sparkle), stars, search and sort; snippets up to 4000 characters. |
| **Style** | Formal / Casual / very casual for each of personal, work, email and other apps; Auto cleanup levels None / Light / Medium / High. |
| **Transforms** | Polish, Prompt Engineer and your own transforms, with shortcuts and an optional auto-apply after dictation. |
| **Scratchpad** | Local notes with autosave, a checklist and transforms. |
| **Settings** | General (shortcut recorder, microphone, dictation languages), System, Models, Experimental, Data and Privacy (import from Wispr Flow, local storage policy, delete history). |
| **Your Wispr data** | On first run, FlowLite offers to import your Wispr history, dictionary, snippets and preferences, reading Wispr's local files only. |

**Languages:** Whisper `small` multilingual. The language is detected per dictation among the languages you selected in Settings (a tiny model does the detection in about 0.2 s), so Hebrew stays Hebrew. As in Wispr, AI style formatting applies to English; other languages get light cleanup.

**Not included:** features that depend on Wispr's cloud — account, billing, team and sharing, cloud sync, connectors/MCP, leaderboards. The Notetaker meeting recorder is also left out, at your choice.

## Speed on this laptop (i5-13500H, no GPU)

A `small` transcription pass costs about 3.5 s here at the CPU's current 2.6 GHz, whatever the clip length. So text appears about 3–4 s after you release the keys, and formatting is prefetched while you pause.

Options:
- **Settings → Models → `base`:** about 1 s, but weaker Hebrew.
- **Windows power mode "Best performance":** roughly doubles the speed.
- **Keep `small`:** for the best Hebrew.

## Checks

```powershell
.venv\Scripts\python selftest.py          # TTS → streaming ASR → local LLM, network guard on
.venv\Scripts\python -m pytest -q tests   # hotkey/gesture state machine
```
