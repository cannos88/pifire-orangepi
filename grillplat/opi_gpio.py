#!/usr/bin/env python3

'''
*****************************************
 PiFire Orange Pi GPIO Support
*****************************************

 Description: GPIO helpers for running PiFire on Orange Pi boards (currently
 the Orange Pi Zero 2W, Allwinner H618) instead of a Raspberry Pi.

 PiFire settings, the wizard and the PCB definitions all use Raspberry Pi BCM
 GPIO numbers.  To keep every existing board configuration valid, this module
 translates a BCM number to the physical pin on the 40-pin header, and the
 physical pin to the Orange Pi GPIO line (bank + index on the H618 pin
 controller).  The rest of PiFire never needs to know which board it runs on.

 GPIO access goes through libgpiod (the character device API), which works on
 any modern Linux kernel.  Both the v2 Python bindings (pip "gpiod" >= 2.0) and
 the older v1 bindings (Debian "python3-libgpiod") are supported.

 The classes below mimic the small part of the gpiozero API that the
 Raspberry Pi platform module uses (OutputDevice, Button), so the Orange Pi
 platform module stays a close copy of the original.

*****************************************
'''

import glob
import os
import threading

'''
==============================
  Pin Maps
==============================
'''

# Raspberry Pi BCM GPIO number -> physical pin on the 40-pin header.
# This is the standard layout shared by every 40-pin Raspberry Pi.
BCM_TO_PHYSICAL = {
	2: 3, 3: 5, 4: 7, 17: 11, 27: 13, 22: 15, 10: 19, 9: 21, 11: 23,
	0: 27, 5: 29, 6: 31, 13: 33, 19: 35, 26: 37,
	14: 8, 15: 10, 18: 12, 23: 16, 24: 18, 25: 22, 8: 24, 7: 26,
	1: 28, 12: 32, 16: 36, 20: 38, 21: 40,
}

# Orange Pi Zero 2W: physical pin -> H618 pin name (bank letter + index).
# Source: orangepi-xunlong/wiringOP (physToWpi_ZERO_2_W + pinToGpio_ZERO_2_W).
# Pins 1, 2, 4, 6, 9, 14, 17, 20, 25, 30, 34 and 39 are power / ground.
ZERO2W_PHYSICAL_TO_PIN = {
	3: 'PI8',    # SDA.1
	5: 'PI7',    # SCL.1
	7: 'PI13',   # PWM3
	8: 'PH0',    # TXD.0 (debug console)
	10: 'PH1',   # RXD.0 (debug console)
	11: 'PH2',   # TXD.5
	12: 'PI1',
	13: 'PH3',   # RXD.5
	15: 'PI5',   # TXD.2
	16: 'PI14',  # PWM4
	18: 'PH4',
	19: 'PH7',   # SPI1 MOSI
	21: 'PH8',   # SPI1 MISO
	22: 'PI6',   # RXD.2
	23: 'PH6',   # SPI1 CLK
	24: 'PH5',   # SPI1 CS0
	26: 'PH9',   # SPI1 CS1
	27: 'PI10',  # SDA.2
	28: 'PI9',   # SCL.2
	29: 'PI0',
	31: 'PI15',
	32: 'PI11',  # PWM1
	33: 'PI12',  # no hardware PWM on this board
	35: 'PI2',
	36: 'PC12',
	37: 'PI16',
	38: 'PI4',
	40: 'PI3',
}

# Physical pins that can drive a hardware PWM channel on the Zero 2W
# (physical pin -> PWM channel of the H618 PWM controller).
ZERO2W_PHYSICAL_TO_PWM = {
	7: 3,
	16: 4,
	32: 1,
}

# Physical pins shared with the debug console.  They work as GPIO only after
# the serial console has been disabled, and U-Boot still uses them at boot.
ZERO2W_CONSOLE_PINS = (8, 10)

BOARDS = {
	'zero2w': {
		'name': 'Orange Pi Zero 2W',
		'pins': ZERO2W_PHYSICAL_TO_PIN,
		'pwm': ZERO2W_PHYSICAL_TO_PWM,
		'console_pins': ZERO2W_CONSOLE_PINS,
		# Label of the main pin controller (the one holding banks A..I).
		'chip_labels': ('300b000.pinctrl',),
	},
}

DEFAULT_BOARD = 'zero2w'


def pin_name_to_offset(pin_name):
	'''
	Convert an Allwinner pin name (e.g. 'PI12') to its line offset on the main
	pin controller.  Allwinner pin controllers expose 32 lines per bank, so the
	offset is bank_index * 32 + pin_index (PA0 = 0, PH4 = 228, PI12 = 268).
	'''
	pin_name = pin_name.strip().upper()
	if len(pin_name) < 3 or pin_name[0] != 'P' or not pin_name[1].isalpha() or not pin_name[2:].isdigit():
		raise ValueError(f'Invalid Allwinner pin name: {pin_name}')
	bank = ord(pin_name[1]) - ord('A')
	index = int(pin_name[2:])
	if not 0 <= index < 32:
		raise ValueError(f'Invalid pin index in {pin_name}')
	return bank * 32 + index


def bcm_to_physical(bcm):
	try:
		return BCM_TO_PHYSICAL[int(bcm)]
	except (KeyError, ValueError, TypeError):
		raise ValueError(f'GPIO{bcm} is not a valid Raspberry Pi BCM GPIO on the 40-pin header')


def bcm_to_pin_name(bcm, board=DEFAULT_BOARD):
	physical = bcm_to_physical(bcm)
	pins = BOARDS[board]['pins']
	if physical not in pins:
		raise ValueError(f'Physical pin {physical} (GPIO{bcm}) is not a GPIO on the {BOARDS[board]["name"]}')
	return pins[physical]


def bcm_to_pwm_channel(bcm, board=DEFAULT_BOARD):
	'''
	Return the hardware PWM channel for a BCM GPIO, or None when that header
	pin has no hardware PWM on this board.
	'''
	return BOARDS[board]['pwm'].get(bcm_to_physical(bcm))


def is_console_pin(bcm, board=DEFAULT_BOARD):
	return bcm_to_physical(bcm) in BOARDS[board]['console_pins']


'''
==============================
  libgpiod Backend
==============================
'''

def _import_gpiod():
	import gpiod  # Imported lazily so the pin maps can be used without libgpiod installed
	return gpiod


def _gpiod_api_version(gpiod):
	# v2 bindings expose request_lines(); v1 bindings expose Chip.get_line()
	return 2 if hasattr(gpiod, 'request_lines') else 1


def _chip_label(gpiod, path):
	if _gpiod_api_version(gpiod) == 2:
		with gpiod.Chip(path) as chip:
			return chip.get_info().label
	chip = gpiod.Chip(path)
	try:
		label = chip.label
		return label() if callable(label) else label
	finally:
		chip.close()


def list_gpiochips():
	return sorted(glob.glob('/dev/gpiochip*'), key=lambda p: int(''.join(c for c in p if c.isdigit()) or 0))


def find_main_chip(board=DEFAULT_BOARD, gpiod=None):
	'''
	Return the /dev/gpiochipN path of the board's main pin controller.
	The chip number is not stable across kernels, so it is found by label.
	'''
	gpiod = gpiod or _import_gpiod()
	labels = BOARDS[board]['chip_labels']
	found = []
	for path in list_gpiochips():
		try:
			label = _chip_label(gpiod, path)
		except Exception:
			continue
		found.append(f'{path}={label}')
		if any(wanted in label for wanted in labels):
			return path
	raise RuntimeError(f'Pin controller {labels} not found. Available GPIO chips: {", ".join(found) or "none"}')


class GPIOLine:
	'''
	One requested GPIO line.  Values are logical: True = active.  When the line
	is active low, active means the pin is driven to 0 V.
	'''

	def __init__(self, offset, direction, chip_path=None, active_low=False, initial_value=False,
				 bias=None, consumer='pifire', board=DEFAULT_BOARD, gpiod=None):
		self._gpiod = gpiod or _import_gpiod()
		self._api = _gpiod_api_version(self._gpiod)
		self.offset = offset
		self.direction = direction  # 'out' or 'in'
		self.active_low = active_low
		self.chip_path = chip_path or find_main_chip(board, self._gpiod)
		self._lock = threading.Lock()
		self._value = bool(initial_value)
		if self._api == 2:
			self._request_v2(consumer, bias)
		else:
			self._request_v1(consumer, bias)

	def _request_v2(self, consumer, bias):
		g = self._gpiod
		from gpiod.line import Direction, Value, Bias
		settings = {'active_low': self.active_low}
		if self.direction == 'out':
			settings['direction'] = Direction.OUTPUT
			settings['output_value'] = Value.ACTIVE if self._value else Value.INACTIVE
		else:
			settings['direction'] = Direction.INPUT
			if bias == 'pull_up':
				settings['bias'] = Bias.PULL_UP
			elif bias == 'pull_down':
				settings['bias'] = Bias.PULL_DOWN
		self._request = g.request_lines(
			self.chip_path,
			consumer=consumer,
			config={self.offset: g.LineSettings(**settings)}
		)

	def _request_v1(self, consumer, bias):
		g = self._gpiod
		chip = g.Chip(self.chip_path)
		self._chip = chip
		line = chip.get_line(self.offset)
		flags = 0
		if self.active_low:
			flags |= g.LINE_REQ_FLAG_ACTIVE_LOW
		if self.direction == 'out':
			line.request(consumer=consumer, type=g.LINE_REQ_DIR_OUT, flags=flags,
						 default_vals=[1 if self._value else 0])
		else:
			if bias == 'pull_up' and hasattr(g, 'LINE_REQ_FLAG_BIAS_PULL_UP'):
				flags |= g.LINE_REQ_FLAG_BIAS_PULL_UP
			elif bias == 'pull_down' and hasattr(g, 'LINE_REQ_FLAG_BIAS_PULL_DOWN'):
				flags |= g.LINE_REQ_FLAG_BIAS_PULL_DOWN
			line.request(consumer=consumer, type=g.LINE_REQ_DIR_IN, flags=flags)
		self._line = line

	def set(self, value):
		value = bool(value)
		with self._lock:
			if self._api == 2:
				from gpiod.line import Value
				self._request.set_value(self.offset, Value.ACTIVE if value else Value.INACTIVE)
			else:
				self._line.set_value(1 if value else 0)
			self._value = value

	def get(self):
		with self._lock:
			if self.direction == 'out':
				return self._value
			if self._api == 2:
				from gpiod.line import Value
				return self._request.get_value(self.offset) == Value.ACTIVE
			return bool(self._line.get_value())

	def close(self):
		with self._lock:
			try:
				if self._api == 2:
					self._request.release()
				else:
					self._line.release()
					self._chip.close()
			except Exception:
				pass


'''
==============================
  gpiozero-like Devices
==============================
'''

class OutputDevice:
	'''
	Minimal replacement for gpiozero.OutputDevice addressed by BCM number.
	The line is requested already in its inactive state, so a relay never
	switches on while PiFire starts.
	'''

	def __init__(self, bcm_pin, active_high=True, initial_value=False, board=DEFAULT_BOARD, gpiod=None, chip_path=None):
		self.bcm_pin = int(bcm_pin)
		self.pin_name = bcm_to_pin_name(self.bcm_pin, board)
		self._line = GPIOLine(pin_name_to_offset(self.pin_name), 'out', chip_path=chip_path,
							  active_low=not active_high, initial_value=initial_value, board=board, gpiod=gpiod)

	def on(self):
		self._line.set(True)

	def off(self):
		self._line.set(False)

	def toggle(self):
		self._line.set(not self._line.get())

	@property
	def value(self):
		return int(self._line.get())

	@property
	def is_active(self):
		return self._line.get()

	def close(self):
		self._line.close()


class Button:
	'''
	Minimal replacement for gpiozero.Button: input with pull-up, active when
	the pin is pulled to ground (gpiozero's default behaviour).
	'''

	def __init__(self, bcm_pin, pull_up=True, board=DEFAULT_BOARD, gpiod=None, chip_path=None):
		self.bcm_pin = int(bcm_pin)
		self.pin_name = bcm_to_pin_name(self.bcm_pin, board)
		self._line = GPIOLine(pin_name_to_offset(self.pin_name), 'in', chip_path=chip_path,
							  active_low=pull_up, bias='pull_up' if pull_up else 'pull_down',
							  board=board, gpiod=gpiod)

	@property
	def is_active(self):
		return self._line.get()

	@property
	def is_pressed(self):
		return self.is_active

	def close(self):
		self._line.close()


'''
==============================
  Hardware PWM (sysfs)
==============================
'''

class SysfsPWM:
	'''
	Hardware PWM through /sys/class/pwm, with the same calls as the
	rpi_hardware_pwm.HardwarePWM class used by the Raspberry Pi module
	(start, stop, change_duty_cycle, change_frequency; duty cycle in percent).
	The PWM overlay for the channel must be enabled in the boot configuration.
	'''

	def __init__(self, pwm_channel, hz, chip=None, sysfs_root='/sys/class/pwm'):
		self.channel = int(pwm_channel)
		self.sysfs_root = sysfs_root
		self.chip_path = os.path.join(sysfs_root, chip) if chip else self._find_chip()
		self.pwm_path = os.path.join(self.chip_path, f'pwm{self.channel}')
		self._duty_cycle = 0.0
		if not os.path.isdir(self.pwm_path):
			self._write(os.path.join(self.chip_path, 'export'), self.channel)
		self.change_frequency(hz)

	def _find_chip(self):
		chips = sorted(glob.glob(os.path.join(self.sysfs_root, 'pwmchip*')))
		for chip in chips:
			try:
				with open(os.path.join(chip, 'npwm')) as f:
					if int(f.read().strip()) > self.channel:
						return chip
			except (OSError, ValueError):
				continue
		raise RuntimeError(f'No PWM controller with channel {self.channel} found in {self.sysfs_root}. '
						   'Enable the PWM overlay for this pin in the boot configuration.')

	@staticmethod
	def _write(path, value):
		with open(path, 'w') as f:
			f.write(str(value))

	def _attr(self, name):
		return os.path.join(self.pwm_path, name)

	def change_frequency(self, hz):
		hz = float(hz)
		if hz <= 0:
			raise ValueError('PWM frequency must be greater than 0')
		self.period_ns = int(1e9 / hz)
		self.hz = hz
		# Duty cycle must never exceed the period, so clear it before changing the period
		self._write(self._attr('duty_cycle'), 0)
		self._write(self._attr('period'), self.period_ns)
		self.change_duty_cycle(self._duty_cycle)

	def change_duty_cycle(self, duty_cycle):
		duty_cycle = max(0.0, min(100.0, float(duty_cycle)))
		self._duty_cycle = duty_cycle
		self._write(self._attr('duty_cycle'), int(self.period_ns * duty_cycle / 100))

	def start(self, initial_duty_cycle):
		self.change_duty_cycle(initial_duty_cycle)
		self._write(self._attr('enable'), 1)

	def stop(self):
		try:
			self._write(self._attr('enable'), 0)
		except OSError:
			pass


class StoppableThread(threading.Thread):
	'''Replacement for gpiozero.threads.GPIOThread (a thread with a stop event).'''

	def __init__(self, target, args=()):
		super().__init__(target=target, args=args, daemon=True)
		self.stopping = threading.Event()

	def stop(self, timeout=10):
		self.stopping.set()
		if self.is_alive() and threading.current_thread() is not self:
			self.join(timeout)
