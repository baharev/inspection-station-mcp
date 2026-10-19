# Inspection MCP server

The MCP server of this repository (the top-level `CLAUDE.md` says what MCP is and how the
two programs relate): it lets the AI take photos with a camera, look closer at part of a
photo, and record inspection results. The safety rules are enforced here, not in the
prompt.

## What is here

- `inspection_server/`: the server (`server.py`), the cameras (`camera.py`), choosing the
  camera and photo size (`choice.py`), the server window (`window.py`) and the live view
  page (`live.html`); `scripts/`: the demo login server (`keycloak.sh`, podman), HTTPS
  certificates, a camera check and the try-it script. Every file: the README's
  [Files](README.md#files).
- The server alone opens the camera: a background thread reads frames while photos or the
  live view (`/live`, with `--http`) are used, and releases the camera a minute later.
  Meanwhile no other program can open it; the live view replaces separate camera viewers.
- The server window (`inspection-server-window`, `inspection_server/window.py`) runs the
  server (`python -u -m inspection_server.server --http`) as a separate program, without
  `CAMERA` and `CAMERA_SIZE` and with no terminal to answer, and shows its output; Stop
  ends it. Tkinter is imported only there: the server never depends on the window, and a
  computer without a screen never needs it. Its choices live in the server's settings
  file, `~/.config/inspection-server/settings.json`, which the camera menu writes too
  (`choice.py`).

## Environment and tests

- In this folder, in its own virtual environment: `.venv/bin/pip install -e ".[test,dev]"`,
  then the checks the top-level `CLAUDE.md` lists. Install with `-e`: the server finds
  `samples/` and keeps `logs/` next to its code.
- Six of the twelve tests in `tests/test_window.py` open a window and are skipped without
  a screen. After a change to `window.py`, run them: with `DISPLAY=:0` on a desktop
  computer reached over SSH, or under `xvfb-run -a`, as the CI workflow does.
- Most tests run in-process (`Client(server)`, or the HTTP app through an ASGI transport
  in `tests/test_http.py`) against `FakeCamera` on photos they draw in a temporary folder,
  so they need no hardware. `tests/conftest.py` keeps this computer's saved camera choice,
  `CAMERA` and `CAMERA_SIZE` away from them.

## Rules a change must not break

- The camera is always chosen by a person, never guessed: by its number in a list the
  server shows in a terminal, by its name in the server window's list, or with `CAMERA`
  (and `CAMERA_SIZE`), which comes first in a terminal; the window removes both from the
  server's environment, and `--choose-camera` refuses to run while either is set. What is
  saved is the camera's name or path, never the number (numbers change when devices are
  plugged in). Without a person to answer the list (stdio, a service), the server stops
  and says why; a saved camera that is missing stops it too, never another camera. How it
  works for the user: the README's [Choosing a camera](README.md#choosing-a-camera).
- Every rule lives in the server: inputs validated, limits in code, a person confirms
  every fail (a pass or an unsure is recorded without asking, on purpose), and every
  action and every refusal by a rule is audit-logged (a malformed input or an unknown
  photo ID is refused without a log line). The person's answer reaches
  `record_inspection` only through `Resolve(confirm_fail)`, never as a tool argument the
  AI could fill in. Tool annotations are hints for the host, not protection. The whole
  list: the main README's
  [rules](../README.md#the-tools-the-server-provides-and-the-rules-it-enforces) and
  [guarantees](../README.md#what-the-server-can-and-cannot-guarantee).
- Over HTTP, the SDK's `TokenVerifier` refuses a request without the secret key or a
  login token only at `/mcp`; every other route checks for itself. The live view's page,
  `/live`, holds no secrets and is open to anyone; its pictures, `/live/frame.jpg`, need a
  key or token from other computers and none from the station computer itself
  (`from_this_computer`). A new route checks the same way. Roles come from the token's
  `roles` claim and are checked in each tool and in the live view.
- Nothing may write to stdout in stdio mode: it carries the protocol. Messages for the
  person go to stderr, records to the log files.

## How to write the code

- MCP Python SDK version 2 names (not the version 1 names found in most blog posts):
  `MCPServer` (`from mcp.server import MCPServer`; version 1 called it FastMCP), `Image`,
  `Elicit` and `Resolve` from `mcp.server.mcpserver`, `ToolError` from
  `mcp.server.mcpserver.exceptions`, `ToolAnnotations` from `mcp.types`, `Client` from
  `mcp`. Check the installed package before guessing an API.
- Protocol version 2026-07-28 is stateless: no handshake, no session. State that must
  survive between calls is an explicit handle passed as a tool argument (the photo ID).
  The server also serves clients of the older versions (2025-11-25 and before), which keep
  a session and ask the person during the tool call; keep both working. The tests of the
  fail question run under both (`under_both_protocols` in `tests/test_server.py`), and a
  new one should too.

## Photos

- Real camera photos go to `captures/` (git-ignored). Look at every photo before
  committing it: a camera can catch people or a room. Keep sample photos at the size the
  camera took them (1920x1080 here), never scaled down; the detail is what the examples
  need.
- No readable brand names in a committed photo: blur logos and makers' names, and check
  the result in enlarged crops. Then show me each photo and its crops: I approve every
  photo before it is committed.
