# ============================================================================
# provision.ps1 — runs once at first logon (via autounattend FirstLogonCommands)
#
# Order of operations:
#   1. install virtio guest tools  -> network + display + balloon drivers
#   2. wait for internet
#   3. install Chocolatey (package manager)
#   4. install the packages listed below
#   5. apply machine-config tweaks
#
# Everything is logged to C:\provision.log
# Edit the $Packages list and the CONFIG section to taste.
# ============================================================================

$ErrorActionPreference = 'Continue'
Start-Transcript -Path C:\provision.log -Append | Out-Null
Write-Host "=== provision started $(Get-Date) ==="

# ---- EDIT ME: software to install (Chocolatey package names) ----------------
$Packages = @(
  'nodejs-lts',
  'git',
  'googlechrome',
  'yt-dlp'
  # ,'vscode'
  # ,'googlechrome'
  # ,'7zip'
  # ,'python'
  # ,'microsoft-windows-terminal'
)

# ---- 1. virtio guest tools (network + display + balloon drivers) ------------
$roots = (Get-PSDrive -PSProvider FileSystem).Root
$gt = Get-ChildItem -Path $roots -Filter 'virtio-win-gt-x64.msi' -ErrorAction SilentlyContinue |
        Select-Object -First 1
if ($gt) {
  Write-Host "Installing virtio guest tools: $($gt.FullName)"
  Start-Process msiexec.exe -Wait -ArgumentList "/i `"$($gt.FullName)`" /qn /norestart"
} else {
  Write-Host "WARNING: virtio-win-gt-x64.msi not found on any drive."
}

# ---- 2. wait for the network (NetKVM driver just came up) -------------------
# NB: use a TCP check, NOT ping — QEMU user-mode networking blocks ICMP, so
# Test-Connection would fail forever even though HTTP/TCP works fine.
Write-Host "Waiting for network..."
$online = $false
for ($i = 0; $i -lt 60; $i++) {
  try {
    if ((Test-NetConnection -ComputerName chocolatey.org -Port 443 `
          -InformationLevel Quiet -WarningAction SilentlyContinue)) {
      $online = $true; break
    }
  } catch {}
  Start-Sleep -Seconds 5
}
Write-Host "Network online: $online"

# ---- 3. Chocolatey ----------------------------------------------------------
if ($online -and -not (Get-Command choco -ErrorAction SilentlyContinue)) {
  Write-Host "Installing Chocolatey..."
  Set-ExecutionPolicy Bypass -Scope Process -Force
  [System.Net.ServicePointManager]::SecurityProtocol = 3072  # TLS 1.2
  Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
  $env:Path += ";$env:ALLUSERSPROFILE\chocolatey\bin"
}

# ---- 4. install packages ----------------------------------------------------
if ($online) {
  foreach ($p in $Packages) {
    Write-Host "--- choco install $p ---"
    & choco install $p -y --no-progress
  }
} else {
  Write-Host "Skipping package install: no network."
}

# ---- 5. OpenSSH server (so the host can run commands / copy files) ----------
# Reachable from the host at 127.0.0.1:2222 (QEMU forwards it to guest :22).
Write-Host "Enabling OpenSSH server..."
try {
  Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction Stop
} catch {
  Write-Host "Add-WindowsCapability failed, trying choco openssh..."
  if ($online) { & choco install openssh -y --no-progress --params '"/SSHServerFeature"' }
}
Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
Start-Service sshd -ErrorAction SilentlyContinue
# Allow inbound :22 on ALL firewall profiles — QEMU's NAT network is classed
# "Public", which the default OpenSSH rule does not cover.
Remove-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
  -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 `
  -Profile Any -ErrorAction SilentlyContinue

# ---- 6. CONFIG: machine tweaks (edit freely) --------------------------------
# Show file extensions in Explorer
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' HideFileExt 0 -ErrorAction SilentlyContinue
# Enable Remote Desktop + firewall rule
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' fDenyTSConnections 0 -ErrorAction SilentlyContinue
Enable-NetFirewallRule -DisplayGroup 'Remote Desktop' -ErrorAction SilentlyContinue
# Never sleep / blank screen while on AC power
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
# Never auto-lock the session (so the agent doesn't hit a lock screen)
Set-ItemProperty 'HKCU:\Control Panel\Desktop' ScreenSaveActive 0 -ErrorAction SilentlyContinue
Set-ItemProperty 'HKCU:\Control Panel\Desktop' ScreenSaveTimeOut 0 -ErrorAction SilentlyContinue
New-Item 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Force | Out-Null
Set-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' NoLockScreen 1 -ErrorAction SilentlyContinue
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 0 2>$null

# Example: global npm tools (uncomment after node is installed)
# & npm install -g pnpm yarn

Write-Host "=== provision finished $(Get-Date) ==="
Stop-Transcript | Out-Null
