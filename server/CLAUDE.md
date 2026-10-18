# Inspection MCP server

An MCP server (Model Context Protocol, the standard way to plug tools, data and devices
into an AI application such as Claude Code) that lets the AI take photos with a camera,
look closer at part of a photo, and record inspection results. The safety rules are
enforced in the server, not in the prompt. This folder holds the server, with its
demo login server and a script for HTTPS certificates. Claude Code connects to it
directly (the README shows how); the desktop app that uses it is in the folder
`client` and never imports this code.

## Environment

- Python 3.13 or later (3.14 is the version tested; the tests also pass on 3.13), in a
  virtual environment of its own:
  `pip install -e ".[test]"`, then `pytest -q`. Add a dependency to `pyproject.toml` in
  the same step as installing it. Never install into the system Python.
- The fake camera (`CAMERA=fake`, or "Sample photos" in the camera list) serves the
  photos in `samples/`; the tests draw their own. The camera is always chosen by a
  person, never guessed: by its number in a list the server shows in a terminal
  (`choice.py`; saved in `~/.config/inspection-server/settings.json`, changed with
  `--choose-camera`), or with `CAMERA`, which comes first. What is saved is the camera's
  name or path, never the number (numbers change when devices are plugged in): on Linux
  a V4L2 webcam by its stable `/dev/v4l/by-id/` path; on Windows (through DirectShow) and
  macOS (not tested yet) by its name, or its device path for two of the same model.
  Without a person to answer the list (stdio, a service), the server stops and says why.
  `python scripts/check_camera.py` lists the cameras with their values for `CAMERA`.
- The server alone opens the camera: a background thread reads frames while photos or the
  live view (`/live`, with `--http`) are used, and releases the camera a minute later.
  Meanwhile no other program can open it; the live view replaces separate camera viewers.
- The server window (`inspection-server-window`, `inspection_server/window.py`) runs
  `inspection-server --http` as a separate program and shows its output; Stop ends it.
  Tkinter is imported only there: the server never depends on the window, and a computer
  without a screen never needs it. Its choices live in the same settings file.
- Containers: podman (the demo login server, `scripts/keycloak.sh`).

## How to write the code

- MCP Python SDK version 2 names (not the version 1 names found in most blog posts):
  `MCPServer` (`from mcp.server import MCPServer`; version 1 called it FastMCP), `Image`,
  `Elicit` and `Resolve` from `mcp.server.mcpserver`, `ToolError` from
  `mcp.server.mcpserver.exceptions`, `ToolAnnotations` from `mcp.types`, `Client` from
  `mcp`. Check the installed package before guessing an API.
- Protocol version 2026-07-28 is stateless: no handshake, no session. State that must
  survive between calls is an explicit handle passed as a tool argument (the photo ID).
- Never `print()` in a stdio server: stdout carries the protocol. Log to a file.
- Over HTTP, every request needs the secret key or a login token (the SDK's
  `TokenVerifier`); roles come from the token's `roles` claim and are checked in each
  tool. The key is in `~/.config/inspection-server/api-key` (made by the server at its
  first start) unless `API_KEY` is set. The `claude mcp add` line the server prints reads
  the file once and Claude Code keeps its own copy: after a new key, run the line again.
  Claude Code sends login details only over HTTPS or to `localhost`.
- Every rule lives in the server: inputs validated, limits in code, a human confirms
  anything with consequences, everything audit-logged. Tool annotations are hints for the
  host, not protection.
- The simplest working version first; no features nobody asked for.
- Tests with pytest, in-process (`Client(server)`), against the fake camera, so they run
  without hardware.

## Photos and text

- Real camera photos go to `captures/` (git-ignored). Look at every photo before
  committing it: a camera can catch people or a room. Keep sample photos at the camera's
  full size; the detail is what the examples need.
- No readable brand names in a committed photo: blur logos and makers' names, and check
  the result in enlarged crops.
- US English spelling.
