# MCP inspection camera: the desktop app

An MCP server (Model Context Protocol, the standard way to plug tools, data and devices
into an AI application such as Claude Code) lets the AI take photos with a camera, look
closer at part of a photo, and record inspection results. The server, with its demo
login server and certificate script, is in a repository of its own, `mcp-server`. This
repository holds a desktop app (PySide6) that uses it. Claude Code connects to the
server directly, as the server's README shows; nothing for it lives here.

## What is here

- `inspection_station/`: the desktop app (command `inspection-station`). `station.py`
  runs the loop between Claude (Anthropic Python SDK, `AsyncAnthropic`) and the camera
  server (MCP `Client` over HTTP with the server's key); `app.py` is the window, which
  runs the station in a background thread with its own asyncio loop and gets each step
  as a Qt signal. The server's fail confirmation (MCP elicitation) becomes a dialog.
- `tests/test_station.py`: the loop against a stand-in for the camera server
  (`tests/stand_in_server.py`, in-process, the same tools) and a scripted stand-in for
  Claude. The app and the server are separate programs: the app never imports the
  server's code, so the server could be rewritten in another language without changing
  the app. What they share is the MCP interface (tool names, arguments, the text
  "Photo <ID> ...", the fail question) and the key file's path.

## Rules

- Claude Code sends login details only over HTTPS or to `localhost`.
- The simplest working version first; no features nobody asked for.
- US English spelling.
- The rules live in the camera server; the app only shows steps and passes answers on.
- Models: Claude Opus 5.5 (default) and Claude Sonnet 5.5; Haiku left out on purpose
  (it reads dials well but judges badly).
