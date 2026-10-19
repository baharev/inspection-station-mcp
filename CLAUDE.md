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

Each fact is written in one README and linked from the others, so a change is made once:

- Main README: the quick start (one computer, the secret key, Linux and Windows, the app and
  Claude Code, answering a fail in Claude Code), the rules (roles, the time limit for a
  fail question), the guarantees, the audit trail, the costs and the model comparison.
- `server/README.md`: everything else about the server: what it prints at start, Claude
  Code starting it, two computers, logins and the demo users, the window, the live view,
  cameras and photo sizes, settings, Windows details (`$env:` settings, firewall, `scp`).
- `client/README.md`: everything else about the app: installing, the Claude API key, what
  the window shows, the app on another computer and with logins, its Windows details.

When a sentence would repeat one of these, link to it instead.
