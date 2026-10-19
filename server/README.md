# Inspection MCP server

The MCP server of [Inspection Station MCP](../README.md), for the station computer, the one the camera is plugged into. It lets an AI application take photos with the camera, look closer at part of a photo, and record the result of an inspection, with the rules enforced in the server; a page in the browser shows what the camera sees, live. Claude Code connects to it directly; the desktop app in the folder [`client`](../client/README.md) uses it too.

This README is the reference for installing and running the server. What it is for, the quick start, the AI's answers, the rules and the audit trail are in the [main README](../README.md).

## Contents

- [Installing](#installing)
- [How to start it](#how-to-start-it)
- [Claude Code starts the server](#claude-code-starts-the-server)
- [The server and Claude Code on one computer](#the-server-and-claude-code-on-one-computer)
- [The camera on one computer, Claude Code on another](#the-camera-on-one-computer-claude-code-on-another)
- [Logins with roles](#logins-with-roles)
- [The server window](#the-server-window)
- [The live view](#the-live-view)
- [Choosing a camera](#choosing-a-camera), [the photo size](#the-photo-size), and [if the camera does not open](#if-the-camera-does-not-open)
- [Settings and options](#settings-and-options)
- [On Windows](#on-windows)
- [How the tests were checked](#how-the-tests-were-checked)
- [Files](#files)

## Installing

Python 3.13+. Its automatic tests pass on macOS, but nobody has run it on a Mac with a real camera; it should work there too, since the camera code for it follows the documentation of the libraries it uses. The commands in this README are for Linux, and should work the same in the macOS Terminal; for PowerShell, see [On Windows](#on-windows).

In a terminal, in the `server` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest -q
```

(If `python3 --version` shows a version older than 3.13, write `python3.13` or `python3.14` instead of `python3`; on Ubuntu and Debian, the first line needs the virtual-environment package for your Python version once, such as `sudo apt install python3.13-venv`.) This makes a Python environment of its own in `.venv`, installs the server into it, and runs the tests. The tests use a fake camera with pictures drawn by the test code, so they need no hardware. The install adds the command `inspection-server`, which starts the server, and `inspection-server-window`, a window that starts it for you (see [The server window](#the-server-window)). In every new terminal, activate the environment again before using it:

```bash
source .venv/bin/activate
```

If the install or the tests fail with the newest versions of the packages the server uses, install the exact versions the tests passed with, listed in `constraints.txt`, instead:

```bash
pip install -e ".[test]" -c constraints.txt
```

Keep the `-e` in the install command: with it, the server finds its sample photos in `samples/`, and keeps the photos it takes in `captures/` and its logs in `logs/`, all in this folder (`captures/` and `logs/` are kept out of git). Installed without `-e`, the server has no folder of its own: it stops at its start and says how to remove that copy and install it again. What the logs hold, and how to check them: [The audit trail](../README.md#the-audit-trail) in the main README.

## How to start it

Which way to run it in which situation is in the main README's table, [Other ways to run it](../README.md#other-ways-to-run-it); the sections below have the server's steps for each. If you would rather click than type, [the server window](#the-server-window) starts the server for you.

The desktop app in the folder [`client`](../client/README.md) needs the server started by you, over HTTP, in every way except Claude Code starting it; the app's README has its own steps.

The server never picks a camera by itself. The first time you start it in a terminal, it lists the cameras it finds and asks you to type the number of one. The last entry needs no camera: the sample photos, served by a fake camera from `samples/`, one per photo taken, in name order (see [`samples/README.md`](samples/README.md)). The choice is saved, and later starts use it without asking; see [Choosing a camera](#choosing-a-camera).

## Claude Code starts the server

Here Claude Code starts the server itself, in the background, when Claude Code starts, and stops it when Claude Code ends. You never start the server; you only tell Claude Code once how to start it.

In a terminal, with the environment active (`source .venv/bin/activate` in the `server` folder), go to the folder where you want to use Claude Code (any folder, this one too) and run:

```bash
claude mcp add -s local inspection-server -e CAMERA=fake -- "$(which inspection-server)"
claude
```

The first line registers the server for Claude Code, in this folder only and for you only (`-s local`); it is needed once. The second starts Claude Code. Type `/mcp` in Claude Code: it should show `inspection-server` as connected. Then ask, for example: "Take a photo of the inspection station. Is the tool tray complete?" When Claude proposes a fail, Claude Code asks you in the terminal, as the main README's quick start describes ([With Claude Code](../README.md#with-claude-code)).

With a real camera, choose it and its photo size once, in a terminal with the environment active (see [Choosing a camera](#choosing-a-camera)):

```bash
inspection-server --choose-camera
```

Then register the server as above, but without `-e CAMERA=fake`, which would come before your choice (if it is registered already, remove it first with `claude mcp remove inspection-server -s local`):

```bash
claude mcp add -s local inspection-server -- "$(which inspection-server)"
```

Claude Code then starts the server with the camera you chose. To choose another later, run `inspection-server --choose-camera` again and restart Claude Code.

This way has no live view: the live view needs the server running over HTTP, as in the next section.

## The server and Claude Code on one computer

Here you start the server yourself, over HTTP, and Claude Code connects to it. You need two terminals, both with the environment active.

**Terminal 1**, in the `server` folder, starts the server:

```bash
inspection-server --http
```

The first time, it asks which camera to use, for example:

```text
Which camera should the server use?
  1  Integrated Camera (built in)
  2  USB Webcam (plugged in)
  3  Sample photos, no camera (the fake camera)
Type its number (1 to 3) and press Enter:
```

Type a number and press Enter; without a camera, only the sample photos are listed. For a camera, it then asks for the photo size (see [The photo size](#the-photo-size)); press Enter for the suggested one. The server remembers the choice, so later starts skip these questions. It runs until you stop it with Ctrl+C. It is ready when it shows:

```text
Camera: Sample photos, no camera (the fake camera), chosen now; to choose another: inspection-server --choose-camera
Secret key: /home/<you>/.config/inspection-server/api-key (made now)
Only this computer can connect. To let other computers in, start with --host 0.0.0.0 too.
Live view: http://localhost:8000/live
MCP address: http://localhost:8000/mcp
To connect Claude Code, run this once in the folder where you use it:
  Linux, macOS: claude mcp add -s local --transport http inspection-server http://localhost:8000/mcp --header "Authorization: Bearer $(cat ~/.config/inspection-server/api-key)"
  PowerShell:   claude mcp add -s local --transport http inspection-server http://localhost:8000/mcp --header "Authorization: Bearer $(Get-Content $HOME\.config\inspection-server\api-key)"
...
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Over HTTP, the server accepts only clients that send its **secret key**. At its first start, it makes a key and saves it in the file shown, which only you can read; every later start uses the same file. Nobody has to type the key: Claude Code reads it from that file in the next step.

**Terminal 2**, in the folder where you want to use Claude Code: run the `claude mcp add` line the server showed for your terminal, once, then start Claude Code with `claude`. The main README's quick start, [With Claude Code](../README.md#with-claude-code), has these steps and what to ask. Open `http://localhost:8000/live` in a browser on this computer to watch the camera ([the live view](#the-live-view)). The desktop app connects to the same server without any command: it reads the same key file.

## The camera on one computer, Claude Code on another

The station computer runs the server; the other computer runs Claude Code and needs only Claude Code, not this repository. In the examples, the station computer's address on the network is 192.168.0.20 (the server shows it when it starts).

**On the station computer**, in a terminal, in the `server` folder, after [installing](#installing) and with the environment active:

1. Start the server, and leave it running:

   ```bash
   inspection-server --http --host 0.0.0.0
   ```

   The first time, it asks which camera to use: type its number (see [Choosing a camera](#choosing-a-camera)). `--host 0.0.0.0` lets other computers connect; without it, only this computer can. It is ready when it shows "Uvicorn running on http://0.0.0.0:8000". Above that, it shows where the secret key is (made at the first start), the live view's addresses, and the command for step 3, with this computer's address filled in. If the camera is not there, it stops at once and says why. Over SSH, start it inside `tmux` or `screen`, or it stops when the connection closes. A firewall on this computer must let port 8000 through (on Windows, see [On Windows](#on-windows)).

2. Open `http://localhost:8000/live` in a browser on this computer, and set up the scene while watching it. Before anything else, look at what the camera sees: it can catch people or the room.

**Copy the key file** to the Claude Code computer, to the same place: `~/.config/inspection-server/api-key`. Use `scp`, on whichever computer can log in to the other over SSH:

- If the station computer runs an SSH server, on the Claude Code computer:

  ```bash
  mkdir -p ~/.config/inspection-server
  scp <user>@192.168.0.20:.config/inspection-server/api-key ~/.config/inspection-server/
  ```

- If only the Claude Code computer runs one, on the station computer:

  ```bash
  ssh <user>@<Claude Code computer> mkdir -p .config/inspection-server
  scp ~/.config/inspection-server/api-key <user>@<Claude Code computer>:.config/inspection-server/
  ```

The key only has to be the same in both files. If the Claude Code computer already has a key file, you may instead copy that one to the station computer before the server's first start; the server then uses it.

**On the Claude Code computer**, in a terminal:

3. In the folder where you want to use Claude Code, register the server with the key, once, with the command the server showed for this computer's terminal (here the one for Linux). If a server called `inspection-server` is already registered there, remove it first with `claude mcp remove inspection-server -s local`.

   ```bash
   claude mcp add -s local --transport http inspection-server http://192.168.0.20:8000/mcp \
       --header "Authorization: Bearer $(cat ~/.config/inspection-server/api-key)"
   ```

4. Start Claude Code with `claude` in the same folder; `/mcp` should show `inspection-server` as connected. Ask, for example: "Take a photo of the inspection station. What do you see?" Photos and logs are kept on the station computer, in its `captures/` and `logs/`. If the server shows 401 in its terminal, the two key files differ. To watch the live view from this computer too, open `http://192.168.0.20:8000/live` and paste the key.

Next time, only step 1 on the station computer and `claude` on the other: the key file and the registration stay.

**A new key**: delete the key file on the station computer, start the server again (it makes a new one), copy it to the Claude Code computer again, and register the server there again (remove, then step 3).

**HTTPS.** Over plain HTTP the key travels unencrypted: acceptable on a home network you trust, not on a shared one (the server warns at its start). For HTTPS, on the station computer, make a certificate once and start the server with it:

```bash
scripts/make_certs.sh 192.168.0.20
inspection-server --http --host 0.0.0.0 --tls-cert certs/server.pem --tls-key certs/server.key
```

Copy `certs/ca.pem` to the Claude Code computer (the same way as the key file), use the `https://` addresses the server now shows, in step 3 and for the live view, and start Claude Code with `NODE_EXTRA_CA_CERTS=<path>/ca.pem claude`, so it trusts the certificate. The browser warns about the private certificate once. `ca.pem` belongs to a small certificate authority of this demo; the script deletes its private key once it has signed the certificate, so nobody can use it to vouch for other websites. Running the script again makes a new one: copy the new `ca.pem` to the other computer again.

## Logins with roles

Logins (OAuth) name every person, instead of one key shared by everyone. Each person logs in to a login server in the browser, Claude Code receives a token for this server, and the server checks the token's signature, who issued it and for which server, then reads the person's roles from it. The tests try 26 forged or altered tokens on it (no signature, the algorithm "none", someone else's key or login server, a token for another server, claims edited after signing, and more): all refused. `scripts/keycloak.sh` starts a demo login server ([Keycloak](https://www.keycloak.org/), in a container; needs [podman](https://podman.io/)) with two users: `inspector` (password `inspector`; may record results, and has the role `viewer` too, since the server checks each role on its own) and `viewer` (password `viewer`; may only take photos, look closer and watch the live view). Claude Code is registered there in advance, as an administrator would register each application that may connect, and so is the desktop app (its steps: [Logins with roles](../client/README.md#logins-with-roles) in its README).

On one computer, in three terminals (the first two in the `server` folder, with the environment active):

```bash
scripts/keycloak.sh                       # terminal 1: the login server; ready at "Listening on"
OAUTH_ISSUER=http://localhost:8080/realms/inspection SERVER_URL=http://localhost:8000/mcp \
    inspection-server --http              # terminal 2: the server, with logins instead of the key
claude mcp add -s local --transport http --client-id claude-code --callback-port 33418 \
    inspection-server http://localhost:8000/mcp
claude mcp login inspection-server        # terminal 3: register once, then log in
claude
```

The login opens the browser (`--no-browser` prints the address instead, for a session over SSH). Log in as `inspector` and ask Claude Code to inspect something; every line of `logs/audit.log` and every record now names `inspector`. Log out with `claude mcp logout inspection-server`, and in the browser at `http://localhost:8080/realms/inspection/protocol/openid-connect/logout` (otherwise the login server logs you straight back in as `inspector`). Log in as `viewer`, and asking to record a result is refused by the server, with the reason. Claude Code renews the login by itself while the login server allows it.

The live view page has no login of its own: on the station computer it needs none, and from another computer it takes a pasted login token instead of the key.

**Logins on two computers** (the camera on one, Claude Code on another): Claude Code sends login details only over HTTPS or to `localhost`, so both servers need certificates. On the station computer, with its address on the network (here 192.168.0.20), in two terminals:

```bash
scripts/make_certs.sh 192.168.0.20     # once: a private certificate authority, and a certificate
MCP_SERVER_URL=https://192.168.0.20:8000/mcp scripts/keycloak.sh --https      # terminal 1
SSL_CERT_FILE=certs/ca.pem OAUTH_ISSUER=https://192.168.0.20:8443/realms/inspection \
    SERVER_URL=https://192.168.0.20:8000/mcp \
    inspection-server --http --host 0.0.0.0 --tls-cert certs/server.pem --tls-key certs/server.key  # terminal 2
```

Copy `certs/ca.pem` to the other computer, register the server there as above with `https://192.168.0.20:8000/mcp`, and start Claude Code with `NODE_EXTRA_CA_CERTS=<path>/ca.pem claude`, so it trusts the certificates. The browser warns about the private certificate on the login page once; accept it or import `ca.pem` into the browser. The firewall on the station computer must let ports 8000 and 8443 through.

The login server's administration page (`/admin`, user `admin`) takes a password made new at each start of `scripts/keycloak.sh`, shown in its first line: with `--https`, other computers can reach that page too.

Not demonstrated here, on purpose: logging in once for several servers (single sign-on does this on a real login server), and Claude Code registering itself with the login server (dynamic client registration; most plants register applications by hand).

## The server window

A small window that starts and stops the server over HTTP, as `inspection-server --http` does in a terminal, for people who would rather click than type. The server is the same either way: the window runs that command for you and shows what it prints. Logins and HTTPS are not in the window; for those, start the server in a terminal.

Start it once from a terminal with the environment active:

```bash
inspection-server-window
```

In the window:

- **Camera**: the same list as in the terminal, and the same saved choice (see [Choosing a camera](#choosing-a-camera)). Choose one before the first start. If the camera chosen earlier is not plugged in, the list stays empty until you plug it in and click **Look again**, or choose another; the window never takes another camera by itself.
- **Photo size**: the sizes the camera offers, as in the terminal (see [The photo size](#the-photo-size)). Choosing a camera fills in the suggested size, and saves it; choose another in the list if you like. The sample photos have no size to choose. On Windows, opening the list for the first time takes a few seconds: the window asks the camera which sizes it has.
- **Let other computers connect**: the same as `--host 0.0.0.0`. The window remembers it, in the same settings file as the camera (`"other_computers": true`). On Windows, other computers also need the port opened in the firewall, as in [On Windows](#on-windows).
- **Start** and **Stop**. While the server runs, the box at the bottom shows what it prints: the camera, where the key file is, the addresses of the live view and of the server, and the command that connects Claude Code (select it and press Ctrl+C to copy it). Where those lines mention `--host 0.0.0.0`, the checkbox does the same. Closing the window stops the server too. If the server stops by itself, its last lines in the box say why; a common reason is that port 8000 is taken, for example by a server started in a terminal.
- **Open live view**: opens `http://localhost:8000/live` in your browser.
- **Copy the secret key**: puts the key on the clipboard, for making the key file on another computer. On Linux, the clipboard keeps it only while the window is open.
- **Put a shortcut on the desktop** (Windows and Linux): from then on, start the window with a double click. The shortcut starts the window from this environment; if you delete or move the environment, make the shortcut again.

The window uses Tkinter, the window toolkit that comes with Python from python.org on Windows and macOS, and with Miniconda. Some Linux distributions ship it separately: if the window says that Tkinter is missing, install it for your Python version (on Ubuntu and Debian, such as `sudo apt install python3.13-tk`; the message names the package). The window's automatic tests pass on macOS, but nobody has opened it on a Mac.

On Linux with Miniconda or Anaconda, the window's letters look rough, without smoothing: the Tkinter in Anaconda's own package channel is built that way. The one from the conda-forge channel draws them smoothly. Make the environment from there, then install the server into it, in the `server` folder:

```bash
conda create -n inspection-server -c conda-forge python=3.14 "tk=*=xft*"
conda activate inspection-server
pip install -e ".[test]"
```

`xft` is the build of Tk with smooth letters. If an environment `inspection-server` exists already, give the new one another name, or remove the old one first with `conda env remove -n inspection-server`. Windows is not affected.

## The live view

The page shows what the camera sees, up to five pictures a second, so you can set up a scene without a separate camera program. Below the picture, it shows the photo size and how many pictures a second the camera sends: fewer at larger photo sizes (see [The photo size](#the-photo-size)). Photos go on working while it is open: the server alone opens the camera, and the page and the photos share it. A photo is the first picture that arrives after it was asked for, so it shows the scene as it is then.

- **On the computer the server runs on**: `http://localhost:8000/live`, no key needed. Write `localhost`: under the computer's network address, the server treats the page as coming from another computer.
- **From another computer**: `http://<the server's address>:8000/live`. The page asks for the secret key (show it with `cat ~/.config/inspection-server/api-key` and paste it) and keeps it until the tab is closed.

The page asks for pictures only while its tab is visible, and the server lets go of the camera a minute after the last picture or photo. With the fake camera, the page shows the photo that the next `capture_image` will return.

## Choosing a camera

The server never picks a camera by itself: a person chooses one, once, by typing its number in a list. The server shows the list when it is started in a terminal with `--http` and no camera has been chosen yet (as in [The server and Claude Code on one computer](#the-server-and-claude-code-on-one-computer)). To show it at any time, also to change a choice or to choose before Claude Code starts the server, run:

```bash
inspection-server --choose-camera
```

Alone, this chooses and stops; with `--http` and the other options, it chooses and then starts the server.

Each camera is listed with its maker and model; on Linux (any webcam the system's video drivers support), also whether it is built in or plugged in. The Windows list can also show virtual cameras that other programs install, such as OBS's; leave those out. The last entry, the sample photos, needs no camera. If your camera is missing, plug it in, press Ctrl+C and start again.

The choice is saved in `~/.config/inspection-server/settings.json` (on Windows `$HOME\.config\inspection-server\settings.json`) as the camera's path on Linux, or its name on Windows and macOS (its device path, for two cameras of the same model). Never as its number in the list: numbers change when devices are plugged in. Every start over HTTP shows which camera it uses. If the chosen camera is not there, the server stops at once and says so; it never takes another one instead. Where nobody can answer the list, as when Claude Code starts the server and no camera has been chosen yet, the server stops and says why.

The setting `CAMERA`, if set, comes before the saved choice, for scripts and tests: `CAMERA=fake` for the sample photos, or a real camera, as `python scripts/check_camera.py` lists them (with single quotes, `CAMERA='<the value>'`: a name can contain spaces, and a Windows identifier contains `&`, which the terminal would otherwise take as an instruction of its own). A real camera in `CAMERA` needs its photo size in `CAMERA_SIZE` too, like `CAMERA_SIZE=1920x1080`; the script lists each camera's sizes, and without `CAMERA_SIZE` the server stops and lists them as well. Given the value, the same script takes one test photo, which goes to `captures/`: `python scripts/check_camera.py '<the value>'`, at the suggested size, or at another one given after it, as in `python scripts/check_camera.py '<the value>' 1280x720`.

### The photo size

After a camera, the server lists the photo sizes that camera offers, largest first, and asks for one, for example:

```text
Asking the camera which photo sizes it offers; this can take a few seconds.
Which photo size? Larger photos show more detail when the AI zooms in; the live view then shows fewer pictures a second.
  1  2304x1536
  2  1920x1080  (suggested)
  3  1280x720
  4  640x480
Type its number (1 to 4), or press Enter for 1920x1080:
```

Press Enter for the suggested size, or type the number of another. The size is saved with the camera; `inspection-server --choose-camera` asks for both again. The setting `CAMERA_SIZE`, if set, comes before the saved size.

The suggestion is 1920×1080 (Full HD) if the camera offers it, otherwise the largest size that fits inside 1920×1080. It is not simply the largest size: webcams often offer sizes larger than their sensor really delivers, enlarged from a smaller picture, which only make photos bigger and slower. A webcam tested here offers 2304×1536, for example, but its photos at that size show less detail than at 1920×1080. When in doubt, take a photo at each size with the check script and compare the same detail, enlarged.

What the size changes:

- **Zooms.** The AI is always sent the whole photo at 1280×720 pixels at most, so a larger size costs nothing extra there. But the server keeps the photo at its full size, and `zoom_image` crops that, so a larger photo shows more when the AI looks closer.
- **Pictures a second.** The camera sends its pictures uncompressed, and the cable carries only so many: the webcam tested here sends 10 a second at 1280×720, 5 at 1920×1080 and fewer than 2 at 2304×1536. The live view gets jerkier, and the first photo after the camera was idle takes longer, because the server waits for 20 pictures so that the exposure can settle: about 2 seconds at 10 a second, 13 seconds at 2304×1536. Photos after that take a fraction of a second.

Sizes under 640 pixels across are left out. On Linux, the list is the camera's own. On Windows and macOS, cameras do not report their sizes in the same way, so the server asks the camera for about fifteen common sizes and lists those it gets; a size the camera has but that is not among the common ones is missing. If the camera sends another size than the one chosen, photos are refused with the reason; the server never uses another size instead.

A camera chosen before photo sizes could be chosen is kept: the next start in a terminal asks only for its size. Where nobody can answer, the server stops and says so.

### If the camera does not open

On macOS, the first use asks whether the terminal app may use the camera; if it was refused, allow it in System Settings, Privacy & Security, Camera. On Windows, if the camera does not open, check Settings, Privacy & security, Camera: "Camera access" and "Let desktop apps access your camera" must be on.

Only one program at a time can read a camera. Close any other camera program before starting the server. While the server runs, it holds the camera whenever it is used and for a minute after, so the check script cannot open it then; use the live view instead.

If the camera does not open while you are logged in over SSH: many Linux desktops give the camera only to the person logged in at the screen. Log in at the desktop too, or add yourself to the `video` group (`sudo usermod -aG video $USER`, then log in again).

## Settings and options

The server reads these settings from the environment; on Linux and macOS, write them in front of the command, as in `CAMERA=fake inspection-server --http`; in PowerShell, write each one on a line of its own before the command, as in `$env:CAMERA = 'fake'`:

| Setting | What it does |
|---|---|
| `CAMERA` | If set, used instead of the camera chosen in the list: `fake` (the sample photos) or a real camera, as `scripts/check_camera.py` lists them |
| `CAMERA_SIZE` | If set, used instead of the photo size chosen in the list, like `1920x1080`: one the camera offers, as `scripts/check_camera.py` lists them. Needed with a real camera in `CAMERA` |
| `SAMPLES_DIR` | The photos the fake camera serves (default: `samples/`) |
| `DATA_DIR` | Where photos (`captures/`) and logs (`logs/`) are kept (default: this folder) |
| `API_KEY` | With `--http`: a secret key of your own, at least 32 characters, instead of the key file `~/.config/inspection-server/api-key` |
| `OAUTH_ISSUER` | With `--http`, instead of a key: the login server whose tokens are accepted; an `https://` address, or one on this computer (`localhost`) |
| `SERVER_URL` | With `OAUTH_ISSUER`: this server's address as clients use it; tokens must be issued for it |
| `SSL_CERT_FILE` | When the login server uses a private certificate: the certificate authority to trust (`certs/ca.pem`) |

The options of `inspection-server`:

| Option | What it does |
|---|---|
| (none) | Talk through input and output (stdio), as when Claude Code starts the server |
| `--http` | Serve over HTTP instead, at `http://<host>:<port>/mcp`, with the live view at `/live` |
| `--host` | With `--http`: the address to listen on (default `127.0.0.1`: this computer only; `0.0.0.0`: every network it is on) |
| `--port` | With `--http`: the port (default 8000) |
| `--tls-cert`, `--tls-key` | With `--http`: the certificate and its private key, for HTTPS |
| `--choose-camera` | Show the list of cameras and choose one, and then its photo size, also if they were chosen before; the choice is saved for later starts. Without `--http`, it stops after choosing |

## On Windows

The same steps in PowerShell. Install in a virtual environment of its own:

```powershell
cd <the repository's folder>\server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest -q
```

If activating fails because running scripts is disabled, allow your own scripts once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. In every new PowerShell window, `cd` to the `server` folder first (a PowerShell started as administrator opens in `C:\Windows\System32`), then run `.venv\Scripts\Activate.ps1`.

**With Miniconda** instead of a virtual environment (Miniconda brings its own Python): open "Anaconda PowerShell Prompt" from the Start menu. Not "Anaconda Prompt": that one is the older Command Prompt, where the PowerShell commands below do not work. Make an environment with Python 3.14 and install into it, once:

```powershell
conda create -n inspection-server python=3.14
conda activate inspection-server
cd <the repository's folder>\server
pip install -e ".[test]"
pytest -q
```

The first time, conda may ask whether you accept the terms of service of Anaconda's package channels (answer `a` to each question), then `Proceed ([y]/n)?`. In every new Anaconda PowerShell Prompt, run `conda activate inspection-server` and `cd` to the `server` folder; everything below then works as with the virtual environment.

[Claude Code starts the server](#claude-code-starts-the-server):

```powershell
claude mcp add -s local inspection-server -e "CAMERA=fake" -- (Get-Command inspection-server).Source
claude
```

[The server and Claude Code on one computer](#the-server-and-claude-code-on-one-computer): the PowerShell steps are in the main README's quick start, [On Windows](../README.md#on-windows).

A setting written in front of a command above, as in `OAUTH_ISSUER=<address> SERVER_URL=<address> inspection-server --http`, is a line of its own in PowerShell, starting with `$env:`; it holds until the window is closed:

```powershell
$env:OAUTH_ISSUER = 'http://localhost:8080/realms/inspection'
$env:SERVER_URL = 'http://localhost:8000/mcp'
inspection-server --http
```

Written the Linux way, PowerShell does not take it as a setting: it tries to run it as a command, and fails. Keep the single quotes.

Lines ending in `\` above continue on the next one: in PowerShell write them as one line.

The camera on Windows, Claude Code on another computer: Windows 10 and later include `ssh` and `scp`, for copying the key file. On the Windows side, write the key file's folder as `$HOME\.config\inspection-server`, not with `~`: PowerShell passes `~` to `scp` unchanged, and the copy fails. On the Windows computer, either fetch the key file of the Claude Code computer, before the server's first start:

```powershell
mkdir -Force $HOME\.config\inspection-server
scp <user>@<Claude Code computer>:.config/inspection-server/api-key $HOME\.config\inspection-server\
```

or send the key file the server made to the Claude Code computer:

```powershell
ssh <user>@<Claude Code computer> mkdir -p .config/inspection-server
scp $HOME\.config\inspection-server\api-key <user>@<Claude Code computer>:.config/inspection-server/
```

To let other computers in with `--host 0.0.0.0`, open the port in an administrator PowerShell (also when you tick "Let other computers connect" in [the server window](#the-server-window)): `New-NetFirewallRule -DisplayName "inspection-server" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`. At the server's first start with `--host 0.0.0.0`, Windows may also ask whether Python may use the network: allow it, with the box for the kind of network the computer is on (a home network can be set up as "Public"). If it was refused, Windows blocks Python despite the port rule; delete the blocking rules for Python in "Windows Defender Firewall with Advanced Security", under Inbound Rules.

`scripts/keycloak.sh` and `scripts/make_certs.sh` are bash scripts: run them on a Linux computer and copy `certs/` over; the server itself runs on Windows with the same settings.

Checked on Windows Server 2025 with Python 3.13 and 3.14 (in a virtual environment; 3.14 also with Miniconda) and the fake camera: the tests; the server started over stdio as Claude Code starts it; over HTTP with the key file (made by the server, read by Claude Code on the same computer, copied with `scp` to another computer, whose Claude Code connected with it); the live view in a browser on the same computer without the key and from another computer with it; a key over HTTPS; and logins over HTTPS. Checked on Windows 11 with Miniconda and a real camera, a USB webcam chosen by name: the live view; photos and zooms from Claude Code on another computer; the camera let go after a minute without use; and a fail declined, then confirmed, in Claude Code. Windows lists and opens cameras through DirectShow. The server window, checked on Windows Server 2025 (virtual environment and Miniconda, fake camera): started from PowerShell and from its desktop shortcut, the server started and stopped (also by closing the window), for this computer and for others, the live view opened, the key copied, and a photo taken through MCP with the key.

## How the tests were checked

The tests were tested too: 28 bugs were planted in the code by hand, one at a time, each breaking one of the server's rules the way a developer could really get it wrong (a fail recorded without a person's yes, a thin crop let through, an expired login accepted, a near-miss key let in, and so on). At first, 11 were caught by a test that failed for the right reason with a clear message, and 9 got through with every test still passing; the other 8 were caught, but for the wrong reason, with an unclear message, or by a test that reached out to the network. Each gap now has a test, and all 28 are caught. The bugs, grouped by the rule they break, and what each one showed: [docs/test-quality.md](docs/test-quality.md). The app's tests were checked the same way.

## Files

- `inspection_server/server.py`: the MCP server: tools, rules, logs, key and login checks, the live view
- `inspection_server/camera.py`: the real camera (opened and shared by the server) and the fake one
- `inspection_server/choice.py`: choosing the camera and its photo size in lists, and saving the choice
- `inspection_server/live.html`: the live view page
- `inspection_server/window.py`: the server window
- `tests/test_server.py`: the tests of the tools; `tests/test_http.py`: over HTTP, with the key and with logins, and the live view; `tests/test_camera.py`: the cameras, the real one against a stand-in device; `tests/test_choice.py`: choosing the camera and its photo size, and what the server shows at its start; `tests/test_window.py`: the server window; `tests/test_try_tools.py`: the script that tries the tools
- `samples/`: the photos the fake camera serves
- `scripts/check_camera.py`: lists the cameras with their values for `CAMERA` and their photo sizes, and takes one test photo
- `scripts/try_tools.py`: tries the tools without an AI, with the fake camera, and asks you to confirm the fail it proposes
- `scripts/keycloak.sh` and `keycloak/inspection-realm.json`: the demo login server, its users and roles
- `scripts/make_certs.sh`: certificates for HTTPS between two computers
- `docs/test-quality.md`: how the tests were checked, with bugs planted on purpose
- `constraints.txt`: the exact versions of the packages the tests passed with

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), version 2.3.0.
