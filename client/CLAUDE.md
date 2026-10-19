# Inspection MCP client: the desktop app

An MCP server (Model Context Protocol, the standard way to plug tools, data and devices
into an AI application such as Claude Code) lets the AI take photos with a camera, look
closer at part of a photo, and record inspection results. The server, with its demo
login server and certificate script, is in the folder `server`. This
folder holds a desktop app (PySide6) that uses it. Claude Code connects to the
server directly, as the server's README shows; nothing for it lives here.

## What is here

- `inspection_client/`: the desktop app (command `inspection-client`). `station.py`
  runs the loop between Claude (Anthropic Python SDK, `AsyncAnthropic`) and the
  inspection server (MCP `Client` over HTTP with the server's key or a login); `app.py` is the
  window, which runs the station in a background thread with its own asyncio loop and
  gets each step as a Qt signal. The server's fail confirmation (MCP elicitation)
  becomes a dialog. `login.py` is the login in the browser (`--login`; the SDK's
  `OAuthClientProvider` does the rest).
- `tests/`: `test_station.py`, the loop against a stand-in for the inspection server
  (`stand_in_server.py`, in-process, the same tools) and a scripted stand-in for Claude;
  `test_window.py`, the conversation and the live view in the window; `test_dialog.py`,
  the fail dialog;
  `test_login.py`, the app's part of the login, with the browser and the login server
  played by the test; `test_main.py`, the start (which key or login, address and
  certificates the parts get); `test_contract.py`, the stand-in compared with the real
  server, skipped unless the server is installed in the same environment. `conftest.py`
  holds the `offline` fixture (HTTP to a stand-in, never the network) and
  `anyio_backend` (asyncio).
- The app and the server are separate programs: the app never imports the server's
  code, so the server could be rewritten in another language without changing the app.
  What they share is the MCP interface, which the stand-in server must follow:
  - the tool names and arguments (`capture_image`, `zoom_image`, `record_inspection`);
  - the photo's ID in the field `image_id` of `capture_image`'s structured content
    (Claude reads it in the sentence "Photo <ID> ...");
  - the fail question: one boolean field, `mark_failed`; any other question is declined;
  - the record's fields `part_id`, `verdict`, `fail_confirmation` and `note`;
  - the SDK's prefix `"Error executing tool <name>: "` on a refusal, which `app.py`
    strips before showing it;
  - and the key file's path.

## Rules

- The simplest working version first; no features nobody asked for.
- US English spelling.
- The rules live in the inspection server; the app only shows steps and passes answers on.
- Models: Claude Opus 5.5 (default) and Claude Sonnet 5.5; Haiku left out on purpose
  (it reads dials well but judges badly).
