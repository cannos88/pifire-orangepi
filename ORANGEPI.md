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
- **PID in °C**: i controller ora lavorano sempre in °F internamente, come i loro parametri. Prima, in °C, PB e finestre (pensati in °F) davano un controllo diverso da quello previsto. Tolto anche il "colpo" derivativo del primo ciclo (partiva da un valore fittizio di 150°).
- **Fiamma spenta**: nuovo rilevatore (`controller/flameout.py`, attivo di default in Hold).
- **Comandi da Home Assistant** via MQTT, con regole di sicurezza.
- **Simulatore del grill** (`tools/grill_sim`) e **test automatici** su GitHub a ogni push.
- **Web app**: dashboard *Moderna* e tema scuro *Ember* per tutte le pagine (vedi sotto).
- **Rete Wi-Fi di emergenza**: se il grill resta senza Wi-Fi accende la rete aperta *PiFire-Setup* per sceglierne una nuova dal telefono (vedi sotto).
- **Correzioni a PiFire**: in °C il target di una sonda finiva sulla temperatura del grill; due comandi ravvicinati (es. target e attivazione) si annullavano a vicenda.
- **Sicurezza e pulizia**: corrette falle di PiFire originale nella web app, librerie aggiornate, controllo settimanale delle vulnerabilità (vedi *Sicurezza e dipendenze*).

Prossimi passi: modulo display HDMI 1024×600, traduzione italiana e app installabile, taratura del simulatore sulle prime cotture vere.

## Preparare l'Orange Pi

### 1. Sistema

Sistema di riferimento: **Armbian, Debian 13 "trixie" Minimal** (kernel mainline), da [armbian.com/orangepizero2w](https://www.armbian.com/orangepizero2w/).

1. Scrivi l'immagine sulla microSD con balenaEtcher o Raspberry Pi Imager.
2. Primo avvio con monitor HDMI e tastiera USB (sulla porta USB-C dati, con adattatore OTG). Armbian chiede la password di root, crea il tuo utente e propone la configurazione del Wi-Fi.
3. Aggiorna con `sudo apt update && sudo apt full-upgrade`.
4. Da qui in poi lavori via SSH dal PC.
5. A sistema funzionante, blocca gli aggiornamenti del kernel con `sudo armbian-config` (System → Freeze kernel). Il driver Wi-Fi della Zero 2W è esterno al kernel ufficiale: un aggiornamento automatico del kernel durante la stagione dei barbecue potrebbe romperlo. Gli altri pacchetti continuano ad aggiornarsi.

L'immagine Debian ufficiale di Orange Pi (Bookworm, kernel 6.1) va bene lo stesso: script e modulo riconoscono entrambe.

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
6. rete Wi-Fi di emergenza: NetworkManager e servizio `pifire-wifi` (vedi [Wi-Fi e rete di emergenza](#wi-fi-e-rete-di-emergenza));
7. installer di PiFire, dopo il riavvio se sono cambiate impostazioni di boot o di rete.

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

## Fiamma spenta

PiFire originale si accorge che il fuoco è spento solo quando il grill scende sotto la temperatura di sicurezza dell'avvio (al massimo 38 °C). Nel frattempo il PID vede il grill raffreddarsi e manda la coclea al massimo, riempiendo il braciere di pellet crudo; alla riaccensione può prendere fuoco tutto insieme.

Il rilevatore guarda l'andamento in Hold:
1. **Sospetto**: la temperatura scende in modo costante per 2,5 minuti con la coclea alta. PiFire riduce il pellet alla quantità che teneva la temperatura prima (appresa durante la cottura).
2. **Conferma**: se dopo 3 minuti la temperatura continua a scendere anche con quel pellet, parte la riaccensione (o l'errore, se i tentativi sono finiti), come per il controllo di sicurezza originale.
3. **Coperchio aperto**: fa scendere la temperatura molto più in fretta di un fuoco spento, quindi un calo rapido mette in pausa il rilevatore per 5 minuti.

Nel simulatore (fuoco spento a 110 °C): PiFire originale riaccende dopo 28 minuti con circa 450 g di pellet nel braciere e un picco di 320 °C alla riaccensione; con il rilevatore riaccende dopo circa 6 minuti con circa 50 g e un picco di 190 °C. Coperchio aperto da 1 a 10 minuti: nessun falso allarme. Si disattiva con `"flameout_detect": false` nella sezione `safety` di `settings.json`.

## Wi-Fi e rete di emergenza

Il passo 6 di `setup.sh` affida la rete a NetworkManager (l'immagine Armbian *Minimal* usa systemd-networkd; la rete già configurata resta) e installa il servizio `pifire-wifi`.

**Se cambi la password del router, o porti il grill su un'altra rete:**
1. il grill prova le reti salvate; dopo **3 minuti** senza Wi-Fi accende la rete **PiFire-Setup**, aperta, senza password;
2. col telefono ti colleghi a *PiFire-Setup*: si apre da sola la pagina Wi-Fi del grill (se non si apre, vai su `http://10.42.0.1`);
3. scegli la rete, scrivi la password e premi *Collega*: la rete di emergenza si spegne e il grill si collega;
4. ricollega il telefono alla rete di casa e apri `http://<nome-del-grill>.local` (l'indirizzo comparirà anche sul display).

Se la password è sbagliata, *PiFire-Setup* ricompare entro un minuto. Se il router era solo spento, il grill lo ritrova da solo: ogni 5 minuti spegne la rete di emergenza per un minuto e riprova le reti salvate (non lo fa mentre qualcuno sta usando la pagina).

**Meglio ancora, prima di cambiare la password:** da *Dashboard → Wi-Fi* (`http://<nome-del-grill>.local/wifi`) aggiungi la rete con la password nuova e premi *Salva per dopo*. Il grill resta sulla rete attuale e passa a quella nuova appena serve.

**Sicurezza:** chi si collega a *PiFire-Setup* vede solo la pagina Wi-Fi. Dashboard, comandi e impostazioni vengono rimandati lì, quindi dalla rete aperta il grill non si accende e non si comanda. La cottura in corso non si ferma se cade il Wi-Fi.

Il servizio scrive lo stato in Redis (`wifi:status`: modalità, rete, indirizzo, nome e QR della rete di emergenza): il display da 5″ lo userà per mostrare la schermata *"Collegati a PiFire-Setup e apri http://10.42.0.1"* con il QR per collegarsi.

Comandi utili via SSH: `systemctl status pifire-wifi`, `journalctl -u pifire-wifi -f`, `nmcli device wifi list`.

## Home Assistant

Nelle impostazioni MQTT di PiFire ci sono due nuovi interruttori:
- **Allow remote control**: aggiunge in Home Assistant le entità *Grill Mode* (select), *Hold Temperature* (number) e *Smoke Plus* (switch).
- **Also allow remote Startup**: disattivato di default.

Regole di sicurezza:
- temperatura target, Smoke e Hold sono accettati solo con il fuoco acceso;
- Shutdown è sempre accettato;
- Stop è rifiutato col fuoco acceso, perché va usato Shutdown che brucia il pellet rimasto;
- l'accensione da remoto funziona solo se l'hai abilitata.

L'esito di ogni comando (`OK`, `ERROR` o `REFUSED` con il motivo) viene pubblicato su `<id>/command/result`.

## Simulatore

Modello del grill (braciere, ritardo della coclea, inerzia termica, coperchio, fiamma spenta) che fa girare i controller veri di PiFire con la stessa logica di `control.py`. È tarato in modo che il PID standard tenga circa ±4 °C a 107 °C, il risultato che PiFire documenta su un Traeger reale. Serve a confrontare strategie, non a prevedere una cottura.

```bash
pip install -r tests/requirements.txt
python -m tools.grill_sim --compare pid pid_ac pid_sp pid_clamping --plot confronto.png
python -m tools.grill_sim --scenario flameout --no-flameout-detect   # comportamento originale
```

Nota: i parametri dei controller (PB, Td, Ti, finestre) sono **in °F** anche quando PiFire mostra i °C.

## Sicurezza e dipendenze

Corretto rispetto a PiFire originale:
- **Comandi di sistema dalla web app**: cambio ramo degli aggiornamenti e cancellazione delle ricette costruivano un comando di shell con testo preso dalla richiesta (es. `x; reboot`). Ora non passa più nulla dalla shell e il ramo deve esistere davvero.
- **Percorsi dei file**: download e cancellazione di ricette, cotture e log accettavano nomi come `../settings.json` o `/etc/passwd`. Ora sono limitati alla loro cartella (`common/safe_paths.py`).
- **Web app solo dietro nginx**: gunicorn ascolta su `127.0.0.1:8000` invece che su tutta la rete; si entra solo dalla porta 80/443.
- Ricerca dispositivi WLED: chiamava uno script inesistente, ora funziona. Caricamento di una cottura: salvava in una cartella sbagliata.

Librerie aggiornate per vulnerabilità note: Pillow 12.3.0, Flask 3.1.3, zeroconf 0.151.5, redis 6.4.0 (la 5.x si portava dietro PyJWT 2.9 vulnerabile), jQuery 3.7.1 (XSS della 3.4.1), Bootstrap 4.6.2. Tolto il pacchetto `uuid` di PyPI, un modulo Python 2 inutile (si usa quello della libreria standard).

Controlli automatici:
- il workflow dei test, ogni lunedì e a ogni push, installa le librerie del grill e le confronta con il database delle vulnerabilità (`pip-audit`); se ne trova una il run fallisce e GitHub ti manda una mail;
- **Dependabot** (`.github/dependabot.yml`) apre ogni settimana le pull request di aggiornamento verso `orangepi-dev`. Per gli avvisi di sicurezza attiva anche *Settings → Code security → Dependabot alerts* nel repository.

Limiti noti, da affrontare più avanti:
- la web app non ha login: chiunque sia sulla rete di casa può comandare il grill (come in PiFire originale);
- l'installer di PiFire dà all'utente della web app permessi di amministratore ampi (sudo per bash, apt, cp) per aggiornamenti e wizard;
- eventlet è deprecato e gunicorn dalla 24 non ha più il suo worker: gunicorn resta fermo alla 23 finché non si passa a un altro server;
- Bootstrap 4 non è più mantenuto (l'unica falla nota riguarda il carosello, con contenuti che qui non arrivano dall'utente); il passaggio a Bootstrap 5 tocca tutte le pagine classiche.

Nel codice di PiFire originale restano piccole cose inutilizzate (import, variabili): le lascio per non complicare l'importazione dei loro aggiornamenti. I moduli per hardware diverso (altri display, sonde, Raspberry) restano perché sono opzioni del wizard.

## Aggiornamenti OTA

Da *Admin → System Updates* il grill scarica il ramo scelto di questo repository e si riavvia, senza togliere la scheda.

Cosa arriva con un aggiornamento:
- **codice, pagine e grafica**: sempre;
- **librerie Python e passi di sistema**: solo se sono elencati in `updater/updater_manifest.json` per una *build* più nuova di quella installata. Per questo ogni volta che cambio una libreria o una configurazione di sistema aggiungo una voce al manifest e alzo il numero di build (un test lo controlla). La build 71 porta gli aggiornamenti di sicurezza delle librerie e lancia `auto-install/orangepi/ota-system.sh` (configurazione di supervisor e servizio Wi-Fi).

Cosa **non** si fa via OTA: il passaggio della rete da systemd-networkd a NetworkManager (passo 6 di `setup.sh`). Fatto senza nessuno davanti potrebbe lasciare il grill fuori dalla rete, quindi resta un passo da lanciare via SSH. Sull'installazione nuova lo fa già `setup.sh`.

Il primo `setup.sh` installa da `orangepi-dev`. Quando ci sarà una versione stabile (workflow *Promote to stable*), da *Admin → System Updates* si passa al ramo `orangepi-stable` e da lì in poi il grill riceve solo le versioni promosse.

## GitHub Actions

- **Orange Pi tests**: a ogni push su `orangepi-dev` e `orangepi-stable` gira la suite completa su Python 3.11 e 3.13. Il confronto del simulatore viene allegato alla run, con grafico e numeri.
- **Vulnerabilità**: stesso workflow, job *audit*, anche ogni lunedì mattina.
- **Promote to stable**: si lancia a mano dalla scheda Actions. Ripete i test e, solo se passano, porta `orangepi-stable` allo stato di `orangepi-dev` e crea un tag `stable-AAAAMMGG-HHMM`. Il grill installa e aggiorna da `orangepi-stable`.

Per vedere "Promote to stable" nella scheda Actions, imposta `orangepi-dev` come ramo predefinito: Settings → General → Default branch. Il workflow "Deploy static content to Pages" ereditato da PiFire fallisce sui repository privati senza GitHub Pages: si può disattivare dalla scheda Actions.

## Test senza hardware

```bash
pip install -r tests/requirements.txt
python -m pytest tests
```

## Web app

**Dashboard Moderna** (`dashboard/modern.json`, `blueprints/dash/templates/modern/`, `blueprints/dash/static/modern/`), quella del mockup approvato:
- temperatura del grill grande, modalità, tempo di cottura, target e Smoke+;
- controllo che cambia con lo stato: *Accendi il grill* / *Solo monitoraggio* da spento; conto alla rovescia durante accensione e spegnimento; con il fuoco acceso Affumicatura / Mantenimento / Spegnimento, − e + (il comando parte 1,3 s dopo l'ultimo tocco), preset e interruttore Smoke+;
- grafico di 30′, 90′ o 3 h con la linea tratteggiata del target;
- una scheda per sonda: tocca la scheda per impostare il target (con valori tipici per manzo, maiale, pollo, pulled pork); mostra il tempo stimato e diventa verde con *PRONTO* quando ci arriva;
- timer con 15′/30′/1 h o durata a scelta, con spegnimento o mantenimento in caldo alla fine;
- stato di ventola, coclea e candeletta, pellet usato nella cottura (stima dal tempo della coclea).

Accensione, spegnimento e Stop chiedono conferma. Stop col fuoco acceso avvisa che è meglio lo spegnimento.

**Tema Ember**: con *Settings → Theme → Dark* tutte le pagine prendono la stessa grafica (`static/css/ember.css`). La dashboard Moderna lo usa sempre. I font Barlow sono inclusi nel progetto (`static/font/barlow/`), quindi funziona anche senza internet; tolto dal CSS scuro di Bootstrap il caricamento di un font da Google.

Su un'installazione nuova sono già impostati dashboard Moderna e tema scuro. Su una esistente: *Settings → Dashboard → Moderna (Ember)* e *Settings → Theme*.

## Grafica

- Display: bozze in `docs-orangepi/display-mockups/` (`python render_5in.py` le rigenera). Font Barlow (SIL Open Font License) e icone FontAwesome già incluse in PiFire. Le bozze da 5″ sono a 800×480: vanno adattate al display scelto (1024×600).
- Web app: mockup interattivo [PiFire Web App](https://claude.ai/artifact/Jf3y8ExsQ29xC1qzHDu1rX), realizzato nella dashboard Moderna.
- Piano di lavoro e lista della spesa: [PiFire Orange Pi](https://claude.ai/artifact/RDBWNfmtbJo1nxR27YnyJm).
