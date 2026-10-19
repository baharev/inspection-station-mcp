"""A window that starts and stops the server, for people who would rather click than type.

    inspection-server-window

The window runs the command a person would type, inspection-server --http, as a separate
program, and shows what it says; Stop ends that program. So the server is the same with
or without the window, and a computer without a screen never needs the window. Its
choices go into the same settings file as the terminal's (choice.py): the camera, the
size of its photos, and whether other computers may connect (the server's --host
0.0.0.0). Logins and HTTPS stay on the command line.
"""

import contextlib
import hashlib
import os
import queue
import subprocess
import sys
import sysconfig
import threading
import traceback
import webbrowser
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    HAVE_TK = True
except ImportError:   # Linux distributions ship it separately; main() says so
    HAVE_TK = False

from inspection_server import choice as camera_choice
from inspection_server.camera import CameraError, camera_sizes, size_text, suggested_size

PORT = 8000
# The same file as in server.py, which is not imported here: it would load the whole server.
KEY_FILE = Path.home() / ".config" / "inspection-server" / "api-key"
OTHER_COMPUTERS = "other_computers"   # the checkbox, as kept in the settings file
NAME = "inspection-server-window"
TITLE = "Inspection server"
# On Windows, no console window for the programs the window starts.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def server_command(other_computers: bool) -> list[str]:
    """What Start runs: the server over HTTP, with the Python this window runs on."""
    command = [sys.executable, "-u", "-m", "inspection_server.server", "--http",
               "--port", str(PORT)]
    return command + (["--host", "0.0.0.0"] if other_computers else [])


def server_environment() -> dict:
    """The server's settings: this window's, except a CAMERA or CAMERA_SIZE left over from
    a terminal, which would come before the camera and size chosen in the window."""
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    environment.pop("CAMERA", None)
    environment.pop("CAMERA_SIZE", None)
    return environment


def secret_key() -> str | None:
    """The key clients need, as the server takes it: API_KEY if set, else the key file's."""
    if key := os.environ.get("API_KEY", "").strip():
        return key
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def window_program() -> list[str]:
    """How a shortcut starts this window: the program pip made, else Python with this module."""
    program = Path(sysconfig.get_path("scripts")) / (NAME + ".exe" if sys.platform == "win32"
                                                     else NAME)
    if program.exists():
        return [str(program)]
    python = Path(sys.executable)
    if sys.platform == "win32" and python.with_name("pythonw.exe").exists():
        python = python.with_name("pythonw.exe")   # no console window
    return [str(python), "-m", "inspection_server.window"]


def desktop_entry(program: list[str]) -> str:
    """A Linux desktop launcher for the window (freedesktop.org's .desktop format)."""
    def quoted(arg: str) -> str:
        arg = arg.replace("%", "%%")
        if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
            return arg
        return '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={TITLE}\nComment=Starts and stops the inspection server\n"
            f"Exec={' '.join(quoted(arg) for arg in program)}\n"
            "Icon=camera-web\nTerminal=false\n")


def make_shortcut() -> Path:
    """Puts a shortcut to the window on the desktop (Windows and Linux) and says where."""
    program = window_program()
    if sys.platform == "win32":
        # PowerShell finds the desktop (also one moved into OneDrive) and makes the .lnk;
        # the values go in as environment variables, so no quoting can go wrong.
        script = ("$p = Join-Path ([Environment]::GetFolderPath('Desktop')) "
                  f"'{TITLE}.lnk'; "
                  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p); "
                  "$s.TargetPath = $env:SHORTCUT_TARGET; $s.Arguments = $env:SHORTCUT_ARGS; "
                  "$s.WorkingDirectory = $HOME; "
                  "$s.Description = 'Starts and stops the inspection server'; "
                  "$s.Save(); $p")
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, creationflags=NO_WINDOW,
            env=dict(os.environ, SHORTCUT_TARGET=program[0],
                     SHORTCUT_ARGS=subprocess.list2cmdline(program[1:])))
        if done.returncode != 0:
            raise OSError(done.stderr.strip() or "PowerShell could not make the shortcut")
        return Path(done.stdout.strip())
    try:
        desktop = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                                 text=True).stdout.strip()
    except OSError:
        desktop = ""
    path = Path(desktop or Path.home() / "Desktop") / f"{NAME}.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry(program), encoding="utf-8")
    path.chmod(0o755)
    # A launcher on the desktop starts without a warning only if it is marked as trusted:
    # GNOME's mark, and Xfce's (the file's checksum, so a changed file is not trusted).
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    for mark, value in (("trusted", "true"), ("xfce-exe-checksum", checksum)):
        with contextlib.suppress(OSError):
            subprocess.run(["gio", "set", str(path), f"metadata::{mark}", value],
                           capture_output=True)
    return path


class Window:
    def __init__(self, root: "tk.Tk"):
        self.root = root
        self.process: subprocess.Popen[str] | None = None   # the server, while it runs
        self.port_taken = False                              # it said its port is taken
        # What it says, from the thread that reads it (None: it ended):
        self.lines: queue.Queue[tuple[subprocess.Popen[str], str | None]] = queue.Queue()
        self.entries: list[tuple[str, str]] = []             # the camera list, as (setting, name)
        self.sizes: list[tuple[int, int]] | None = None      # the camera's photo sizes, once listed
        root.title(TITLE)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame = ttk.Frame(root, padding=12)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

        ttk.Label(frame, text="Camera:").grid(row=0, column=0, sticky="w")
        self.camera = ttk.Combobox(frame, state="readonly", width=50)
        self.camera.grid(row=0, column=1, sticky="ew", padx=6)
        self.camera.bind("<<ComboboxSelected>>", self.camera_chosen)
        self.look_again = ttk.Button(frame, text="Look again", command=self.find_cameras)
        self.look_again.grid(row=0, column=2)

        ttk.Label(frame, text="Photo size:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        # The sizes are listed when the list opens: on Windows that opens the camera.
        self.size = ttk.Combobox(frame, state="readonly", width=24, postcommand=self.list_sizes)
        self.size.grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        self.size.bind("<<ComboboxSelected>>", self.size_chosen)

        settings = camera_choice.read_settings()
        self.others = tk.BooleanVar(value=settings.get(OTHER_COMPUTERS) is True)
        self.others_box = ttk.Checkbutton(
            frame, text="Let other computers connect", variable=self.others,
            command=lambda: camera_choice.write_settings({OTHER_COMPUTERS: self.others.get()}))
        self.others_box.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.start = ttk.Button(frame, text="Start", command=self.start_or_stop)
        self.start.grid(row=3, column=0, sticky="w", pady=12)
        self.state = ttk.Label(frame, text="Stopped.")
        self.state.grid(row=3, column=1, columnspan=2, sticky="w", padx=6)

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="w")
        self.live = ttk.Button(buttons, text="Open live view", command=lambda:
                               webbrowser.open(f"http://localhost:{PORT}/live"))
        self.live.pack(side="left")
        ttk.Button(buttons, text="Copy the secret key", command=self.copy_key).pack(
            side="left", padx=6)
        if sys.platform in ("win32", "linux"):   # macOS: not tested yet
            ttk.Button(buttons, text="Put a shortcut on the desktop",
                       command=self.shortcut).pack(side="left")
        self.note = ttk.Label(frame, text="", wraplength=640, justify="left")
        self.note.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="What the server says:").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.output = tk.Text(frame, height=14, width=90, wrap="word", font="TkFixedFont",
                              state="disabled")
        self.output.grid(row=7, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=self.output.yview)
        scrollbar.grid(row=7, column=3, sticky="ns")
        self.output["yscrollcommand"] = scrollbar.set
        self.output.bind("<1>", lambda event: self.output.focus_set())   # for Ctrl+C

        self.find_cameras()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.show_output)

    def find_cameras(self) -> None:
        """Fills the camera list, with the camera chosen earlier selected if it is there."""
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            self.entries = camera_choice.menu_entries()
        finally:
            self.root.config(cursor="")
        self.camera["values"] = [name for _, name in self.entries]
        devices = [device for device, _ in self.entries]
        chosen = camera_choice.saved()
        self.sizes = None
        self.size["values"] = []
        self.size.set(size_text(chosen.size) if chosen and chosen.size else "")
        if chosen and chosen.device in devices:
            self.camera.current(devices.index(chosen.device))
            self.note["text"] = ("" if chosen.size or chosen.device == camera_choice.FAKE
                                 else "Choose a photo size, then click Start.")
        else:   # never another camera in its place
            self.camera.set("")
            self.size.set("")
            self.note["text"] = (
                f"The camera chosen earlier, {chosen.name}, cannot be found. Is it plugged in? "
                "Then click Look again. Or choose another." if chosen else
                "Choose a camera, then click Start.")
        self.update_buttons()

    def camera_chosen(self, event=None) -> None:
        """Saves the camera with its suggested photo size, which the size list can change."""
        device, name = self.entries[self.camera.current()]
        self.sizes = None
        self.size["values"] = []
        self.size.set("")
        self.note["text"] = ""
        size = None
        if device != camera_choice.FAKE and (sizes := self.list_sizes()):
            size = suggested_size(sizes)
            self.size.current(sizes.index(size))
            self.note["text"] = (f"Photo size {size_text(size)} suggested: larger photos show "
                                 "more detail when the AI zooms in, but the live view shows "
                                 "fewer pictures a second. Change it in the list if you like.")
        camera_choice.save(camera_choice.Choice(device, name, "", size))
        self.update_buttons()

    def list_sizes(self) -> list[tuple[int, int]] | None:
        """Lists the chosen camera's photo sizes, once; None if they cannot be read."""
        if self.sizes is not None:
            return self.sizes
        device = self.entries[self.camera.current()][0]
        if device == camera_choice.FAKE:
            return None
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            sizes = camera_sizes(device)
        except CameraError as err:
            self.note["text"] = str(err)
            return None
        finally:
            self.root.config(cursor="")
        self.sizes = sizes
        suggested = suggested_size(sizes)
        shown = self.size.get()
        self.size["values"] = [size_text(s) + (" (suggested)" if s == suggested else "")
                               for s in sizes]
        self.size.set(shown)
        return sizes

    def size_chosen(self, event=None) -> None:
        device, name = self.entries[self.camera.current()]
        assert self.sizes is not None   # a size is chosen from the listed ones
        size = self.sizes[self.size.current()]
        camera_choice.save(camera_choice.Choice(device, name, "", size))
        self.note["text"] = ""
        self.update_buttons()

    def update_buttons(self) -> None:
        running = self.process is not None
        camera = self.camera.current()
        fake = camera >= 0 and self.entries[camera][0] == camera_choice.FAKE
        ready = camera >= 0 and (fake or bool(self.size.get()))
        self.start.config(text="Stop" if running else "Start",
                          state="normal" if running or ready else "disabled")
        self.camera.config(state="disabled" if running else "readonly")
        self.size.config(state="disabled" if running or camera < 0 or fake else "readonly")
        for widget in (self.look_again, self.others_box):
            widget.config(state="disabled" if running else "normal")
        self.live.config(state="normal" if running else "disabled")

    def start_or_stop(self) -> None:
        if self.process:
            self.stop()
            return
        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        self.output.config(state="disabled")
        self.note["text"] = ""
        try:
            # No input: the server must never wait for an answer in a terminal nobody sees.
            self.process = subprocess.Popen(
                server_command(self.others.get()), env=server_environment(),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        except OSError as err:
            self.state["text"] = f"The server could not be started: {err}"
            return
        threading.Thread(target=self.read_output, args=(self.process,), daemon=True).start()
        self.state["text"] = "Starting…"
        self.port_taken = False
        self.update_buttons()

    def read_output(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None   # started with stdout=PIPE
        for line in process.stdout:
            self.lines.put((process, line))
        self.lines.put((process, None))   # it ended

    def show_output(self) -> None:
        """Shows what the server said since the last look; runs ten times a second."""
        while not self.lines.empty():
            process, line = self.lines.get()
            if process is not self.process:
                continue   # one stopped from the window
            if line is None:
                process.wait()
                self.process = None
                self.state["text"] = (
                    f"The server stopped: another program already uses port {PORT}. Is the "
                    "server running already, from a terminal or another window?"
                    if self.port_taken else "The server stopped. Its last messages say why.")
                self.output.see("end")
                self.update_buttons()
                continue
            self.output.config(state="normal")
            self.output.insert("end", line)
            self.output.config(state="disabled")
            if "error while attempting to bind" in line:   # uvicorn's words
                self.port_taken = True
            if "Uvicorn running on" in line:
                self.output.see("1.0")   # its first lines: where to find it, how to connect
                self.state["text"] = ("Running. Other computers can connect too, with the "
                                      "secret key." if self.others.get() else
                                      "Running. Only this computer can connect.")
        self.root.after(100, self.show_output)

    def stop(self) -> None:
        process, self.process = self.process, None
        assert process is not None   # called only while it runs
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        self.state["text"] = "Stopped."
        self.update_buttons()

    def copy_key(self) -> None:
        key = secret_key()
        if not key:
            self.note["text"] = ("There is no secret key yet: the server makes it at its "
                                 "first start. Click Start first.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        self.note["text"] = ("The secret key is copied. Paste it into the key file on the "
                             "other computer, as the README says."
                             + (" Keep this window open until then: on Linux, what it "
                                "copied is gone when it closes." if sys.platform == "linux"
                                else ""))

    def shortcut(self) -> None:
        try:
            path = make_shortcut()
        except OSError as err:
            self.note["text"] = f"No shortcut made: {err}"
            return
        self.note["text"] = f'The shortcut "{TITLE}" is on the desktop now ({path}).'

    def close(self) -> None:
        if self.process:
            self.stop()
        self.root.destroy()


def show_error(kind, error, trace) -> None:
    """Shows an unexpected error in a message box: on Windows there is no console for it."""
    messagebox.showerror(TITLE, "".join(traceback.format_exception(kind, error, trace)))


def main() -> None:
    if not HAVE_TK:
        sys.exit("This Python has no Tkinter, which the window needs. On Ubuntu and Debian: "
                 f"sudo apt install python{sys.version_info.major}.{sys.version_info.minor}-tk")
    if sys.platform == "win32":   # sharp text on screens scaled above 100 %
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.report_callback_exception = show_error
    try:
        Window(root)
    except Exception:
        show_error(*sys.exc_info())
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
