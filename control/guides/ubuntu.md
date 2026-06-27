# Operating this Ubuntu 24.04 (GNOME) VM

You are an administrator on this machine. User `user`, password `user` (sudo too).
Tools: left_click, double_click, type_text, key, run_bash.

## Logging in
If the GDM login screen is shown (the name `user` on a dark screen): click the
`user` entry, type `user`, press enter.

## Opening apps (do this, don't guess dock coordinates)
Press the **super** key to open Activities, type the app name, press enter.
Reliable app names to type:
- `Files` — the file manager (GNOME Nautilus); browse/create files & folders
- `Terminal` — a shell terminal
- `Google Chrome` — the web browser
- `Text Editor` — the GNOME text editor (gedit-like)
- `Settings` — system settings
Never hunt for an app by clicking pixels in the dock — `super` + type + enter is
far more reliable.

## Running commands — prefer this for anything scriptable
Use `run_bash` for files, installs, versions, scripting (it runs over SSH as
`user`). For root: `echo user | sudo -S <command>`. Install software with apt:
`echo user | sudo -S apt-get install -y <pkg>`.
Pre-installed: `node`, `npm`, `git`, `yt-dlp`, `google-chrome`.
GUI apps launched from `run_bash` will NOT appear on screen — open those via
Activities (above) instead.

## Web browsing (Google Chrome)
Focus the address bar with **ctrl-l**, type the URL, press enter.
New tab **ctrl-t**, find on page **ctrl-f**, close tab **ctrl-w**, reload **f5**.
If a first-run **"Sign in to Chrome"** dialog covers the window, the address bar
is hidden — click **"Stay signed out"** to dismiss it first. If `ctrl-l` doesn't
visibly focus an address bar after one try, a dialog is blocking it: dismiss the
dialog (or, for a download/fetch, just use `run_bash` with `curl` instead of the
browser). Never press `ctrl-l` repeatedly — if it didn't work once, change tack.

## Filling in web forms (do this to avoid typos)
1. **The first field is usually already focused** when a form/page loads — just
   `type_text` straight away, no click needed.
2. To focus another field, click it **once**, then immediately `type_text`. Do
   NOT click the same field again — if your click didn't land, press **tab** to
   move between fields instead of re-clicking. Never click a field repeatedly.
3. After typing in a field, **tab** to the next one and type; repeat down the form.
4. To replace text already in a field, click it once, **ctrl-a** (select all),
   then type the new value — don't backspace character by character.
5. When all fields are filled, click the form's button (e.g. "Sign in",
   "Save draft", "Create account") **once**, then take a screenshot to confirm.
6. If you see a browser **"Confirm Form Resubmission"** dialog, don't fight it —
   re-navigate to the page with **ctrl-l** + the URL + enter, then refill.

## Filesystem
Home is `/home/user`; the Desktop is `~/Desktop`.

## Recipes for multi-step tasks
- **Write & run a script** (one run_bash call): use a heredoc, then run it, e.g.
  `cat > ~/fib.js <<'EOF'` … `EOF` then `node ~/fib.js`. Capture output in the
  same call so you can report it.
- **Install & verify a package**:
  `echo user | sudo -S apt-get install -y <pkg> && <pkg> --version`
- **Update the system**:
  `echo user | sudo -S apt-get update && echo user | sudo -S apt-get -y upgrade`
- **Fetch a YouTube transcript** (yt-dlp is installed):
  `yt-dlp --skip-download --write-auto-subs --sub-format vtt -o '~/t.%(ext)s' '<url>'`
  then read the `.vtt` with `cat`.
- **Search/read the web**: open Chrome (super → "Google Chrome"), `ctrl-l`, type
  the query or URL, enter; then screenshot to read the page.
- **Read text off the screen**: take a screenshot and read it visually; for file
  contents prefer `run_bash` (`cat <file>`).
- **Navigate Files (Nautilus) to a folder**: **double-click a folder** to open
  it — folder and file cells are grounded, so click them directly. To descend
  several levels, double-click each folder in turn. If you already know the exact
  full path, `ctrl-l` + type the path (or `run_bash` `nautilus <path>`) is also
  reliable — but don't type a path you'd have to guess; just click the folder you
  can see.
- **Act on a file in Files**: click a file **once** to select it (the cell
  highlights). To move the selected file to the Trash, press **Delete** (no
  confirmation; it just leaves the folder). To rename, press **F2**. Avoid
  Shift+Delete unless you mean to permanently erase it.
- **Save a GUI file to an exact path** (GTK Save dialog): typing a full path into
  the "Name" field does NOT change folder. Follow this exact recipe once the Save
  dialog is open — do it once, in order, then stop and screenshot:
  1. Press **ctrl-l** **once** — a location entry appears (or the Name field
     becomes a path entry). Do NOT press ctrl-l again; if you can already type a
     path, skip straight to step 2.
  2. Type the **full path** (e.g. `/home/user/Desktop/poem.txt`).
  3. Press **enter**. In GNOME Text Editor that enter usually saves directly; if a
     **Save** button is still showing, click it **once**.
  4. **Never click Cancel** — Cancel throws away the save and the dialog. If
     something looks wrong, screenshot and re-read the dialog rather than
     cancelling or re-opening it.
  Confirm the file with `run_bash` (`cat <path>`).
