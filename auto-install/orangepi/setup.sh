#!/usr/bin/env bash
#
# PiFire on Orange Pi Zero 2W: board preparation and installation
#
# Run on the Orange Pi, from a checkout of this repository:
#   sudo bash auto-install/orangepi/setup.sh
#
# Steps (each one asks before changing anything):
#   1. system packages needed by PiFire and by the GPIO/I2C tools
#   2. Debian "contrib" component (needed by the installer for the fonts package)
#   3. serial console off, so header pins 8 and 10 can be used by the buttons/encoder
#   4. I2C1 (pins 3/5) and SPI1 overlays in the boot configuration
#   5. read-only deploy key for the private repository (root, used by installer and updater)
#   6. emergency Wi-Fi network: NetworkManager, open network "PiFire-Setup" when no known Wi-Fi
#   7. PiFire installer, cloning this repository
#
# Options (environment variables):
#   PIFIRE_REPO    repository to install   (default: git@github.com:cannos88/pifire-orangepi.git)
#   PIFIRE_BRANCH  branch to install       (default: orangepi-dev)

set -u

PIFIRE_REPO="${PIFIRE_REPO:-git@github.com:cannos88/pifire-orangepi.git}"
PIFIRE_BRANCH="${PIFIRE_BRANCH:-orangepi-dev}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REBOOT_NEEDED=0

say()  { printf '\n\033[1;33m== %s ==\033[0m\n' "$1"; }
info() { printf ' + %s\n' "$1"; }
warn() { printf ' ! %s\n' "$1"; }
ask()  { local reply; read -r -p " ? $1 [s/N] " reply; [[ "$reply" =~ ^([sSyY]|si|sì)$ ]]; }

if [[ $EUID -ne 0 ]]; then
	echo "Esegui lo script con sudo: sudo bash $0"
	exit 1
fi
RUN_USER="${SUDO_USER:-root}"

# ---------------------------------------------------------------------------
say "Scheda"
MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo sconosciuta)"
info "Modello: $MODEL"
info "Kernel:  $(uname -r)"
if [[ ! "$MODEL" =~ [Zz]ero.?2[Ww] ]]; then
	warn "Questo script è pensato per l'Orange Pi Zero 2W."
	ask "Continuare comunque?" || exit 1
fi

# ---------------------------------------------------------------------------
say "1. Pacchetti di sistema"
PACKAGES="git curl whiptail python3-dev python3-venv build-essential i2c-tools gpiod python3-libgpiod"
info "Da installare: $PACKAGES"
if ask "Installo i pacchetti?"; then
	apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y $PACKAGES || warn "Installazione pacchetti non riuscita: controlla i messaggi qui sopra."
fi

# ---------------------------------------------------------------------------
say "2. Repository Debian contrib"
if apt-cache policy ttf-mscorefonts-installer 2>/dev/null | grep -q 'Candidate: (none)' \
	|| ! apt-cache policy ttf-mscorefonts-installer 2>/dev/null | grep -q 'Candidate'; then
	warn "Il pacchetto dei font usato dall'installer di PiFire non è disponibile: serve il componente 'contrib'."
	# Debian 13 (trixie) uses deb822 files in sources.list.d, older releases use sources.list
	SOURCES=""
	for f in /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; do
		[[ -f "$f" ]] && grep -qE '^(deb|URIs:).*debian' "$f" && SOURCES="$SOURCES $f"
	done
	if [[ -n "$SOURCES" ]] && ask "Aggiungo 'contrib' ai repository Debian in$SOURCES (con backup)?"; then
		for f in $SOURCES; do
			cp "$f" "$f.pifire.bak"
			if [[ "$f" == *.sources ]]; then
				sed -i -E '/^Components:/{/contrib/! s/main/main contrib/}' "$f"
			else
				sed -i -E '/^deb(-src)? .*debian.* main/{/ contrib/! s/ main/ main contrib/}' "$f"
			fi
		done
		apt-get update
		apt-cache policy ttf-mscorefonts-installer | grep -q 'Candidate: [0-9]' \
			&& info "contrib attivo." || warn "Ancora non disponibile: controlla /etc/apt/sources.list a mano."
	fi
else
	info "OK, il pacchetto dei font è disponibile."
fi

# ---------------------------------------------------------------------------
say "3. Console seriale (pin 8 e 10)"
ENV_FILE=""
for f in /boot/orangepiEnv.txt /boot/armbianEnv.txt /boot/dietpiEnv.txt; do
	[[ -f "$f" ]] && ENV_FILE="$f" && break
done
info "Configurazione di boot: ${ENV_FILE:-non trovata}"
info "La PCB v4 collega tasti/encoder ai pin 8 e 10, che sono la console seriale di debug."
info "Se usi solo la web app puoi lasciarla attiva."
if ask "Disattivo la console seriale (resta il login via SSH e sullo schermo HDMI)?"; then
	systemctl disable --now serial-getty@ttyS0.service 2>/dev/null && info "Login seriale disattivato."
	if [[ -n "$ENV_FILE" ]]; then
		cp "$ENV_FILE" "$ENV_FILE.pifire.bak"
		if grep -q '^console=' "$ENV_FILE"; then
			sed -i -E 's/^console=.*/console=display/' "$ENV_FILE"
		else
			echo "console=display" >> "$ENV_FILE"
		fi
		info "console=display impostato in $ENV_FILE (backup in $ENV_FILE.pifire.bak)."
		REBOOT_NEEDED=1
	fi
	warn "U-Boot usa comunque il pin 8 durante l'avvio: sul filo CLK dell'encoder metti una resistenza da 1 kΩ in serie."
fi

# ---------------------------------------------------------------------------
say "4. Overlay I2C e SPI"
OVERLAY_DIR="$(ls -d /boot/dtb/allwinner/overlay /boot/dtb*/allwinner/overlay 2>/dev/null | head -n1)"
if [[ -z "$ENV_FILE" || -z "$OVERLAY_DIR" ]]; then
	warn "Configurazione overlay non trovata (env: ${ENV_FILE:-?}, cartella: ${OVERLAY_DIR:-?}). Salto questo passo."
else
	PREFIX="$(grep -E '^overlay_prefix=' "$ENV_FILE" | cut -d= -f2)"
	PREFIX="${PREFIX:-sun50i-h616}"
	info "Cartella overlay: $OVERLAY_DIR (prefisso $PREFIX)"
	AVAILABLE="$(ls "$OVERLAY_DIR" | grep -E "^${PREFIX}-.*\.dtbo$" | sed -E "s/^${PREFIX}-//; s/\.dtbo$//" | tr '\n' ' ')"
	info "Disponibili: $AVAILABLE"
	pick() {  # first candidate that exists
		for c in "$@"; do
			[[ -f "$OVERLAY_DIR/${PREFIX}-$c.dtbo" ]] && { echo "$c"; return; }
		done
	}
	# Names differ between Orange Pi OS and Armbian/DietPi images
	I2C="$(pick pi-i2c1 i2c1-pi i2c1)"
	SPI="$(pick pi-spi1-cs0-cs1-spidev spidev1_0 spi1-cs0-spidev spi-spidev)"
	CURRENT="$(grep -E '^overlays=' "$ENV_FILE" | cut -d= -f2)"
	info "Attivi ora: ${CURRENT:-nessuno}"
	WANTED=""
	[[ -n "$I2C" ]] && WANTED="$WANTED $I2C" || warn "Overlay I2C1 non riconosciuto: mandami la riga 'Disponibili' qui sopra."
	[[ -n "$SPI" ]] && WANTED="$WANTED $SPI" || info "Overlay SPI1 non riconosciuto (serve solo per display SPI o MAX31865)."
	if [[ -n "$WANTED" ]] && ask "Aggiungo agli overlay:$WANTED ?"; then
		NEW="$(echo $CURRENT $WANTED | tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' ' | sed 's/ $//')"
		cp "$ENV_FILE" "$ENV_FILE.pifire-overlays.bak"
		if grep -q '^overlays=' "$ENV_FILE"; then
			sed -i -E "s/^overlays=.*/overlays=$NEW/" "$ENV_FILE"
		else
			echo "overlays=$NEW" >> "$ENV_FILE"
		fi
		info "overlays=$NEW"
		REBOOT_NEEDED=1
	fi
fi

# ---------------------------------------------------------------------------
say "5. Chiave di accesso al repository privato"
KEY=/root/.ssh/id_ed25519
if [[ "$PIFIRE_REPO" == git@* ]]; then
	if [[ ! -f "$KEY" ]]; then
		mkdir -p /root/.ssh && chmod 700 /root/.ssh
		ssh-keygen -t ed25519 -N "" -C "pifire-$(hostname)" -f "$KEY" >/dev/null && info "Chiave creata."
	fi
	ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
	sort -u -o /root/.ssh/known_hosts /root/.ssh/known_hosts
	echo
	echo "   Aggiungi questa chiave al repository su GitHub:"
	echo "   Settings > Deploy keys > Add deploy key  (lascia 'Allow write access' DISATTIVATO)"
	echo
	cat "$KEY.pub"
	echo
	read -r -p " Premi Invio quando l'hai aggiunta... " _
	if ssh -o BatchMode=yes -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
		info "Accesso a GitHub riuscito."
	else
		warn "GitHub non accetta ancora la chiave: controlla la deploy key e riprova."
	fi
else
	info "Repository pubblico ($PIFIRE_REPO): nessuna chiave necessaria."
fi

# ---------------------------------------------------------------------------
say "6. Rete Wi-Fi di emergenza"
info "Se il grill resta senza Wi-Fi per 3 minuti accende una rete aperta, «PiFire-Setup» (senza password)."
info "Col telefono ti colleghi a quella rete, si apre la pagina Wi-Fi del grill e scegli la rete nuova."
info "Da quella rete si vede solo la pagina Wi-Fi: il grill non si comanda."
if ask "Configuro la rete di emergenza?"; then
	apt-get install -y network-manager dnsmasq-base avahi-daemon libnss-mdns \
		|| warn "Installazione di NetworkManager non riuscita: controlla i messaggi qui sopra."

	# Armbian Minimal: netplan + systemd-networkd.  Hand the interfaces to NetworkManager
	# (the CLI images already do this).  The saved Wi-Fi stays, it only changes manager.
	NETPLAN_TODO=""
	for f in /etc/netplan/*.yaml; do
		[[ -f "$f" ]] || continue
		grep -qE '^[[:space:]]*renderer:[[:space:]]*NetworkManager' "$f" || NETPLAN_TODO="$NETPLAN_TODO $f"
	done
	if [[ -n "$NETPLAN_TODO" ]]; then
		info "Rete gestita da systemd-networkd in:$NETPLAN_TODO"
		warn "Passo la gestione a NetworkManager. La rete configurata resta e riparte dopo il riavvio;"
		warn "se il Wi-Fi non tornasse, dopo 3 minuti compare comunque la rete PiFire-Setup."
		if ask "Procedo (backup accanto a ogni file)?"; then
			for f in $NETPLAN_TODO; do
				cp "$f" "$f.pifire.bak"
				if grep -qE '^[[:space:]]*renderer:' "$f"; then
					sed -i -E 's/^([[:space:]]*)renderer:.*/\1renderer: NetworkManager/' "$f"
				else
					sed -i -E 's/^network:[[:space:]]*$/network:\n  renderer: NetworkManager/' "$f"
				fi
				chmod 600 "$f"
			done
			netplan generate && info "netplan aggiornato." || warn "netplan generate ha dato errore: controlla i file in /etc/netplan."
			systemctl enable NetworkManager >/dev/null 2>&1
			REBOOT_NEEDED=1
		fi
	else
		info "NetworkManager gestisce già la rete."
	fi

	mkdir -p /etc/NetworkManager/dnsmasq-shared.d
	cp "$REPO_DIR/auto-install/orangepi/pifire-captive.conf" /etc/NetworkManager/dnsmasq-shared.d/pifire-captive.conf
	cp "$REPO_DIR/auto-install/orangepi/pifire-wifi.service" /etc/systemd/system/pifire-wifi.service
	systemctl daemon-reload
	systemctl enable pifire-wifi.service >/dev/null 2>&1 && info "Servizio pifire-wifi abilitato (parte quando PiFire è installato)."
	info "Pagina Wi-Fi: http://$(hostname).local/wifi  ·  rete di emergenza: http://10.42.0.1"
fi

# ---------------------------------------------------------------------------
say "7. Installazione di PiFire"
info "Repository: $PIFIRE_REPO  (ramo $PIFIRE_BRANCH)"
if [[ -d /usr/local/bin/pifire ]]; then
	warn "/usr/local/bin/pifire esiste già: l'installer non sovrascrive un'installazione esistente."
elif [[ $REBOOT_NEEDED -eq 1 ]]; then
	info "Prima riavvia per attivare le modifiche di boot, poi rilancia questo script e salta i passi già fatti."
elif ask "Avvio l'installer di PiFire (richiede 15-30 minuti)?"; then
	sudo -u "$RUN_USER" env PIFIRE_REPO="$PIFIRE_REPO" PIFIRE_BRANCH="$PIFIRE_BRANCH" bash "$REPO_DIR/auto-install/install.sh"
	info "Al termine apri http://$(hostname -I | awk '{print $1}') e nel wizard scegli 'PiFire PCB 4.x.x Modular PCB + Orange Pi Zero 2W'."
fi

# ---------------------------------------------------------------------------
say "Fatto"
if [[ $REBOOT_NEEDED -eq 1 ]]; then
	warn "Riavvio necessario: sudo reboot"
fi
info "Verifica hardware: sudo python3 $REPO_DIR/auto-install/orangepi/opi_check.py"
