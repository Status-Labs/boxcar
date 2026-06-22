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
EOF
dconf update || true

echo "=== ubuntu provision done $(date) ==="
