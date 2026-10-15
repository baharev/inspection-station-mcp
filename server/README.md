# MCP inspection camera: the server

An MCP server that lets an AI application take photos with a camera, look closer at part
of a photo, and record the result of an inspection. The safety rules are enforced in the
server, not in the prompt. A page in the browser shows what the camera sees, live.

A self-built demonstration of connecting a device to AI models through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP), the standard way to
plug tools, data and devices into AI applications such as Claude Code. It is small on
purpose: about 670 lines of Python and 60 tests. It runs on one computer, or over the
network with a secret key or with logins and roles.

This repository holds the server, a demo login server and a script for HTTPS
certificates. The Claude Code side (a ready-made `.mcp.json` with the fake camera) is in
the companion repository `mcp-client`. To try it, see [Installing](#installing) and
[How to start it](#how-to-start-it).

Author: [Ali Baharev](https://baharev.info/)

## The tools

| Tool | What it does |
|---|---|
| `capture_image` | Takes a photo, capped at 1280×720 pixels, saves it and returns it with an ID such as `20261014-213005`. Changes nothing else. |
| `zoom_image(image_id, left, top, width, height)` | "Look closer": crops a rectangle of an earlier photo (given as fractions of the photo, 0 to 1) and returns it enlarged. Read-only. |
| `record_inspection(image_id, part_id, verdict, findings)` | Adds one record to the inspection log. Verdict `pass`, `fail` or `unsure`. A fail needs a human's yes. |

The photo ID is passed explicitly from one call to the next: the MCP protocol version
used here (2026-07-28) keeps no session between calls.

The zoom tool lets the AI decide for itself that it cannot see well enough and take a
closer look, for example at a small label in a corner. Enlarging shows what the camera
captured more clearly; it cannot add detail the camera did not capture. Very small print
needs a camera closer to the object, so crops smaller than a tenth of the photo are
refused.

## The rules, and where they live

All in the server code (`inspection_camera/server.py`), so they hold whatever the AI is
told or tries:

- **Inputs are checked.** Photo IDs, part labels, verdicts and the length of the findings
  must have the expected form; anything else is refused with a readable reason. A photo
  ID can never point to another file.
- **Limits are in code.** Photo size is capped; zoom rectangles must lie inside the photo
  and not be too small.
- **A human confirms a fail.** In a plant, a failed part would be scrapped, so before a
  fail is recorded the server asks the person at the keyboard through MCP
  ("elicitation"). In this demo, recording only adds a line to the log. If they say no
  or close the question, nothing is written. The question is asked only for a record that
  would otherwise be accepted. In non-interactive use (`claude -p`) the question cannot be
  shown, so a fail is refused there.
- **One record per photo**, so the log never holds two verdicts for the same picture.
- **Everything is audit-logged** with the time and who called: photos, zooms, records,
  refusals, unconfirmed fails and each visit to the live view (`logs/audit.log`). Records
  go to `logs/inspections.jsonl`, one JSON object per line, with the name of whoever
  recorded them.
- **Over the network, nobody gets in without a key or a login**, and a login's roles
  decide which tools its user may call: a viewer may take photos, look closer and watch
  the live view; an inspector may also record results. The server checks this at every
  call; the AI application cannot change it. The one exception: the live view needs no
  key on the camera's own computer.

Tool annotations such as "read-only" are also set, but they are only hints for the
AI application, not protection.

## Installing

Python 3.14, the version tested on Linux and Windows. macOS is not tested yet: the
camera code for it follows the documentation of the libraries it uses, but has not run
on a Mac. The commands in this README are for Linux, and should work the same in the
macOS Terminal; for PowerShell, see [On Windows](#on-windows). Where a command sets the
camera, which PowerShell writes differently, the PowerShell form is shown next to it.

In a terminal, in this repository's folder:

```
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest -q
```

This makes a Python environment of its own in `.venv`, installs the server into it,
and runs the tests. The tests use a fake camera with pictures drawn by the test code, so
they need no hardware. The install adds the command `inspection-camera`, which starts
the server. In every new terminal, activate the environment again before using it:

```
source .venv/bin/activate
```

Keep the `-e` in the install command: with it, the server finds its sample photos in
`samples/`, and keeps the photos it takes in `captures/` and its logs in `logs/`, all in
this folder (`captures/` and `logs/` are kept out of git).

## How to start it

| Your situation | Who starts the server, and how | See |
|---|---|---|
| Try it on one computer, no camera needed | Claude Code starts it by itself; you run no server command | [Try it on one computer](#try-it-on-one-computer) |
| One computer, and you want to watch the live view | You, in a terminal: `inspection-camera --http` | [The live view on one computer](#the-live-view-on-one-computer) |
| The camera on one computer, Claude Code on another | You, on the camera computer: `inspection-camera --http --host 0.0.0.0` | [The camera on one computer, Claude Code on another](#the-camera-on-one-computer-claude-code-on-another) |
| Each person logs in, with a role | You, with a login server | [Logins with roles](#logins-with-roles) |

Without a camera, the server uses a fake one, which serves the `.jpg` photos in
`samples/`, one per photo taken, in name order (see `samples/README.md`). A real camera
is chosen with the setting `CAMERA`; see [Choosing a real camera](#choosing-a-real-camera).

## Try it on one computer

Here Claude Code starts the server itself, in the background, when Claude Code starts,
and stops it when Claude Code ends. You never start the server; you only tell Claude
Code once how to start it.

In a terminal, with the environment active (`source .venv/bin/activate` in this
repository's folder), go to the folder where you want to use Claude Code (any folder,
this one too) and run:

```
claude mcp add -s local inspection-camera -e CAMERA=fake -- "$(which inspection-camera)"
claude
```

The first line registers the server for Claude Code, in this folder only and for you
only (`-s local`); it is needed once. The second starts Claude Code. Type `/mcp` in
Claude Code: it should show `inspection-camera` as connected. Then ask, for example:
"Take a photo of the inspection station. What does the gauge read?"

With a real camera, write `-e 'CAMERA=<the value for CAMERA>'` instead of
`-e CAMERA=fake`, with the single quotes (see
[Choosing a real camera](#choosing-a-real-camera)); this works the same in PowerShell. To
change the setting later, first remove the old one with
`claude mcp remove inspection-camera -s local`.

This way has no live view: the live view needs the server running over HTTP, as in the
next section. (The `mcp-client` repository does the same as the two lines above with a
file, `.mcp.json`: start Claude Code in its folder with this environment active, and
approve the `inspection-camera` server.)

## The live view on one computer

Here you start the server yourself, over HTTP, and Claude Code connects to it. You need
two terminals, both with the environment active.

**Terminal 1**, in this repository's folder, starts the server:

```
inspection-camera --http
```

It runs until you stop it with Ctrl+C. It is ready when it shows:

```
Secret key: /home/<you>/.config/inspection-camera/api-key (made now)
Live view: http://localhost:8000/live
...
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Over HTTP, the server accepts only clients that send its **secret key**. At its first
start, it makes a key and saves it in the file shown, which only you can read; every
later start uses the same file. Nobody has to type the key: Claude Code reads it from
that file in the next step.

**Terminal 2**, in the folder where you want to use Claude Code:

```
claude mcp add -s local --transport http inspection-camera http://localhost:8000/mcp \
    --header "Authorization: Bearer $(cat ~/.config/inspection-camera/api-key)"
claude
```

The first command registers the server with its key (once); the second starts Claude
Code. Ask Claude Code for a photo as above, and open `http://localhost:8000/live` in a
browser on this computer.

With a real camera, start the server in terminal 1 with this instead:

```
CAMERA='<the value for CAMERA>' inspection-camera --http
```

In PowerShell, on Windows, the setting is a line of its own:

```
$env:CAMERA = '<the value for CAMERA>'
inspection-camera --http
```

## About the live view

The page shows what the camera sees, about five pictures a second, so you can set up a
scene without a separate camera program. Photos go on working while it is open: the
server alone opens the camera, and the page and the photos share it. A photo is the
first picture that arrives after it was asked for, so it shows the scene as it is then.

- **On the computer the server runs on**: `http://localhost:8000/live`, no key needed.
  Write `localhost`: under the computer's network address, the server treats the page as
  coming from another computer.
- **From another computer**: `http://<the server's address>:8000/live`. The page asks
  for the secret key (show it with `cat ~/.config/inspection-camera/api-key` and paste
  it) and keeps it until the tab is closed.

The page asks for pictures only while its tab is visible, and the server lets go of the
camera a minute after the last picture or photo. With the fake camera, the page shows
the photo that the next `capture_image` will return.

## Choosing a real camera

The server never picks a camera by itself: the setting `CAMERA` names it. To see what to
set it to, list the cameras, in this repository's folder with the environment active:

```
python scripts/check_camera.py
```

Each camera is listed with its maker and model and, below that, the value for `CAMERA`.
On Linux (any webcam the system's video drivers support), that value is a path under
`/dev/v4l/by-id/`, which stays the same when other devices are plugged in, and the list
also says whether each camera is built in or plugged in. On Windows and macOS (macOS not
tested yet), the value is the camera's name, or, for two cameras of the same model, the
identifier below it in the list. The Windows list can also show virtual cameras that
other programs install, such as OBS's; leave those out. When the server starts, it checks
that `CAMERA` names a camera that is there (on Windows and macOS, exactly one), and
otherwise stops at once with the reason. On macOS, the first use asks whether the terminal
app may use the camera; if it was refused, allow it in System Settings, Privacy &
Security, Camera. On Windows, if the camera does not open, check Settings, Privacy &
security, Camera: "Camera access" and "Let desktop apps access your camera" must be on.

Then take one test photo, which goes to `captures/` (look at it: a camera can catch
people or the room):

```
python scripts/check_camera.py '<the value for CAMERA>'
```

Keep the single quotes, here and wherever `CAMERA` is set: a name can contain spaces, and
a Windows identifier contains `&`, which the terminal would otherwise take as an
instruction of its own. They work the same in Linux terminals and in PowerShell.

Only one program at a time can read a camera. Close any other camera program before
starting the server. While the server runs, it holds the camera whenever it is used and
for a minute after, so the check script cannot open it then; use the live view instead.

If the camera does not open while you are logged in over SSH: many Linux desktops give
the camera only to the person logged in at the screen. Log in at the desktop too, or add
yourself to the `video` group (`sudo usermod -aG video $USER`, then log in again).

## The camera on one computer, Claude Code on another

The camera computer runs the server; the other computer runs Claude Code and needs
only Claude Code, not this repository. In the examples, the camera computer's address on
the network is 192.168.0.20 (on Linux, `hostname -I` shows it).

**On the camera computer**, in a terminal, in this repository's folder, after
[installing](#installing) and with the environment active:

1. Choose the camera and take one test photo, as in
   [Choosing a real camera](#choosing-a-real-camera). Look at the photo (in
   `captures/`) before going on.

2. Start the server, and leave it running:

   ```
   CAMERA='<the value for CAMERA>' inspection-camera --http --host 0.0.0.0
   ```

   In PowerShell, on Windows, the setting is a line of its own:

   ```
   $env:CAMERA = '<the value for CAMERA>'
   inspection-camera --http --host 0.0.0.0
   ```

   `--host 0.0.0.0` lets other computers connect; without it, only this computer can.
   It is ready when it shows "Uvicorn running on http://0.0.0.0:8000"; its first line
   says where the secret key is (made at the first start). If the camera is not there,
   it stops at once and says why. Over SSH, start it inside `tmux` or `screen`, or it
   stops when the connection closes. A firewall on this computer must let port 8000
   through (on Windows, see [On Windows](#on-windows)).

3. Open `http://localhost:8000/live` in a browser on this computer, and set up the scene
   while watching it.

**Copy the key file** to the Claude Code computer, to the same place:
`~/.config/inspection-camera/api-key`. Use `scp`, on whichever computer can log in to
the other over SSH:

- If the camera computer runs an SSH server, on the Claude Code computer:

  ```
  mkdir -p ~/.config/inspection-camera
  scp <user>@192.168.0.20:.config/inspection-camera/api-key ~/.config/inspection-camera/
  ```

- If only the Claude Code computer runs one, on the camera computer:

  ```
  ssh <user>@<Claude Code computer> mkdir -p .config/inspection-camera
  scp ~/.config/inspection-camera/api-key <user>@<Claude Code computer>:.config/inspection-camera/
  ```

The key only has to be the same in both files. If the Claude Code computer already has a
key file, you may instead copy that one to the camera computer before the server's first
start; the server then uses it.

**On the Claude Code computer**, in a terminal:

4. In the folder where you want to use Claude Code, register the server with the key,
   once. If a server called `inspection-camera` is already registered there, remove it
   first with `claude mcp remove inspection-camera -s local`.

   ```
   claude mcp add -s local --transport http inspection-camera http://192.168.0.20:8000/mcp \
       --header "Authorization: Bearer $(cat ~/.config/inspection-camera/api-key)"
   ```

5. Start Claude Code with `claude` in the same folder; `/mcp` should show
   `inspection-camera` as connected. Ask, for example: "Take a photo of the inspection
   station. What do you see?" Photos and logs are kept on the camera computer, in its
   `captures/` and `logs/`. If the server shows 401 in its terminal, the two key files
   differ. To watch the live view from this computer too, open
   `http://192.168.0.20:8000/live` and paste the key.

Next time, only step 2 on the camera computer and `claude` on the other: the key file and
the registration stay.

**A new key**: delete the key file on the camera computer, start the server again (it
makes a new one), copy it to the Claude Code computer again, and register the server
there again (remove, then step 4).

**HTTPS.** Over plain HTTP the key travels unencrypted: acceptable on a home network you
trust, not on a shared one. For HTTPS, on the camera computer, make a certificate once
and start the server with it:

```
scripts/make_certs.sh 192.168.0.20
CAMERA='<the value for CAMERA>' inspection-camera --http --host 0.0.0.0 \
    --tls-cert certs/server.pem --tls-key certs/server.key
```

(In PowerShell: set `$env:CAMERA` first, as in step 2, and write the command on one line.)

Copy `certs/ca.pem` to the Claude Code computer (as the key file), write `https://` in
step 4 and in the live view's address, and start Claude Code with
`NODE_EXTRA_CA_CERTS=<path>/ca.pem claude`, so it trusts the certificate. The browser
warns about the private certificate once.

## Logins with roles

Logins (OAuth) name every person, instead of one key shared by everyone. Each person
logs in to a login server in the browser, Claude Code receives a token for this server,
and the server checks the token's signature, who issued it and for which server, then
reads the person's roles from it. `scripts/keycloak.sh` starts a demo login server
([Keycloak](https://www.keycloak.org/), in a container; needs
[podman](https://podman.io/)) with two users: `inspector` (password `inspector`; may
record results) and `viewer` (password `viewer`; may only take photos, look closer and
watch the live view). Claude Code is registered there in advance, as an administrator
would register each application that may connect.

On one computer, in three terminals (the first two in this repository's folder, with
the environment active):

```
scripts/keycloak.sh                       # terminal 1: the login server; ready at "Listening on"
OAUTH_ISSUER=http://localhost:8080/realms/inspection SERVER_URL=http://localhost:8000/mcp \
    inspection-camera --http              # terminal 2: the server, with logins instead of the key
claude mcp add -s local --transport http --client-id claude-code --callback-port 33418 \
    inspection-camera http://localhost:8000/mcp
claude mcp login inspection-camera        # terminal 3: register once, then log in
claude
```

The login opens the browser (`--no-browser` prints the address instead, for a session
over SSH). Log in as `inspector` and ask Claude Code to inspect something; every line of
`logs/audit.log` and every record now names `inspector`. Log out with `claude mcp logout
inspection-camera`, and in the browser at
`http://localhost:8080/realms/inspection/protocol/openid-connect/logout` (otherwise the
login server logs you straight back in as `inspector`). Log in as `viewer`, and asking
to record a result is refused by the server, with the reason. Claude Code renews the
login by itself while the login server allows it.

The live view page has no login of its own: on the camera's computer it needs none, and
from another computer it takes a pasted login token instead of the key.

**Logins on two computers** (the camera on one, Claude Code on another): Claude Code
sends login details only over HTTPS or to `localhost`, so both servers need
certificates. On the camera computer, with its address on the network (here
192.168.0.20), in two terminals:

```
scripts/make_certs.sh 192.168.0.20     # once: a private certificate authority, and a certificate
MCP_SERVER_URL=https://192.168.0.20:8000/mcp scripts/keycloak.sh --https      # terminal 1
SSL_CERT_FILE=certs/ca.pem OAUTH_ISSUER=https://192.168.0.20:8443/realms/inspection \
    SERVER_URL=https://192.168.0.20:8000/mcp CAMERA='<the value for CAMERA>' \
    inspection-camera --http --host 0.0.0.0 --tls-cert certs/server.pem --tls-key certs/server.key  # terminal 2
```

Copy `certs/ca.pem` to the other computer, register the server there as above with
`https://192.168.0.20:8000/mcp`, and start Claude Code with
`NODE_EXTRA_CA_CERTS=<path>/ca.pem claude`, so it trusts the certificates. The browser
warns about the private certificate on the login page once; accept it or import
`ca.pem` into the browser. The firewall on the camera computer must let ports 8000 and
8443 through.

Not demonstrated here, on purpose: logging in once for several servers (single sign-on
does this on a real login server), and Claude Code registering itself with the login
server (dynamic client registration; most plants register applications by hand).

## Settings and options

The server reads these settings from the environment; on Linux and macOS, write them in
front of the command, as in `CAMERA=fake inspection-camera --http`; in PowerShell, write
each one on a line of its own before the command, as in `$env:CAMERA = 'fake'`:

| Setting | What it does |
|---|---|
| `CAMERA` | `fake` (the default) or a real camera, as `scripts/check_camera.py` lists them |
| `SAMPLES_DIR` | The photos the fake camera serves (default: `samples/`) |
| `DATA_DIR` | Where photos (`captures/`) and logs (`logs/`) are kept (default: this folder) |
| `API_KEY` | With `--http`: a secret key of your own, at least 32 characters, instead of the key file `~/.config/inspection-camera/api-key` |
| `OAUTH_ISSUER` | With `--http`, instead of a key: the login server whose tokens are accepted |
| `SERVER_URL` | With `OAUTH_ISSUER`: this server's address as clients use it; tokens must be issued for it |
| `SSL_CERT_FILE` | When the login server uses a private certificate: the certificate authority to trust (`certs/ca.pem`) |

The options of `inspection-camera`:

| Option | What it does |
|---|---|
| (none) | Talk through input and output (stdio), as when Claude Code starts the server |
| `--http` | Serve over HTTP instead, at `http://<host>:<port>/mcp`, with the live view at `/live` |
| `--host` | With `--http`: the address to listen on (default `127.0.0.1`: this computer only; `0.0.0.0`: every network it is on) |
| `--port` | With `--http`: the port (default 8000) |
| `--tls-cert`, `--tls-key` | With `--http`: the certificate and its private key, for HTTPS |

## On Windows

The same steps in PowerShell. Install in a virtual environment of its own:

```
cd <this repository's folder>
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest -q
```

If activating fails because running scripts is disabled, allow your own scripts once
with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. In every new PowerShell
window, `cd` to the repository's folder first (a PowerShell started as administrator
opens in `C:\Windows\System32`), then run `.venv\Scripts\Activate.ps1`.

**With Miniconda** instead of a virtual environment (Miniconda brings its own Python):
open "Anaconda PowerShell Prompt" from the Start menu. Not "Anaconda Prompt": that one
is the older Command Prompt, where the PowerShell commands below do not work. Make an
environment with Python 3.14 and install into it, once:

```
conda create -n mcp python=3.14
conda activate mcp
cd <this repository's folder>
pip install -e ".[test]"
pytest -q
```

The first time, conda asks whether you accept the terms of service of Anaconda's package
channels (three questions; answer `a` to each), then `Proceed ([y]/n)?`. In every new
Anaconda PowerShell Prompt, run `conda activate mcp` and `cd` to the repository's folder;
everything below then works as with the virtual environment.

Try it on one computer (Claude Code starts the server):

```
claude mcp add -s local inspection-camera -e "CAMERA=fake" -- (Get-Command inspection-camera).Source
claude
```

The live view on one computer: in window 1, start the server; in window 2, register it
with the key file (`$HOME\.config\inspection-camera\api-key`) and start Claude Code:

```
inspection-camera --http
```

```
claude mcp add -s local --transport http inspection-camera http://localhost:8000/mcp --header "Authorization: Bearer $(Get-Content $HOME\.config\inspection-camera\api-key)"
claude
```

A setting written in front of a command above, as in
`CAMERA='<the value for CAMERA>' inspection-camera --http`, is a line of its own in
PowerShell, starting with `$env:`; it holds until the window is closed:

```
$env:CAMERA = '<the value for CAMERA>'
inspection-camera --http --host 0.0.0.0
```

Written the Linux way, PowerShell does not take it as a setting: it tries to run it as a
command, and fails with an error about `&` or about a module that could not be loaded.
Keep the single quotes (see [Choosing a real camera](#choosing-a-real-camera)).

Lines ending in `\` above continue on the next one: in PowerShell write them as one
line.

The camera on Windows, Claude Code on another computer: Windows 10 and later include
`ssh` and `scp`, for copying the key file. On the Windows side, write the key file's
folder as `$HOME\.config\inspection-camera`, not with `~`: PowerShell passes `~` to `scp`
unchanged, and the copy fails. On the Windows computer, either fetch the key file of the
Claude Code computer, before the server's first start:

```
mkdir -Force $HOME\.config\inspection-camera
scp <user>@<Claude Code computer>:.config/inspection-camera/api-key $HOME\.config\inspection-camera\
```

or send the key file the server made to the Claude Code computer:

```
ssh <user>@<Claude Code computer> mkdir -p .config/inspection-camera
scp $HOME\.config\inspection-camera\api-key <user>@<Claude Code computer>:.config/inspection-camera/
```

To let other computers in with `--host 0.0.0.0`, open the port in an administrator
PowerShell:
`New-NetFirewallRule -DisplayName "inspection-camera" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`.
At the server's first start with `--host 0.0.0.0`, Windows may also ask whether Python
may use the network: allow it, with the box for the kind of network the computer is on
(a home network can be set up as "Public"). If it was refused, Windows blocks Python
despite the port rule; delete the blocking rules for Python in "Windows Defender
Firewall with Advanced Security", under Inbound Rules.

`scripts/keycloak.sh` and `scripts/make_certs.sh` are bash scripts: run them on a Linux
computer and copy `certs/` over; the server itself runs on Windows with the same
settings.

Checked on Windows Server 2025 with Python 3.14 (in a virtual environment, and with
Miniconda) and the fake camera: the tests; the
server started over stdio as Claude Code starts it; over HTTP with the key file (made by
the server, read by Claude Code on the same computer, copied with `scp` to another
computer, whose Claude Code connected with it); the live view in a browser on the same
computer without the key and from another computer with it; a key over HTTPS; and
logins over HTTPS. Checked on Windows 11 with Miniconda and a real camera, a USB webcam
chosen by name: the live view; photos and zooms from Claude Code on another computer; the
camera let go after a minute without use; and a fail declined, then confirmed, in Claude
Code. Windows lists and opens cameras through DirectShow.

## Files

- `inspection_camera/server.py`: the MCP server: tools, rules, logs, key and login
  checks, the live view
- `inspection_camera/camera.py`: the real camera (opened and shared by the server) and
  the fake one
- `inspection_camera/live.html`: the live view page
- `tests/test_server.py`: the tests of the tools; `tests/test_http.py`: over HTTP, with
  the key and with logins, and the live view; `tests/test_camera.py`: the cameras, the
  real one against a stand-in device
- `samples/`: the photos the fake camera serves
- `scripts/check_camera.py`: lists the cameras, and takes one test photo
- `scripts/keycloak.sh` and `keycloak/inspection-realm.json`: the demo login server, its
  users and roles
- `scripts/make_certs.sh`: certificates for HTTPS between two computers

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
version 2.3.0.

## License

MIT, see [LICENSE](LICENSE).
