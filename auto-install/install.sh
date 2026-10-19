#!/usr/bin/env bash

# PiFire installer for the Orange Pi Zero 2W (Orange Pi fork).
# Run by auto-install/orangepi/setup.sh (step 8), which prepares the board first and passes:
#   PIFIRE_REPO    Git URL to clone (this fork; git@ URL with the read-only deploy key)
#   PIFIRE_BRANCH  branch to clone (orangepi-dev, later orangepi-stable)
# Based on the PiFire installer (many thanks to the PiVPN project for the original inspiration).

INSTALL_SCRIPT_VERSION="orangepi"
PIFIRE_REPO="${PIFIRE_REPO:-git@github.com:cannos88/pifire-orangepi.git}"
PIFIRE_BRANCH="${PIFIRE_BRANCH:-orangepi-dev}"

# Create logs directory if it doesn't exist
mkdir -p ~/logs

# Start logging
echo "*************************************************************************" | tee ~/logs/pifire_install.log
echo "PiFire Installation Started at $(date '+%Y-%m-%d %H:%M:%S')" | tee ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo " ** Logging to ~/logs/pifire_install.log **" | tee -a ~/logs/pifire_install.log

# Must be root to install
if [[ $EUID -eq 0 ]];then
    echo " + You are root." | tee -a ~/logs/pifire_install.log
else
    echo " + SUDO will be used for the install." | tee -a ~/logs/pifire_install.log
    # Check if it is actually installed
    # If it isn't, exit because the install cannot complete
    if [[ $(dpkg-query -s sudo) ]];then
        export SUDO="sudo"
        export SUDOE="sudo -E"
    else
        echo " !! Installation Failed, 'sudo' not found. Please install sudo.  Exiting" | tee -a ~/logs/pifire_install.log
        exit 1
    fi
    # Authenticate once upfront and keep the sudo session alive for the duration of the install.
    # This is needed on systems where sudo requires a password.
    echo " *************************************************************************" | tee -a ~/logs/pifire_install.log
    echo " + Please enter your sudo password to proceed with installation." | tee -a ~/logs/pifire_install.log
    echo " *************************************************************************" | tee -a ~/logs/pifire_install.log
    sudo -v || { echo " !! Failed to authenticate with sudo. Exiting." | tee -a ~/logs/pifire_install.log; exit 1; }
    # Refresh sudo timestamp every 60 seconds in the background so it never expires mid-install
    while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null &
    SUDO_KEEPALIVE_PID=$!
fi

# 64-bit ARM only (Armbian on the Orange Pi Zero 2W)
ARCH=$(uname -m)
echo " + System architecture: $ARCH" | tee -a ~/logs/pifire_install.log
if [[ "$ARCH" != "aarch64" ]]; then
    echo " !! This installer is for the Orange Pi Zero 2W with a 64-bit OS (aarch64). Exiting." | tee -a ~/logs/pifire_install.log
    exit 1
fi

# Determine OS version number
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME=$NAME
    OS_VERSION=$VERSION_ID
    echo " + Detected OS: $OS_NAME Version: $OS_VERSION" | tee -a ~/logs/pifire_install.log
else
    echo " !! Unable to determine OS version. /etc/os-release not found." | tee -a ~/logs/pifire_install.log
    exit 1
fi  

sleep 2
# Find the rows and columns. Will default to 80x24 if it can not be detected.
screen_size=$(stty size 2>/dev/null || echo 24 80)
rows=$(echo $screen_size | awk '{print $1}')
columns=$(echo $screen_size | awk '{print $2}')

# Divide by two so the dialogs take up half of the screen.
r=$(( rows / 2 ))
c=$(( columns / 2 ))
# If the screen is small, modify defaults
r=$(( r < 20 ? 20 : r ))
c=$(( c < 70 ? 70 : c ))

# Display the welcome dialog
whiptail --msgbox --backtitle "Welcome" --title "PiFire Automated Installer" "This installer turns the Orange Pi Zero 2W into the PiFire controller of the grill. Run it from auto-install/orangepi/setup.sh on a fresh Armbian (Debian 12 or 13)." ${r} ${c}

# Supervisor WebUI Settings
SVISOR=$(whiptail --title "Would you like to enable the supervisor WebUI?" --radiolist "This allows you to check the status of the supervised processes via a web browser, and also allows those processes to be restarted directly from this interface. (Recommended)" 20 78 2 "ENABLE_SVISOR" "Enable the WebUI" ON "DISABLE_SVISOR" "Disable the WebUI" OFF 3>&1 1>&2 2>&3)

if [[ $SVISOR = "ENABLE_SVISOR" ]];then
   USERNAME=$(whiptail --inputbox "Choose a username [default: user]" 8 78 user --title "Choose Username" 3>&1 1>&2 2>&3)
   PASSWORD=$(whiptail --passwordbox "Enter your password" 8 78 --title "Choose Password" 3>&1 1>&2 2>&3)
   whiptail --msgbox --backtitle "Supervisor WebUI Setup" --title "Supervisor Configured" "After this installation is completed, you should be able to access the Supervisor WebUI at http://your.ip.address.here:9001 with the username and password you have chosen." ${r} ${c}
else
    echo "No Supervisor WebUI Setup." | tee -a ~/logs/pifire_install.log
fi

echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "**      Running Apt Update... (This could take several minutes)        **" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
# Update package list, exit if failed
$SUDO apt update 2>&1 | tee -a ~/logs/pifire_install.log || exit 1

echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "**      Running Apt Upgrade... (This could take several minutes)       **" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
# Upgrade packages, exit if failed
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold 2>&1 | tee -a ~/logs/pifire_install.log
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo " !! Failed to upgrade packages. Installation cannot continue." | tee -a ~/logs/pifire_install.log
    exit 1
fi

# Install APT dependencies
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "**      Installing Dependencies... (This could take several minutes)   **" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
# Install dependencies, exit if failed
$SUDO apt install python3-dev python3-pip python3-venv python3-scipy nginx git supervisor ttf-mscorefonts-installer redis-server gfortran libopenblas-dev liblapack-dev libopenjp2-7 -y 2>&1 | tee -a ~/logs/pifire_install.log
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo " !! Failed to install dependencies. Installation cannot continue." | tee -a ~/logs/pifire_install.log
    exit 1
fi
# Grab project files
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "**      Cloning PiFire from GitHub...                                  **" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
cd /usr/local/bin

echo " + Cloning $PIFIRE_REPO (branch $PIFIRE_BRANCH)..." | tee -a ~/logs/pifire_install.log
$SUDO git clone --depth 1 --branch "$PIFIRE_BRANCH" "$PIFIRE_REPO" pifire 2>&1 | tee -a ~/logs/pifire_install.log
if [[ ! -f pifire/app.py ]]; then
    echo " !! Failed to clone $PIFIRE_REPO. Installation cannot continue." | tee -a ~/logs/pifire_install.log
    exit 1
fi

# Setup Python VENV & Install Python dependencies
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "**      Setting up Python VENV and Installing Modules...               **" | tee -a ~/logs/pifire_install.log
echo "**            (This could take several minutes)                        **" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo ""
echo " + Setting Up PiFire Group"
cd /usr/local/bin
$SUDO groupadd pifire 
$SUDO usermod -a -G pifire $USER 
$SUDO usermod -a -G pifire root 
# Change ownership to group=pifire for all files/directories in pifire 
$SUDO chown -R $USER:pifire pifire 
# Change ability for pifire group to read/write/execute 
$SUDO chmod -R 777 /usr/local/bin

# Install sudoers drop-in so the pifire group can run required system commands
# without a password prompt.
echo " + Installing sudoers rules for pifire group" | tee -a ~/logs/pifire_install.log
$SUDO tee /etc/sudoers.d/pifire > /dev/null <<'EOF'
# Allow members of the pifire group to run system commands required by PiFire
# without being prompted for a password.

# System control (control.py, display modules, common.py)
%pifire ALL=(ALL) NOPASSWD: /sbin/shutdown, /sbin/reboot, /usr/sbin/shutdown, /usr/sbin/reboot

# Supervisor management (common.py restarts control/webapp processes)
%pifire ALL=(ALL) NOPASSWD: /usr/bin/supervisorctl, /bin/supervisorctl
%pifire ALL=(ALL) NOPASSWD: /bin/systemctl restart supervisor, /usr/bin/systemctl restart supervisor

# Package management (updater.py, wizard.py apt installs)
%pifire ALL=(ALL) NOPASSWD: /usr/bin/apt, /usr/bin/apt-get

# File operations (updater manifest cp of supervisor conf files)
%pifire ALL=(ALL) NOPASSWD: /bin/cp, /usr/bin/cp

# Script execution (updater manifest runs auto-install/orangepi/ota-system.sh)
%pifire ALL=(ALL) NOPASSWD: /bin/bash, /usr/bin/bash
EOF
$SUDO chmod 0440 /etc/sudoers.d/pifire
# Validate the file is syntactically correct before proceeding
if ! $SUDO visudo -cf /etc/sudoers.d/pifire; then
    echo " !! sudoers file validation failed. Removing and continuing without it." | tee -a ~/logs/pifire_install.log
    $SUDO rm -f /etc/sudoers.d/pifire
else
    echo " + sudoers rules installed successfully." | tee -a ~/logs/pifire_install.log
fi

# Exact versions of every package (direct and indirect) for this release:
# libraries change only with a new release (Orange Pi fork, tools/lock_dependencies.sh)
CONSTRAINTS=/usr/local/bin/pifire/auto-install/constraints.txt
CONSTRAINT_ARGS=()
[ -f "$CONSTRAINTS" ] && CONSTRAINT_ARGS=(-c "$CONSTRAINTS")

# Python environment: uv venv with the system packages (numpy/scipy from Debian)
echo " + Installing UV" | tee -a ~/logs/pifire_install.log
if ! /bin/curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" /bin/sh; then
    echo " ! Failed to download or install UV. Exiting." | tee -a ~/logs/pifire_install.log
    exit 1
fi

echo " + Setting up VENV" | tee -a ~/logs/pifire_install.log
cd /usr/local/bin/pifire
uv venv --system-site-packages
source .venv/bin/activate

echo " + Installing modules from requirements.txt one at a time... " | tee -a ~/logs/pifire_install.log
while IFS= read -r req || [ -n "$req" ]; do
    # Strip inline comments and trim whitespace
    req="${req%%#*}"
    req="$(echo "$req" | xargs)"
    [ -z "$req" ] && continue
    echo " - Installing $req ..." | tee -a ~/logs/pifire_install.log
    uv pip install "${CONSTRAINT_ARGS[@]}" "$req" 2>&1 | tee -a ~/logs/pifire_install.log
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        echo " !! Failed to install $req. Installation cannot continue." | tee -a ~/logs/pifire_install.log
        exit 1
    fi
done < /usr/local/bin/pifire/auto-install/requirements.txt
echo " + requirements.txt installation complete." | tee -a ~/logs/pifire_install.log

# Get PIP List into JSON file
echo " - Getting PIP List into JSON file" | tee -a ~/logs/pifire_install.log
python updater.py --piplist 2>&1 | tee -a ~/logs/pifire_install.log


### Setup nginx to proxy to gunicorn
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "**      Configuring nginx...                                           **" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
# Move into install directory
cd /usr/local/bin/pifire/auto-install/nginx

# Generate Self-Signed SSL Certificate
echo " + Generating Self-Signed SSL Certificate" | tee -a ~/logs/pifire_install.log
if ! $SUDO openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout /etc/ssl/private/localhost.key -out /etc/ssl/certs/localhost.crt -subj "/CN=localhost" -batch; then
    echo " !! Failed to generate SSL certificate. HTTPS may not function correctly." | tee -a ~/logs/pifire_install.log
else
    echo " + SSL Certificate generation successful." | tee -a ~/logs/pifire_install.log
fi

# Delete default configuration
$SUDO rm /etc/nginx/sites-enabled/default

# Copy configuration file to nginx
$SUDO cp pifire.nginx /etc/nginx/sites-available/pifire

# Create link in sites-enabled
$SUDO ln -s /etc/nginx/sites-available/pifire /etc/nginx/sites-enabled

# Copy server_error.html to /usr/share/nginx/html
$SUDO cp server_error.html /usr/share/nginx/html

# Restart nginx
$SUDO service nginx restart

### Setup Supervisor to Start Apps on Boot / Restart on Failures
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "**      Configuring Supervisord...                                     **" | tee -a ~/logs/pifire_install.log
echo "**                                                                     **" | tee -a ~/logs/pifire_install.log
echo "*************************************************************************" | tee -a ~/logs/pifire_install.log

# Copy configuration files (control.conf, webapp.conf) to supervisor config directory
cd /usr/local/bin/pifire/auto-install/supervisor

# Add the current username to the configuration files 
echo "user=$USER" | tee -a control.conf > /dev/null
echo "user=$USER" | tee -a webapp.conf > /dev/null

$SUDO cp *.conf /etc/supervisor/conf.d/

if [[ $SVISOR = "ENABLE_SVISOR" ]];then
   echo " " | sudo tee -a /etc/supervisor/supervisord.conf > /dev/null
   echo "[inet_http_server]" | sudo tee -a /etc/supervisor/supervisord.conf > /dev/null
   echo "port = 9001" | sudo tee -a /etc/supervisor/supervisord.conf > /dev/null
   echo "username = " $USERNAME | sudo tee -a /etc/supervisor/supervisord.conf > /dev/null
   echo "password = " $PASSWORD | sudo tee -a /etc/supervisor/supervisord.conf > /dev/null
else
   echo "No WebUI Setup." | tee -a ~/logs/pifire_install.log
fi

# If supervisor isn't already running, startup Supervisor
$SUDO service supervisor start 2>&1 | tee -a ~/logs/pifire_install.log

# Installation Complete, Reboot Prompt
echo "+ Installation completed at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a ~/logs/pifire_install.log

# Ask user if they want to reboot
if whiptail --backtitle "Install Complete" --title "Installation Completed" --yesno "Congratulations, the installation is complete.\n\nIt's recommended to reboot your system now for all changes to take effect. On first boot, the wizard will guide you through the remaining setup steps.\n\nYou should be able to access your application by opening a browser on your PC or other device and using the IP address (or http://[hostname].local) for this device.\n\nWould you like to reboot now?" ${r} ${c}; then
    echo "Rebooting system..." | tee -a ~/logs/pifire_install.log
    $SUDO cp ~/logs/pifire_install.log /usr/local/bin/pifire/logs/pifire_install_$(date '+%Y%m%d_%H%M%S').log
    $SUDO reboot
else
    echo "Reboot skipped. Please reboot manually when convenient." | tee -a ~/logs/pifire_install.log
    $SUDO cp ~/logs/pifire_install.log /usr/local/bin/pifire/logs/pifire_install_$(date '+%Y%m%d_%H%M%S').log
    exit 0
fi

