# MCP inspection camera: the desktop app and the Claude Code side

An MCP server (Model Context Protocol, the standard way to plug tools, data and devices
into an AI application such as Claude Code) lets the AI take photos with a camera, look
closer at part of a photo, and record inspection results. The server, with its demo
login server and certificate script, is in a repository of its own, `mcp-server`. This
repository holds the programs that use it: a desktop app (PySide6), and the setup for
Claude Code.

## What is here

- `inspection_station/`: the desktop app (command `inspection-station`). `station.py`
  runs the loop between Claude (Anthropic Python SDK, `AsyncAnthropic`) and the camera
  server (MCP `Client` over HTTP with the server's key); `app.py` is the window, which
  runs the station in a background thread with its own asyncio loop and gets each step
  as a Qt signal. The server's fail confirmation (MCP elicitation) becomes a dialog.
- `tests/test_station.py`: the loop against the real server in-process (fake camera)
  and a scripted stand-in for Claude; needs `mcp-server` installed in the environment.
- `.mcp.json`: registers the server for Claude Code in this folder. It starts the
  server's command `inspection-camera` (installed from `mcp-server` into the active
  Python environment) with the fake camera, which serves stored photos instead of a real
  camera. A private setting (`claude mcp add -s local ...`) overrides it, for example to
  reach a server with a real camera on another computer.

## Rules

- Claude Code sends login details only over HTTPS or to `localhost`.
- The simplest working version first; no features nobody asked for.
- US English spelling.
- The rules live in the camera server; the app only shows steps and passes answers on.
- Models: Claude Opus 5.5 (default) and Claude Sonnet 5.5; Haiku left out on purpose
  (it reads dials well but judges badly).
