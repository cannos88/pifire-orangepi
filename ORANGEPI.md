# PiFire su Orange Pi Zero 2W

Questo repository è una copia privata di [PiFire](https://github.com/nebhead/PiFire) adattata per girare su un **Orange Pi Zero 2W** al posto del Raspberry Pi, per un **Traeger Pro 22** (230 V, ventola AC) con la PCB v4.x.x di PiFire e il modulo relè SSR.

## Rami

| Ramo | Contenuto |
|---|---|
| `main` | Copia esatta di PiFire originale (`nebhead/PiFire`), da cui prendiamo i loro aggiornamenti |
| `orangepi-dev` | Sviluppo del porting: qui arrivano le modifiche man mano |
| `orangepi-stable` | (più avanti) La versione che il grill installa e aggiorna |

Per allineare `main` al progetto originale: `git fetch upstream && git checkout main && git merge --ff-only upstream/main`.

## Stato

Fatto:
- **Modulo di piattaforma** `grillplat/orangepi_zero2w.py`: stessa interfaccia del modulo Raspberry, GPIO tramite libgpiod, PWM hardware via sysfs (per la futura ventola DC), temperatura CPU e Wi-Fi senza `vcgencmd`/`iwconfig`.
- **Mappa dei pin** `grillplat/opi_gpio.py`: le impostazioni restano in numeri GPIO Raspberry e vengono tradotte sul pin dell'Orange Pi nella stessa posizione dell'header. Verificata contro le tabelle ufficiali di wiringOP.
- **Wizard**: nuova scheda *"PiFire PCB 4.x.x Modular PCB + Orange Pi Zero 2W"*.
- **Installer**: `auto-install/install.sh` accetta `PIFIRE_REPO` / `PIFIRE_BRANCH` e salta `rpi.gpio` fuori dal Raspberry. Script di preparazione e di verifica in `auto-install/orangepi/`.
- **Test** senza hardware: `tests/opi/` (GPIO e sysfs simulati).

Prossimi passi: correzione dei guadagni PID in °C, riconoscimento dello spegnimento fiamma, simulatore del grill, modulo display HDMI 1024×600, comandi da Home Assistant via MQTT.

## Preparare l'Orange Pi

### 1. Sistema

1. Scarica l'immagine **Debian Bookworm server** per Orange Pi Zero 2W dal sito Orange Pi (in alternativa Armbian Bookworm minimal).
2. Scrivila sulla microSD con balenaEtcher o Raspberry Pi Imager.
3. Primo avvio con monitor e tastiera, oppure via cavo seriale. Collega il Wi-Fi con `sudo nmtui`, poi aggiorna con `sudo apt update && sudo apt full-upgrade`.
4. Da qui in poi lavori via SSH dal PC.

Per ora **non collegare niente all'header** a 40 pin.

### 2. Accesso al repository privato

Sull'Orange Pi:

```bash
sudo mkdir -p /root/.ssh && sudo ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519
sudo cat /root/.ssh/id_ed25519.pub
```

Su GitHub, in questo repository: **Settings → Deploy keys → Add deploy key**. Incolla la chiave e lascia **"Allow write access" disattivato**: l'Orange Pi può solo scaricare.

```bash
sudo GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new" \
  git clone -b orangepi-dev git@github.com:cannos88/pifire-orangepi.git /opt/pifire-setup
```

### 3. Preparazione e installazione

```bash
sudo bash /opt/pifire-setup/auto-install/orangepi/setup.sh
```

Lo script chiede conferma prima di ogni passo:
1. pacchetti di sistema (git, compilatore, strumenti I2C e GPIO);
2. componente Debian `contrib`, che serve all'installer;
3. disattivazione della console seriale, necessaria solo per tasti/encoder sui pin 8 e 10;
4. overlay I2C1 (pin 3 e 5, ADS1115) e SPI1;
5. verifica della chiave di accesso a GitHub;
6. installer di PiFire, dopo il riavvio se sono cambiate impostazioni di boot.

Se un overlay non viene riconosciuto, lo script mostra l'elenco di quelli disponibili. Mandamelo e aggiorno lo script: i nomi cambiano tra l'immagine Orange Pi e Armbian.

### 4. Verifica

```bash
sudo python3 /opt/pifire-setup/auto-install/orangepi/opi_check.py
```

Il risultato riassume scheda, controller GPIO, I2C (con l'ADS1115 a `0x48` quando è collegato), SPI, PWM, console seriale e la mappa dei pin. **Mandamelo dopo il primo avvio.**

Con le schede montate:

```bash
# Ogni relè si accende per 2 secondi. SOLO con il lato 230 V scollegato.
sudo python3 /opt/pifire-setup/auto-install/orangepi/opi_check.py relays

# Mostra le pressioni dei tasti e gli scatti dell'encoder per 20 secondi
sudo python3 /opt/pifire-setup/auto-install/orangepi/opi_check.py inputs
```

### 5. Wizard di PiFire

Apri `http://<indirizzo-dell-orange-pi>` e nel wizard scegli:
- **Piattaforma**: *PiFire PCB 4.x.x Modular PCB + Orange Pi Zero 2W*
- **System Type**: *Orange Pi Zero 2W*
- **Relay Type**: *Active High* (modulo SSR della PCB v4)
- **Fan Type**: *AC Fan*
- **Unità**: °C

## Mappa dei pin (PCB v4 → Orange Pi Zero 2W)

| Funzione | GPIO Raspberry | Pin fisico | Pin Orange Pi | Note |
|---|---|---|---|---|
| Relè Power | 22 | 15 | PI5 | |
| Relè Coclea | 23 | 16 | PI14 | |
| Relè Candeletta | 18 | 12 | PI1 | |
| Relè Ventola | 26 | 37 | PI16 | |
| Tasto su / encoder CLK | 14 | 8 | PH0 | console seriale |
| Tasto invio / encoder SW | 15 | 10 | PH1 | console seriale |
| Tasto giù / encoder DT | 16 | 36 | PC12 | |
| I2C SDA / SCL | 2 / 3 | 3 / 5 | PI8 / PI7 | I2C1 |
| PWM ventola DC | 13 | 33 | PI12 | **senza PWM hardware**: ponticello al pin 32 (PI11, PWM1) |
| 1-Wire | 4 | 7 | PI13 | non configurato (non serve per il Traeger) |

## Note hardware

- **Pin 8 e 10**: sono la console seriale di debug. Anche con la console disattivata, U-Boot trasmette sul pin 8 all'avvio. **Metti una resistenza da 1 kΩ in serie sul filo CLK dell'encoder**: evita un cortocircuito se all'accensione l'encoder è fermo con il contatto chiuso verso massa.
- **Pin 33**: niente PWM hardware sull'Orange Pi. Serve solo per l'upgrade futuro a ventola DC: ponticello verso il pin 32 e uscita PWM impostata su GPIO12 (oppure `"pwm_pin": 12` nelle impostazioni della piattaforma).
- **All'avvio** i pin restano in alta impedenza e il modulo SSR ha resistenze di pull-down sulle basi dei transistor, quindi i relè restano spenti finché PiFire non li comanda. Non abilitare overlay UART2 o PWM4: userebbero i pin 15 e 16, che pilotano i relè.

## Test senza hardware

```bash
python -m pytest tests/opi
```

## Grafica

- Display: bozze in `docs-orangepi/display-mockups/` (`python render_5in.py` le rigenera). Font Barlow (SIL Open Font License) e icone FontAwesome già incluse in PiFire. Le bozze da 5″ sono a 800×480: vanno adattate al display scelto (1024×600).
- Web app: mockup interattivo [PiFire Web App](https://claude.ai/artifact/Jf3y8ExsQ29xC1qzHDu1rX).
- Piano di lavoro e lista della spesa: [PiFire Orange Pi](https://claude.ai/artifact/RDBWNfmtbJo1nxR27YnyJm).
