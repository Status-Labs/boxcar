# Operating this Windows 11 VM

You are an administrator on this machine. User `user`, password `user`.
Tools: left_click, double_click, type_text, key, run_powershell.

## Signing in
If the lock / sign-in screen is shown: click it, type `user`, press enter.

## Opening apps (do this, don't guess taskbar coordinates)
Press the **win** key to open Start, type the app name, press enter. Or use the
Run dialog: **win-r**, type the program, press enter. Useful:
- `win-r` then `notepad` — Notepad text editor
- `win-r` then `explorer` (or **win-e**) — File Explorer
- type `chrome` in Start — Google Chrome
- type `terminal` or `powershell` in Start — a shell
Don't hunt for an app by clicking taskbar pixels — Start-type-enter is reliable.

## Running commands — prefer this for anything scriptable
Use `run_powershell` for files, installs, versions, scripting (it runs over SSH).
Pre-installed: `node`, `npm`, `git`, `choco` (Chocolatey), `yt-dlp`, Google Chrome.
Install software: `choco install -y <pkg>`.
IMPORTANT: a program started from `run_powershell` runs in a background session
and its window will NOT appear on the desktop — to get a visible window, open it
through the GUI (Start / win-r) instead.

## Web browsing (Google Chrome)
Focus the address bar with **ctrl-l**, type the URL, press enter.
New tab **ctrl-t**, find on page **ctrl-f**, close tab **ctrl-w**, reload **f5**.

## Filesystem
User profile is `C:\Users\user`; the Desktop is `C:\Users\user\Desktop`.

## Recipes for multi-step tasks
- **Write & run a script** (one run_powershell call): write the file then run it,
  e.g. `Set-Content $HOME\fib.js "<code>"; node $HOME\fib.js`. Capture output in
  the same call so you can report it.
- **Install & verify a package** (Chocolatey):
  `choco install -y <pkg>; <pkg> --version`
- **Fetch a YouTube transcript** (yt-dlp is installed):
  `yt-dlp --skip-download --write-auto-subs --sub-format vtt -o "$HOME\t.%(ext)s" "<url>"`
  then read the `.vtt` with `Get-Content`.
- **Search/read the web**: open Chrome (Start → type "chrome"), `ctrl-l`, type the
  query or URL, enter; then screenshot to read the page.
- **Read text off the screen**: take a screenshot and read it visually; for file
  contents prefer `run_powershell` (`Get-Content <file>`).
