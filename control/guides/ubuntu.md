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

## Filling in web forms (do this to avoid typos and missed clicks)
1. To fill the first field: `type_text`, then CHECK the next screenshot — if
   your text did **not** appear in the field, the field wasn't focused: click
   it **once** and type again. Never submit a form without seeing your text in
   the fields on screen.
2. To focus another field, click it **once**, then immediately `type_text`. Do
   NOT click the same field again — if your click didn't land, press **tab** to
   move between fields instead of re-clicking. Never click a field repeatedly.
3. After typing in a field, **tab** to the next one and type; repeat down the form.
4. To replace text already in a field, click it once, **ctrl-a** (select all),
   then type the new value — don't backspace character by character.
5. **Small controls are easy to miss with clicks — drive them by keyboard:**
   - **checkbox**: focus it (tab, or one click), then press **spc** to toggle;
     confirm the check mark in the screenshot.
   - **dropdown (`select`)**: click it **once** — the option list pops open.
     Read the list in the screenshot, press **down**/**up** to highlight the
     option you want, then **enter** to commit. (Typing the option's first
     letter also jumps to it.) NEVER click a dropdown repeatedly — a second
     click just closes the list; if nothing seemed to happen, the click missed:
     use tab + arrows instead.
   - **button**: when it has keyboard focus (tab), **enter** activates it.
6. When all fields are filled AND the screenshot shows the right values, click
   the form's button (e.g. "Sign in", "Save draft", "Create account") **once**,
   then take a screenshot to confirm.
7. If a click on a small control visibly changed nothing, do NOT re-click at
   slightly different pixels — switch to the keyboard (tab/spc/arrows/enter).
8. If you see a browser **"Confirm Form Resubmission"** dialog, don't fight it —
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
- **Open a folder in Files (Nautilus)**: do NOT guess pixel coordinates for the
  icon — grid cells are small and easy to miss. Folder/file cells are in the
  accessibility tree by name, so **`click_element` by the folder's name to select
  it, then press `enter` to open it**. To descend `Workspace` → `inbox`:
  `click_element {"name":"Workspace"}`, `key {"keys":"enter"}`,
  `click_element {"name":"inbox"}`, `key {"keys":"enter"}`. (A single click only
  *selects* the folder; **enter** is what opens it — don't coordinate-double-click.)
  If you already know the exact full path, `ctrl-l` + type the path (or `run_bash`
  `nautilus <path>`) also works — but don't type a path you'd have to guess.
- **Act on a file in Files**: **`click_element` by the file's name** to select it
  (don't guess pixels), then act on the selection by keyboard: **Delete** moves it
  to the Trash (no confirmation; it just leaves the folder), **F2** renames,
  **enter** opens it. Avoid Shift+Delete unless you mean to permanently erase it.
- **Save a GUI file to an exact path** (GTK Save dialog, e.g. Text Editor Save
  As): the dialog opens with the **Name field already focused and only the name
  stem selected — the extension is NOT selected**. If you just start typing, the
  old extension is kept and you get `poem.txt.txt`. Do exactly this, once, in
  order, then stop and screenshot:
  1. Press **ctrl-a** — selects the WHOLE pre-filled name, extension included.
  2. Type the **full absolute path** (e.g. `/home/user/Desktop/poem.txt`). The
     Name field accepts an absolute path and saves to exactly that file — no
     folder navigation needed. (Do NOT use ctrl-l here: it does nothing in this
     dialog because focus is already in the Name entry.)
  3. Press **enter**. If a **Save** button is still showing, click it **once**.
  4. If a dialog asks **"A file named … already exists. Do you want to replace
     it?"**, click **Replace** (`click_element {"name":"Replace"}`).
  5. **Never click Cancel** — Cancel throws away the save and the dialog. If
     something looks wrong, screenshot and re-read the dialog rather than
     cancelling or re-opening it.
  Confirm the file with `run_bash` (`cat <path>`).
