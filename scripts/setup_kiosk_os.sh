#!/bin/bash
# Kiosk OS setup script for Ubuntu 22.04
# Configures system for kiosk deployment

set -e

echo "=== Kiosk OS Setup Script ==="
echo "This script configures Ubuntu 22.04 for kiosk deployment"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root"
    exit 1
fi

KIOSK_USER="${KIOSK_USER:-kiosk}"

echo "[1/7] Creating kiosk user..."
if ! id "$KIOSK_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$KIOSK_USER"
    echo "  Created user: $KIOSK_USER"
else
    echo "  User already exists: $KIOSK_USER"
fi

echo "[2/7] Configuring auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d/
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $KIOSK_USER --noclear %I \$TERM
EOF
echo "  Auto-login configured for $KIOSK_USER"

echo "[3/7] Disabling screen blanking..."
# Disable screen blanking in X11
mkdir -p /home/$KIOSK_USER/.config/autostart
cat > /home/$KIOSK_USER/.config/autostart/disable-screensaver.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Disable Screensaver
Exec=xset s off -dpms
EOF
chown -R $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.config
echo "  Screen blanking disabled"

echo "[4/7] Configuring audio devices..."
# Add user to audio group
usermod -a -G audio $KIOSK_USER
echo "  User added to audio group"

echo "[5/7] Installing systemd service..."
# Copy service file (assumes it exists)
if [ -f "client/kiosk.service" ]; then
    cp client/kiosk.service /etc/systemd/system/
    systemctl daemon-reload
    echo "  Service file installed"
else
    echo "  Warning: client/kiosk.service not found"
fi

echo "[6/7] Configuring power management..."
# Disable suspend and hibernate
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
echo "  Power management disabled"

echo "[7/7] Setting up environment..."
# Create .bashrc for kiosk user
cat >> /home/$KIOSK_USER/.bashrc <<EOF

# Kiosk environment
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
EOF
chown $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.bashrc
echo "  Environment configured"

echo ""
echo "=== Kiosk OS Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Enable the kiosk service: systemctl enable kiosk.service"
echo "2. Start the kiosk service: systemctl start kiosk.service"
echo "3. Reboot the system to apply all changes"
