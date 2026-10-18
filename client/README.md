# Inspection MCP client: the desktop app

A window where Claude inspects parts with a camera. You type a question, such as "Is the
tray complete?". Claude takes a photo, looks closer where it needs to, answers, and can
record the result. The window shows each step with its pictures, and the camera's live
picture next to it. When Claude finds a part bad, a dialog asks you first, with the
photo; no part is marked as failed without your yes.

A self-built demonstration of connecting a device to AI models through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP), the standard way to
plug tools, data and devices into AI applications. The camera sits behind an MCP server,
in the companion repository `inspection-mcp-server`; this repository holds a desktop app that uses
it. Claude Code can use the server too, without this app: see the `inspection-mcp-server` README.
The app is small on purpose: about
1,200 lines of Python, using the official MCP and Anthropic libraries.

Author: [Ali Baharev](https://baharev.info/)

## Quick start

You need two things first:

- **The inspection server, running on this computer**: see the Quick start of the
  `inspection-mcp-server` README. Its sample photos work without a camera.
- **A Claude API key** in the file `~/.config/anthropic/api-key`: see
  [Your Claude API key](#your-claude-api-key).

Then, on Linux, in a terminal, in this repository's folder:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
inspection-client
```

On Ubuntu and Debian, `python3 -m venv` needs `sudo apt install python3-venv` once. On
Windows, in PowerShell, in this repository's folder:

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
inspection-client
```

In the window, ask for example: "Take a photo. Is the tool tray complete?" The rest of
this README explains each step, other setups, and logins.

## What an inspection station is

A factory makes parts: a filled box, a tray of tools, a pack of food, a gauge. Before a
part moves on to the next machine or to the customer, someone checks it. That check is
the inspection, and the place where it happens is the inspection station: a table or a
spot on the conveyor belt, with a camera and good lighting above it, and usually a screen
for a worker, the operator.

Each part gets one of three outcomes:

- **Pass**: the part is fine and moves on.
- **Fail**: the part is bad (torn, a tool missing, a reading out of range). It is taken
  off the line, to be scrapped or repaired. A fail costs money, because a part is thrown
  away or reworked.
- **Unsure**: the check cannot tell. The part is put aside for a person to look at.

Every outcome is also written down, with the part's label (such as `tray-07`), the time,
the photo and what was seen. That list is the inspection log. Factories keep it because
customers and quality rules demand proof that every part was checked, and so that bad
parts can be traced back later.

Simple checks are usually done by fixed camera software ("is there a hole at this
spot?"). This demo is about the checks such software cannot do, the open questions: "is
anything missing from this tray?", "does any of these watches show a different time?"

In this demo, each photo stands for one part, and there is no production line: recording
an outcome means writing one line to the inspection log, and nothing is moved or
scrapped. Claude looks at the photo and decides pass, fail or unsure. A pass or an unsure
is written down straight away. A fail is not: wrongly scrapping a good part costs money,
so the inspection server asks a person first, and this app shows that question as a dialog,
with the photo; your answer then shows in the conversation too. If you agree, the part is
marked as failed. If you say no, or close the
dialog without answering, the part is marked as unsure, to be put aside for a person to
look at, and the log says that Claude called it a fail and what your answer was. Every
part Claude records ends up in the log, and every fail question is logged when it is
asked. You have an hour to answer: an answer that comes later, or after the inspection
server was restarted, records nothing; the window then says so, and you ask again.

![The setup. Left: the inspection station, where no AI runs: a camera above a conveyor belt, and the station computer with the MCP server, which keeps the inspection log. Right: the operator's computer with the desktop app, which talks to the MCP server over the network and to Claude, the AI, on the internet.](docs/setup.svg)

The station computer, the one the camera is plugged into, and the operator's computer
can also be one and the same, and the camera a USB webcam, or the fake camera, which
serves stored photos instead.

## What it does, step by step

1. You type a question and press Enter.
2. The app sends Claude the conversation, and the inspection server's tools: take a photo,
   look closer at part of a photo, record an inspection result.
3. When Claude asks for a tool, the app passes the call on to the inspection server and
   gives the result, photos included, back to Claude. The window shows each step, in
   gray below your question: what Claude asked for, in plain words, and what came back.
   Tick "Show MCP messages" to see the messages themselves as well, as the Model
   Context Protocol sends them between the app and the inspection server: indented, one
   field per line, each message between two thin lines. Where a text holds JSON of its
   own, such as the inspection record, that JSON is shown unpacked, not as one string
   full of escapes. A fail question comes back as the call's result, with the server's
   sealed state (shortened in the window); the dialog shows, and the call goes to the
   server again with your answer and that state.
4. Steps 2 and 3 repeat until Claude answers.

The rules live in the inspection server, not in the app and not in what Claude is told: the
server caps the photo size, refuses zooms too small to show anything but blur, keeps one
record per photo, logs every action, and asks a person before marking a part as
failed. The app only passes the server's question on to you, and your answer back. A refusal from the
server is shown in red, and Claude reads it too.

Each answer ends with what the question cost, and below the conversation the window
shows what the whole conversation cost so far. In our tests, a question with a photo and a few closer looks
cost $0.04 to $0.07 with Claude Opus 5.5 and $0.01 to $0.02 with Claude Sonnet 5.5; a
short follow-up question costs less than a cent. You choose the model below the conversation.
"New conversation" starts over; until then, Claude remembers the earlier questions and
photos, so you can ask "now look closer at the left one".

## Installing

Python 3.13 or later: tested with 3.14; the tests also pass with 3.13. The app was
tested on Linux and Windows; macOS is not tested yet. The commands are for Linux, and
should work the same in the macOS Terminal; for PowerShell, see
[On Windows](#on-windows).

The app and the inspection server are separate programs. The app talks to the server only
over the network, through MCP, even when both run on one computer; it needs no part of
the server installed beside it. So each has a Python environment of its own: the
server's is made as its README describes, and the app's as below. There are two ways to
make the app's environment; use one of them, not both:

- [With a virtual environment](#with-a-virtual-environment), if Python 3.13 or later
  is installed on your computer. The environment is a folder, `.venv`, in this
  repository's folder.
- [With conda](#with-conda), if you use Miniconda or Anaconda, which bring their own
  Python. Conda keeps the environment in a place of its own and you call it by its name,
  `inspection-client`.

### With a virtual environment

In a terminal, in this repository's folder:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest -q
```

The first line makes the folder `.venv`, with a Python environment in it (if
`python3 --version` shows a version older than 3.13, write `python3.14` or `python3.13`
instead of `python3`; on Ubuntu and Debian, it needs `sudo apt install python3-venv`
once); the second activates it; the rest installs the app into it and runs its tests.
**In every new terminal**, activate it again before starting the app, in this
repository's folder:

```
source .venv/bin/activate
```

### With conda

In a terminal, in this repository's folder:

```
conda create -n inspection-client python=3.14
conda activate inspection-client
pip install -e ".[test]"
pytest -q
```

The first line makes a conda environment called `inspection-client`, with Python 3.14 in it; the
second activates it; the rest installs the app into it and runs its tests. The first
time, conda may ask whether you accept the terms of service of Anaconda's package
channels (answer `a` to each question), then `Proceed ([y]/n)?`. **In every new
terminal**, activate it again before starting the app:

```
conda activate inspection-client
```

Activating conda's own `base` environment is not enough: the app is in `inspection-client`.

### What the install adds

The command `inspection-client`, which starts the app. It exists only inside the
environment: in a terminal where it is not active, the answer is "command not found".
The tests use stand-ins for the inspection server and for Claude, so they need no server, no
camera, no key and no internet.

## Your Claude API key

The app talks to Claude through Anthropic's API, which needs an API key, and is paid per
use (see the costs above).

1. Sign in to the Claude Console at platform.claude.com.
2. Under "API keys", create a key, and copy it.
3. In a terminal, make the key file and open it in an editor:

   ```
   mkdir -p ~/.config/anthropic
   nano ~/.config/anthropic/api-key
   ```

4. Paste the key, save with Ctrl+O and Enter, and close the editor with Ctrl+X. Then
   make the file readable for you only:

   ```
   chmod 600 ~/.config/anthropic/api-key
   ```

The app reads the key from this file every time it starts. (If the environment variable
`ANTHROPIC_API_KEY` is set, the app uses that instead.) To stop the key from working,
delete it in the Console; a spending limit for the key's workspace can be set there as
well.

## How to start it

Every terminal below needs an environment active first: for the app, its own, the way
you installed it (`source .venv/bin/activate` in this repository's folder, or
`conda activate inspection-client`); for the inspection server, the server's, as its README describes.

| Your situation | What you start | See |
|---|---|---|
| Try it on one computer, no camera needed | The inspection server with its fake camera, then the app | [Try it on one computer](#try-it-on-one-computer) |
| The camera on one computer, the app on another | The inspection server on the station computer, the app on yours | [The camera on another computer](#the-camera-on-another-computer) |
| Each person logs in with their own name and role, instead of one shared key | A login server, the inspection server with logins, then the app with `--login` | [Logins with roles](#logins-with-roles) |
| You want Claude Code instead of this app | Nothing from this repository | [With Claude Code instead](#with-claude-code-instead) |

## Try it on one computer

Without a camera, the server can use a fake one, which serves stored photos of the demo
scenes (a tool tray, watches, packs, a scale, a gauge), a new one for every photo taken.

**In a first terminal**, with the server's environment active, in the folder
`inspection-mcp-server`, start the inspection server, and leave it running:

```
inspection-server --http
```

(Or start it with a click: `inspection-server-window` opens the server window, as
described in the `inspection-mcp-server` README. The steps below are for the terminal.)

The first time, it lists the cameras it finds and asks you to type the number of one:
type the number of the last entry, "Sample photos, no camera", and press Enter (or that
of a real camera, to use it). The server remembers the choice; to choose again, start it
with `inspection-server --http --choose-camera`. It is ready when it shows "Uvicorn
running on http://127.0.0.1:8000". Above that, it says where its secret key is:
`~/.config/inspection-server/api-key`, made at its first start. The app reads the same
file, so there is nothing to copy on one computer.

**In a second terminal**, with the app's environment active, start the app:

```
inspection-client
```

The status line at the bottom of the window says "Connected" and lists the server's
tools; the live view on the left shows the photo the fake camera will serve next. Ask,
for example: "Take a photo. Is the tool tray complete?" Then ask "Take another photo.
Check that every tool is in the tray; it is part tray-02. Record the result." If Claude
finds a tool missing, the confirmation dialog comes up.

To stop, close the window, and press Ctrl+C in the server's terminal. The photos the
server took are in `inspection-mcp-server/captures/`, its logs in `inspection-mcp-server/logs/`.

## The camera on another computer

The station computer runs the inspection server, as described in the `inspection-mcp-server` README,
section "The camera on one computer, Claude Code on another": choose the camera, start
the server with `--http --host 0.0.0.0`, and copy its key file to the app's computer, to
the same place: `~/.config/inspection-server/api-key`. That section's steps for Claude
Code are not needed here.

On the app's computer, in a terminal with the app's environment active, start the app
with the station computer's address (here 192.168.0.20; on Linux, `hostname -I` on the
station computer shows it):

```
inspection-client --server http://192.168.0.20:8000/mcp
```

If something is wrong, the window says what: the inspection server cannot be reached (is it
running, with `--host 0.0.0.0`, and does a firewall let port 8000 through?), it refused
the key (the key files differ), or there is no inspection server at that address.

## Logins with roles

Instead of one key that everyone shares, each person can log in with their own name.
The inspection server then knows who asks, writes the name into every log line and record,
and lets each person do only what their role allows: a `viewer` may take photos, look
closer and watch the live view; an `inspector` may also record results. The login
happens in the browser, at a login server, which hands the app a token that the
inspection server checks. The `inspection-mcp-server` README, section "Logins with
roles", explains this in more detail; its script `scripts/keycloak.sh` starts a demo login server
([Keycloak](https://www.keycloak.org/), in a container; needs [podman](https://podman.io/))
with two users: `inspector` (password `inspector`) and `viewer` (password `viewer`).
This app is registered there in advance as `inspection-client`, the way an
administrator registers each application that may connect.

On one computer, in three terminals. In the first, in the folder `inspection-mcp-server`, start the
login server:

```
scripts/keycloak.sh
```

It is ready when it shows "Listening on". In a second terminal with the server's
environment active, in the folder `inspection-mcp-server`, start the inspection server with logins
instead of its key:

```
OAUTH_ISSUER=http://localhost:8080/realms/inspection SERVER_URL=http://localhost:8000/mcp \
    inspection-server --http
```

In a third terminal with the app's environment active, start the app:

```
inspection-client --login
```

The app opens the login page in your browser. Log in as `viewer`; the browser says
"Logged in", and the window "Logged in as viewer". Ask, for example, "Take a photo. Is
the tool tray complete? Record it as part tray-01." (The fake camera serves its photos
in turn, the complete tool tray first.) The inspection server refuses to record, with the
reason, shown in red; Claude reads the refusal and tells you. Close the window, start
the app again, and log in as `inspector` (if the login page offers `viewer` again, the
round arrows next to the name start over with another user). Ask "Take a photo. Check
that every tool is in the tray; it is part tray-02. Record the result.": the next photo
shows the tray with its hammer missing, and now the result is recorded, after the
confirmation dialog if Claude finds a tool missing. Every line of
`inspection-mcp-server/logs/audit.log` and every record names the person logged in.

The app keeps the login only while it runs: each start asks again. A login token is
valid for a few minutes (the demo's: 5); the app renews it by itself while it runs, as
long as the login server allows.

**The camera on another computer**: the token travels with every request, so over the
network it should be encrypted (HTTPS); Claude Code, for one, sends logins only over
HTTPS or to `localhost`. On the station computer, start the login server and the
inspection server with certificates, as the `inspection-mcp-server` README describes in
"Logins with roles", "Logins on two computers". Copy `certs/ca.pem` from there to the app's computer, into
the folder you start the app in, and start it with the station computer's address (here
192.168.0.20):

```
inspection-client --login --server https://192.168.0.20:8000/mcp --trust ca.pem
```

`--trust` tells the app to accept certificates signed by the demo's own certificate
authority, `ca.pem`. The browser warns about the private certificate on the login page
once; accept it, or import `ca.pem` into the browser.

If something is wrong, the window says what, for example that the inspection server takes
logins and the app was started without `--login`, or that the address given with
`--server` differs from the one the inspection server was started with (`SERVER_URL`): it
must be the same, letter for letter.

## With Claude Code instead

Claude Code connects to the inspection server directly, so it needs nothing from this
repository: the `inspection-mcp-server` README shows how, in its Quick start and in "Try it on one
computer".

## On Windows

**With a virtual environment**: the same steps in PowerShell, in this repository's
folder:

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest -q
```

If activating fails because running scripts is disabled, allow your own scripts once
with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. In every new PowerShell
window, `cd` to this repository's folder and activate the environment again with
`.venv\Scripts\Activate.ps1`.

**With Miniconda**: open "Anaconda PowerShell Prompt" from the Start menu (not "Anaconda
Prompt", the older Command Prompt), `cd` to this repository's folder, and run the
commands of [With conda](#with-conda) there, unchanged; in every new Anaconda PowerShell
Prompt, `conda activate inspection-client`.

The Claude API key goes into `$HOME\.config\anthropic\api-key`:

```
mkdir $HOME\.config\anthropic
New-Item $HOME\.config\anthropic\api-key
notepad $HOME\.config\anthropic\api-key
```

Paste the key, save, and close Notepad. The second line makes the file, empty, so that
Notepad opens it; given a file that does not exist yet, Notepad would make `api-key.txt`
instead, which the app does not read.

A setting written in front of a command, as in `OAUTH_ISSUER=... inspection-server
--http` in [Logins with roles](#logins-with-roles), is a line of its own in PowerShell,
starting with `$env:`; it holds until the window is closed. A `\` at the end of a line
means the command goes on in the next one. For the inspection server with logins, with the
server's environment active, in the folder `inspection-mcp-server`:

```
$env:OAUTH_ISSUER = 'http://localhost:8080/realms/inspection'
$env:SERVER_URL = 'http://localhost:8000/mcp'
inspection-server --http
```

The login server's script `scripts/keycloak.sh` is a bash script: run it on a Linux
computer (see the `inspection-mcp-server` README, "On Windows").

Checked on Windows Server 2025 with Python 3.14, in a virtual environment and with
Miniconda, from fresh copies of both repositories: the tests; the app with the fake
camera and the key file (the live view, answers, the confirmation dialog); logins with
the login server on a Linux computer, over HTTP and over HTTPS with `--trust` (a viewer
refused recording, an inspector's fail confirmed, the login renewed without asking
again).

## How the tests were checked

The tests were tested too: 12 bugs were planted in the code by hand, one at a time, each
breaking something the app must get right the way a developer could really get it wrong
(No in the fail dialog passed on as yes, the dialog showing the wrong photo, the live view
sent without the key, and so on). At first, 2 were caught by a test that failed for the
right reason with a clear message, and 8 got through with every test still passing. Each
gap now has a test, and all 12 are caught. Two parts that had no tests at all (how
refusals are put into words, and how the start passes the key or login on) were then
covered the same way, with 19 more planted bugs. The bugs and what each one showed:
[docs/test-quality.md](docs/test-quality.md). The inspection server's tests were checked the
same way.

## Files

- `inspection_client/station.py`: the work behind the window: the loop between Claude
  and the inspection server, the costs, and errors in plain words
- `inspection_client/app.py`: the window: live view, conversation, confirmation dialog
- `inspection_client/login.py`: the login in the browser (the MCP SDK does the rest)
- `tests/test_station.py`: the loop, against stand-ins for the inspection server and for
  Claude
- `tests/stand_in_server.py`: the stand-in for the inspection server: the same tools, as
  any inspection server offers them over MCP
- `tests/test_login.py`: the app's part of the login, with a stand-in for the browser
- `tests/test_window.py`: the conversation in the window (MCP messages only when asked
  for, pictures and links, your answer to a fail question), the live view's "try again",
  and the status line checked again once the live view is back
- `tests/test_dialog.py`: the confirmation dialog: Enter never marks a part as failed
- `tests/test_main.py`: the app's start: which key or login, address and certificates
  its parts are given
- `tests/conftest.py`: what several test files share: HTTP to stand-ins, never the
  network
- `docs/setup.svg`: the figure of the setup
- `docs/test-quality.md`: how the tests were checked, with bugs planted on purpose

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
version 2.3.0, the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
version 1.15.0, and [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python) version
6.12.0, its essential modules only (the package `PySide6-Essentials`).

## License

MIT, see [LICENSE](LICENSE).
