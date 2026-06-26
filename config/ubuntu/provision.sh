#!/bin/bash
# Runs in the target system (via `curtin in-target`) during autoinstall.
# Best-effort (no `set -e`): a hiccup here must never fail the OS install — the
# late-command wraps this with `|| true`. Repairable afterwards over SSH.
export DEBIAN_FRONTEND=noninteractive
echo "=== ubuntu provision started $(date) ==="

# The base desktop target lacks curl — install prerequisites first.
apt-get update -y
apt-get install -y curl ca-certificates gnupg

echo "=== Node.js (NodeSource LTS) ==="
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
apt-get install -y nodejs

echo "=== Google Chrome ==="
curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb
apt-get install -y /tmp/chrome.deb || apt-get -f install -y
rm -f /tmp/chrome.deb
# Managed policy: skip the first-run / "Sign in to Chrome" promo and the
# default-browser nag, so Chrome opens straight into browsing (any launcher).
install -d /etc/opt/chrome/policies/managed
cat > /etc/opt/chrome/policies/managed/agent.json <<'EOF'
{
  "BrowserSignin": 0,
  "SyncDisabled": true,
  "DefaultBrowserSettingEnabled": false,
  "PromotionalTabsEnabled": false,
  "MetricsReportingEnabled": false,
  "PasswordManagerEnabled": false,
  "PasswordLeakDetectionEnabled": false
}
EOF
# Belt-and-suspenders: also bake --no-first-run / --no-default-browser-check into
# every launcher Exec line. GNOME Activities opens Chrome via this .desktop (not a
# flagged command), so this guarantees a fresh profile skips the first-run "Sign in
# to Chrome" modal even if the managed policy above is ever absent.
DESKTOP=/usr/share/applications/google-chrome.desktop
if [ -f "$DESKTOP" ]; then
  sed -i -E 's#^Exec=(/usr/bin/google-chrome-stable|/opt/google/chrome/google-chrome)#Exec=\1 --no-first-run --no-default-browser-check#' "$DESKTOP"
fi

echo "=== accessibility (AT-SPI) tooling for the agent's ui_tree() ==="
# python3-pyatspi: the AT-SPI tree. xdotool + x11-utils (xprop): used to recover
# GTK4/libadwaita "bogus (0,0)" widget rects from X11 window geometry +
# _GTK_FRAME_EXTENTS (see config/ubuntu/atspi_helper.py). Needs the Xorg session.
apt-get install -y python3-pyatspi xdotool x11-utils

echo "=== GDM: Xorg, password login (keeps the keyring encrypted) ==="
# Deliberately NO autologin: password login lets pam_gnome_keyring create and
# unlock the encrypted login keyring, so Chrome uses real secret storage (not
# the plaintext --password-store=basic). WaylandEnable=false → Xorg, which makes
# launching GUI apps into the session over SSH (DISPLAY=:0) straightforward.
install -d /etc/gdm3
cat > /etc/gdm3/custom.conf <<'EOF'
[daemon]
WaylandEnable=false
EOF

echo "=== disable screen lock / blanking ==="
install -d /etc/dconf/profile /etc/dconf/db/local.d
printf 'user-db:user\nsystem-db:local\n' > /etc/dconf/profile/user
cat > /etc/dconf/db/local.d/00-no-lock <<'EOF'
[org/gnome/desktop/session]
idle-delay=uint32 0
[org/gnome/desktop/screensaver]
lock-enabled=false
idle-activation-enabled=false
[org/gnome/settings-daemon/plugins/power]
sleep-inactive-ac-type='nothing'
[org/gnome/desktop/interface]
toolkit-accessibility=true
EOF
dconf update || true

echo "=== ubuntu provision done $(date) ==="
