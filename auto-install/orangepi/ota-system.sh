#!/usr/bin/env bash
#
# System-level steps of an OTA update on the Orange Pi (run by the PiFire
# updater, as root, from updater/updater_manifest.json).  Idempotent: safe to
# run on every update.
#
#  - supervisor configuration (web app listening on 127.0.0.1 only)
#  - emergency Wi-Fi service, only where NetworkManager already runs the network.
#    Switching an Armbian Minimal system from systemd-networkd to NetworkManager
#    is NOT done here: done unattended it could cut the grill off the network.
#    That stays in setup.sh (step 7), run by hand over SSH.

PIFIRE_DIR=${PIFIRE_DIR:-/usr/local/bin/pifire}
SUPERVISOR_DIR=${SUPERVISOR_DIR:-/etc/supervisor/conf.d}	# both overridable for the tests
LOG="$PIFIRE_DIR/logs/ota-system.log"
mkdir -p "$PIFIRE_DIR/logs"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# Supervisor: the configuration install.sh copies
CONF_DIR="$PIFIRE_DIR/auto-install/supervisor"
if [[ -d "$SUPERVISOR_DIR" ]]; then
	# install.sh appends "user=<installer user>" to these files; the repo copies do not
	# have it, so keep the user already configured (else supervisor would run PiFire as root)
	RUN_USER=$(sed -n 's/^user=//p' "$SUPERVISOR_DIR/webapp.conf" 2>/dev/null | tail -1)
	[[ -n "$RUN_USER" ]] || RUN_USER=$(stat -c %U "$PIFIRE_DIR")
	for conf in control.conf webapp.conf; do
		{ grep -v '^user=' "$CONF_DIR/$conf"; echo "user=$RUN_USER"; } > "$SUPERVISOR_DIR/$conf.new" \
			&& mv "$SUPERVISOR_DIR/$conf.new" "$SUPERVISOR_DIR/$conf"
	done
	log "supervisor: configuration updated from $CONF_DIR for user $RUN_USER (applied at the next restart)"
fi

# Emergency Wi-Fi network
if systemctl is-active --quiet NetworkManager && ! grep -qsE '^[[:space:]]*renderer:[[:space:]]*networkd' /etc/netplan/*.yaml; then
	mkdir -p /etc/NetworkManager/dnsmasq-shared.d
	cp "$PIFIRE_DIR/auto-install/orangepi/pifire-captive.conf" /etc/NetworkManager/dnsmasq-shared.d/pifire-captive.conf
	cp "$PIFIRE_DIR/auto-install/orangepi/pifire-wifi.service" /etc/systemd/system/pifire-wifi.service
	systemctl daemon-reload
	systemctl enable pifire-wifi.service >/dev/null 2>&1
	systemctl restart pifire-wifi.service && log "pifire-wifi: installed and restarted"
else
	log "pifire-wifi: NetworkManager does not manage the network yet; run setup.sh step 7 over SSH to enable the emergency Wi-Fi"
fi
exit 0
