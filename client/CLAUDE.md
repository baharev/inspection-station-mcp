# MCP inspection camera: the Claude Code side

An MCP server (Model Context Protocol, the standard way to plug tools, data and devices
into an AI application such as Claude Code) lets the AI take photos with a camera, look
closer at part of a photo, and record inspection results. The server, with its demo
login server and certificate script, is in a repository of its own, `mcp-server`. This
repository holds how Claude Code connects to it.

## What is here

- `.mcp.json`: registers the server for Claude Code in this folder. It starts the
  server's command `inspection-camera` (installed from `mcp-server` into the active
  Python environment) with the fake camera, which serves stored photos instead of a real
  camera. A private setting (`claude mcp add -s local ...`) overrides it, for example to
  reach a server with a real camera on another computer.

## Rules

- Claude Code sends login details only over HTTPS or to `localhost`.
- The simplest working version first; no features nobody asked for.
- US English spelling.
