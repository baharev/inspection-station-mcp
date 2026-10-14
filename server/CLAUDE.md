# MCP inspection camera

An MCP server (Model Context Protocol, the standard way to plug tools, data and devices
into an AI application such as Claude Code) that lets the AI take photos with a camera,
look closer at part of a photo, and record inspection results. The safety rules are
enforced in the server, not in the prompt. What it does and how to run it: `README.md`.

## Environment

- Python 3.11 or later, in a virtual environment of its own:
  `pip install -e ".[test]"`, then `pytest -q`. Add a dependency to `pyproject.toml` in
  the same step as installing it. Never install into the system Python.
- The tests and `.mcp.json` use the fake camera (`CAMERA=fake`), which serves the photos
  in `samples/`. A real camera is a Linux V4L2 webcam, opened by its stable
  `/dev/v4l/by-id/` path, never by a number (numbers change when devices are plugged in).
- Containers, if ever needed: podman.

## How to write the code

- MCP Python SDK version 2 names (not the version 1 names found in most blog posts):
  `MCPServer` (`from mcp.server import MCPServer`; version 1 called it FastMCP), `Image`,
  `Elicit` and `Resolve` from `mcp.server.mcpserver`, `ToolError` from
  `mcp.server.mcpserver.exceptions`, `ToolAnnotations` from `mcp.types`, `Client` from
  `mcp`. Check the installed package before guessing an API.
- Protocol version 2026-07-28 is stateless: no handshake, no session. State that must
  survive between calls is an explicit handle passed as a tool argument (the photo ID).
- Never `print()` in a stdio server: stdout carries the protocol. Log to a file.
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
