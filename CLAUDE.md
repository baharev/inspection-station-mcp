# Inspection Station MCP

Two separate programs in one repository, each with its own `pyproject.toml`, environment,
tests and `CLAUDE.md`:

- `server/`: the MCP server `inspection-server` (camera, tools, rules, audit log), its demo
  login server and certificate script. Read `server/CLAUDE.md` before changing it.
- `client/`: the desktop app `inspection-client`. Read `client/CLAUDE.md` before changing it.

The client never imports the server's code: they share only the MCP interface (listed in
`client/CLAUDE.md`), and the client's tests run against `client/tests/stand_in_server.py`
in an environment without the server, so the server could be rewritten in another
language without changing the client. A change to that interface changes both folders in
one commit.

Shared: `docs/setup.svg` (the figure in the main README) and `LICENSE`. The main
`README.md` tells the story (quick start, the AI's answers, the rules, the audit trail);
`server/README.md` and `client/README.md` are references for installing and running each.
US English spelling.
