#!/usr/bin/env python3
'''
PiFire on Orange Pi: hardware check

Prints what PiFire needs from the board (GPIO controller, I2C, SPI, PWM,
serial console) and can exercise the relay outputs and the button/encoder
inputs of the PiFire PCB v4.x.x.  Run it on the Orange Pi:

  sudo python3 auto-install/orangepi/opi_check.py              # report only
  sudo python3 auto-install/orangepi/opi_check.py relays       # click each relay output
  sudo python3 auto-install/orangepi/opi_check.py inputs       # watch buttons / encoder

Relay test: do it with the 230 V side DISCONNECTED.  An LED or a multimeter
on the relay header is enough to see the outputs switch.
'''

import argparse
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from grillplat import opi_gpio  # noqa: E402

# PiFire PCB v4.x.x pins (Raspberry Pi BCM numbers, see wizard/wizard_manifest.json)
PCB_V4 = {
	'outputs': {'power': 22, 'auger': 23, 'igniter': 18, 'fan': 26},
	'inputs': {'button up / encoder CLK': 14, 'button enter / encoder SW': 15, 'button down / encoder DT': 16},
	'other': {'PWM (DC fan)': 13, 'DC fan enable': 26, 'display DC': 24, 'display RST': 25,
			  'display LED': 5, '1-Wire': 4, 'shutdown': 17},
}


def read(path, default=None):
	try:
		with open(path) as f:
			return f.read().strip('\x00\n ')
	except OSError:
		return default


def run(cmd):
	try:
		return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
	except (OSError, subprocess.SubprocessError):
		return None


def section(title):
	print(f'\n=== {title} ===')


def report():
	section('Sistema')
	print(f'Scheda:  {read("/proc/device-tree/model", "sconosciuta")}')
	print(f'Kernel:  {os.uname().release}')
	os_release = dict(line.split('=', 1) for line in (read('/etc/os-release', '') or '').splitlines() if '=' in line)
	print(f'Sistema: {os_release.get("PRETTY_NAME", "?").strip(chr(34))}')
	for env in ('/boot/orangepiEnv.txt', '/boot/armbianEnv.txt', '/boot/dietpiEnv.txt'):
		content = read(env)
		if content is not None:
			print(f'Boot:    {env}')
			for line in content.splitlines():
				if line.split('=', 1)[0] in ('overlay_prefix', 'overlays', 'user_overlays', 'console', 'fdtfile'):
					print(f'         {line}')

	section('GPIO')
	chips = opi_gpio.list_gpiochips()
	print('Chip:    ' + (', '.join(chips) if chips else 'nessun /dev/gpiochip* trovato'))
	main = None
	try:
		import gpiod  # noqa: F401
		api = 2 if hasattr(gpiod, 'request_lines') else 1
		print(f'libgpiod Python: API v{api}')
		try:
			main = opi_gpio.find_main_chip()
			print(f'Controller principale: {main}  OK')
		except RuntimeError as e:
			print(f'Controller principale: NON TROVATO  ({e})')
	except ImportError:
		print('libgpiod Python: non installato (sudo apt install python3-libgpiod, oppure pip install gpiod)')
	info = None
	if main:
		chip_name = os.path.basename(main)
		# gpioinfo syntax differs between libgpiod tools v1 and v2
		info = run(['gpioinfo', chip_name]) or run(['gpioinfo', '-c', chip_name])
	busy = {}
	if info:
		for line in info.splitlines():
			parts = line.split()
			if line.strip().startswith('line') and len(parts) > 3 and '"' in line:
				# libgpiod v1/v2 gpioinfo formats differ; keep the offset and the quoted consumer
				try:
					offset = int(parts[1].rstrip(':'))
				except ValueError:
					continue
				quoted = [p for p in line.split('"')[1::2]]
				if len(quoted) >= 2 and quoted[1] not in ('unused', ''):
					busy[offset] = quoted[1]
				elif 'used' in line and 'unused' not in line and quoted:
					busy[offset] = quoted[-1]

	print('\nPin della PCB v4 sull\'Orange Pi Zero 2W:')
	print(f'  {"funzione":30} {"GPIO Pi":>8} {"pin":>4}  {"Orange Pi":9} {"note"}')
	for group in ('outputs', 'inputs', 'other'):
		for name, bcm in PCB_V4[group].items():
			physical = opi_gpio.bcm_to_physical(bcm)
			pin_name = opi_gpio.bcm_to_pin_name(bcm)
			notes = []
			if opi_gpio.is_console_pin(bcm):
				notes.append('console seriale')
			if name.startswith('PWM') and opi_gpio.bcm_to_pwm_channel(bcm) is None:
				notes.append('senza PWM hardware (usare pin 32)')
			offset = opi_gpio.pin_name_to_offset(pin_name)
			if offset in busy:
				notes.append(f'occupato da "{busy[offset]}"')
			print(f'  {name:30} {bcm:>8} {physical:>4}  {pin_name:9} {", ".join(notes)}')

	section('I2C')
	buses = sorted(glob.glob('/dev/i2c-*'))
	print('Bus:     ' + (', '.join(buses) if buses else 'nessuno: abilitare l\'overlay I2C1 (pin 3 e 5)'))
	for bus in buses:
		number = bus.rsplit('-', 1)[1]
		name = read(f'/sys/class/i2c-dev/i2c-{number}/name', '')
		scan = run(['i2cdetect', '-y', number])
		found = []
		if scan:
			for line in scan.splitlines()[1:]:
				found += [cell for cell in line.split()[1:] if cell not in ('--', 'UU')]
		print(f'  {bus} ({name}): ' + (', '.join('0x' + a for a in found) if found else 'nessun dispositivo')
			  + ('   <- ADS1115' if '48' in found else ''))

	section('SPI')
	spis = sorted(glob.glob('/dev/spidev*'))
	print('Device:  ' + (', '.join(spis) if spis else 'nessuno (serve solo per display SPI o MAX31865)'))

	section('PWM')
	chips = sorted(glob.glob('/sys/class/pwm/pwmchip*'))
	if not chips:
		print('Nessun controller PWM attivo (serve solo per la ventola DC)')
	for chip in chips:
		print(f'  {chip}: {read(os.path.join(chip, "npwm"), "?")} canali')

	section('Console seriale (pin 8 e 10)')
	cmdline = read('/proc/cmdline', '')
	console_on = 'console=ttyS0' in cmdline
	getty = run(['systemctl', 'is-active', 'serial-getty@ttyS0.service'])
	print(f'Kernel console su ttyS0: {"SI" if console_on else "no"}')
	print(f'Login seriale (serial-getty@ttyS0): {getty or "?"}')
	if console_on or getty == 'active':
		print('-> I pin 8 e 10 (tasti/encoder della PCB v4) non sono utilizzabili finché la console è attiva.')

	section('Rete')
	nm_state = run(['systemctl', 'is-active', 'NetworkManager'])
	print(f'NetworkManager: {nm_state or "non installato"}')
	for yaml_file in sorted(glob.glob('/etc/netplan/*.yaml')):
		renderers = [l.split(':', 1)[1].strip() for l in (read(yaml_file, '') or '').splitlines() if l.strip().startswith('renderer:')]
		print(f'Netplan {yaml_file}: renderer {", ".join(renderers) or "predefinito (networkd)"}')
	devices = run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device']) if nm_state == 'active' else None
	for line in (devices or '').splitlines():
		if ':wifi:' in line:
			print(f'Wi-Fi: {line}')
	print(f'Servizio rete di emergenza (pifire-wifi): {run(["systemctl", "is-active", "pifire-wifi"]) or "?"}')
	if nm_state != 'active':
		print('-> Senza NetworkManager la rete di emergenza non funziona: rilancia setup.sh, passo 6.')

	section('Temperatura CPU')
	for zone in sorted(glob.glob('/sys/class/thermal/thermal_zone*')):
		temp = read(os.path.join(zone, 'temp'))
		if temp and temp.lstrip('-').isdigit():
			print(f'  {read(os.path.join(zone, "type"), zone)}: {int(temp) / 1000:.1f} °C')


def relay_test(active_high, seconds):
	from grillplat.opi_gpio import OutputDevice
	print('ATTENZIONE: eseguire questo test con il lato 230 V SCOLLEGATO.')
	answer = input('Il 230 V è scollegato? Scrivi "si" per continuare: ').strip().lower()
	if answer not in ('si', 'sì', 's', 'yes', 'y'):
		print('Test annullato.')
		return
	devices = {}
	try:
		for name, bcm in PCB_V4['outputs'].items():
			devices[name] = OutputDevice(bcm, active_high=active_high, initial_value=False)
		for name, device in devices.items():
			print(f'{name:8} (GPIO{device.bcm_pin}, pin {opi_gpio.bcm_to_physical(device.bcm_pin)}, {device.pin_name}): ACCESO', flush=True)
			device.on()
			time.sleep(seconds)
			device.off()
			print(f'{name:8} spento')
			time.sleep(0.5)
	finally:
		for device in devices.values():
			device.off()
			device.close()
	print('Test relè completato: tutte le uscite sono spente.')


def input_test(seconds):
	from grillplat.opi_gpio import Button
	buttons = {}
	try:
		for name, bcm in PCB_V4['inputs'].items():
			buttons[name] = Button(bcm)
	except OSError as e:
		print(f'Impossibile leggere gli ingressi ({e}). Se riguarda i pin 8/10, disattivare prima la console seriale.')
		return
	print(f'Premi i tasti o gira la manopola per {seconds} secondi...')
	last = {name: b.is_active for name, b in buttons.items()}
	end = time.time() + seconds
	try:
		while time.time() < end:
			for name, button in buttons.items():
				state = button.is_active
				if state != last[name]:
					print(f'  {name}: {"ATTIVO" if state else "rilasciato"}')
					last[name] = state
			time.sleep(0.005)
	finally:
		for button in buttons.values():
			button.close()
	print('Fine test ingressi.')


def main():
	parser = argparse.ArgumentParser(description='Verifica hardware di PiFire su Orange Pi Zero 2W')
	parser.add_argument('test', nargs='?', choices=['report', 'relays', 'inputs'], default='report')
	parser.add_argument('--active-low', action='store_true', help='relè attivi bassi (la PCB v4 con modulo SSR è attiva alta)')
	parser.add_argument('--seconds', type=float, default=2.0, help='durata di ogni passo del test (default 2 s, 20 s per gli ingressi)')
	args = parser.parse_args()
	if args.test == 'report':
		report()
	elif args.test == 'relays':
		relay_test(active_high=not args.active_low, seconds=args.seconds)
	else:
		input_test(seconds=args.seconds if args.seconds != 2.0 else 20)


if __name__ == '__main__':
	main()
