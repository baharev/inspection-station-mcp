# Inspection MCP client: the desktop app

The desktop app (PySide6) of this repository (the top-level `CLAUDE.md` says what MCP is
and how the two programs relate): it runs the loop between Claude and the inspection
server and shows each step. Claude Code connects to the server directly, as the server's
README shows; nothing for it lives here.

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
  `test_contract.py`, the stand-in compared with the real server, skipped unless the
  server is installed in the same environment. `conftest.py` holds the `offline` fixture
  (HTTP to a stand-in, never the network) and `anyio_backend` (asyncio). Every file: the
  README's [Files](README.md#files).
- What the app and the server share (the top-level `CLAUDE.md` says why), which the
  stand-in server must follow; `tests/test_contract.py` checks the MCP part against the
  real server:
  - the tool names and arguments (`capture_image`, `zoom_image`, `record_inspection`):
    adding, removing or renaming a tool or an argument changes the interface, so the
    stand-in and this list change with it; and the smallest zoom, `MIN_ZOOM`;
  - the photo's ID in the field `image_id` of `capture_image`'s structured content
    (Claude reads it in the sentence "Photo <ID> ...");
  - the fail question: one boolean field, `mark_failed`; any other question is declined;
  - the record's fields `part_id`, `verdict`, `fail_confirmation` and `note`;
  - the SDK's prefix `"Error executing tool <name>: "` on a refusal, which `app.py`
    strips before showing it;
  - the key file's path, and the setting `API_KEY`, which comes before it;
  - beside MCP, and not checked by the contract test: the live view's pictures at
    `/live/frame.jpg` next to `/mcp`, with the same key or token, refused with 401 or 403
    and a reason in plain text; and the app's registration in the demo login server
    (client `inspection-client`, callback port 33419, in
    `server/keycloak/inspection-realm.json`).

## Environment and tests

- In this folder, in its own virtual environment, without the server:
  `.venv/bin/pip install -e ".[test,dev]"`, then the checks the top-level `CLAUDE.md`
  lists.
- The window and dialog tests need no screen: they set Qt's `offscreen` platform.
- The contract test is skipped unless the server is installed in the same environment:
  run it in a throwaway environment, as the top-level `CLAUDE.md` says, never by
  installing the server into this one.

## Rules

- The rules live in the inspection server; the app only shows steps and passes answers on.
- Models: those in `MODELS` (`inspection_client/station.py`), an Opus as the default and a
  Sonnet (today Claude Opus 5.5 and Claude Sonnet 5.5); never a Haiku (it reads dials well
  but judges badly). A model replaces one of these only after the main README's questions
  are asked again and its comparison is updated. Model IDs and prices come from
  Anthropic's model and pricing pages, never from memory; the commit says where they came
  from.
