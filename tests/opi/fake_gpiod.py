'''
Fake libgpiod Python bindings (v1 and v2 APIs) for testing the Orange Pi
platform without hardware.  Each fake keeps a record of the physical level
of every line, so tests can check what would appear on the header pins.
'''

import enum
import sys
import types

CHIP_LABELS = {
	'/dev/gpiochip0': '300b000.pinctrl',
	'/dev/gpiochip1': '7022000.pinctrl',
}


class PhysicalPins:
	'''Physical level (0 V = 0, 3.3 V = 1) of each line, keyed by (chip, offset).'''

	def __init__(self):
		self.level = {}
		self.inputs = {}
		self.requested = set()

	def reset(self):
		self.level.clear()
		self.inputs.clear()
		self.requested.clear()


PINS = PhysicalPins()


def build_v2():
	gpiod = types.ModuleType('gpiod')
	line_mod = types.ModuleType('gpiod.line')

	class Direction(enum.Enum):
		AS_IS = 1
		INPUT = 2
		OUTPUT = 3

	class Value(enum.Enum):
		INACTIVE = 0
		ACTIVE = 1

	class Bias(enum.Enum):
		AS_IS = 1
		UNKNOWN = 2
		DISABLED = 3
		PULL_UP = 4
		PULL_DOWN = 5

	line_mod.Direction = Direction
	line_mod.Value = Value
	line_mod.Bias = Bias

	class LineSettings:
		def __init__(self, direction=Direction.AS_IS, output_value=Value.INACTIVE, active_low=False, bias=Bias.AS_IS):
			self.direction = direction
			self.output_value = output_value
			self.active_low = active_low
			self.bias = bias

	class ChipInfo:
		def __init__(self, label):
			self.label = label

	class Chip:
		def __init__(self, path):
			if path not in CHIP_LABELS:
				raise FileNotFoundError(path)
			self.path = path

		def get_info(self):
			return ChipInfo(CHIP_LABELS[self.path])

		def __enter__(self):
			return self

		def __exit__(self, *exc):
			return False

	class LineRequest:
		def __init__(self, path, config):
			self.path = path
			self.config = config
			self.released = False
			for offset, settings in config.items():
				key = (path, offset)
				if key in PINS.requested:
					raise OSError(16, 'Device or resource busy')
				PINS.requested.add(key)
				if settings.direction == Direction.OUTPUT:
					PINS.level[key] = self._physical(settings, settings.output_value)
				elif settings.bias == Bias.PULL_UP:
					PINS.inputs.setdefault(key, 1)
				elif settings.bias == Bias.PULL_DOWN:
					PINS.inputs.setdefault(key, 0)

		@staticmethod
		def _physical(settings, value):
			active = value == Value.ACTIVE
			return int(active != settings.active_low)

		def set_value(self, offset, value):
			assert not self.released
			settings = self.config[offset]
			assert settings.direction == Direction.OUTPUT
			PINS.level[(self.path, offset)] = self._physical(settings, value)

		def get_value(self, offset):
			settings = self.config[offset]
			level = PINS.inputs.get((self.path, offset), 0)
			active = bool(level) != settings.active_low
			return Value.ACTIVE if active else Value.INACTIVE

		def release(self):
			self.released = True
			for offset in self.config:
				PINS.requested.discard((self.path, offset))

	def request_lines(path, consumer=None, config=None):
		return LineRequest(path, config)

	gpiod.Chip = Chip
	gpiod.LineSettings = LineSettings
	gpiod.request_lines = request_lines
	gpiod.line = line_mod
	return gpiod, line_mod


def build_v1():
	gpiod = types.ModuleType('gpiod')
	gpiod.LINE_REQ_DIR_IN = 1
	gpiod.LINE_REQ_DIR_OUT = 2
	gpiod.LINE_REQ_FLAG_ACTIVE_LOW = 4
	gpiod.LINE_REQ_FLAG_BIAS_PULL_UP = 32
	gpiod.LINE_REQ_FLAG_BIAS_PULL_DOWN = 64

	class Line:
		def __init__(self, path, offset):
			self.key = (path, offset)
			self.flags = 0
			self.type = None

		def request(self, consumer=None, type=None, flags=0, default_vals=None):
			if self.key in PINS.requested:
				raise OSError(16, 'Device or resource busy')
			PINS.requested.add(self.key)
			self.type = type
			self.flags = flags
			if type == gpiod.LINE_REQ_DIR_OUT:
				self.set_value(default_vals[0] if default_vals else 0)
			elif flags & gpiod.LINE_REQ_FLAG_BIAS_PULL_UP:
				PINS.inputs.setdefault(self.key, 1)

		def _active_low(self):
			return bool(self.flags & gpiod.LINE_REQ_FLAG_ACTIVE_LOW)

		def set_value(self, value):
			PINS.level[self.key] = int(bool(value) != self._active_low())

		def get_value(self):
			return int(bool(PINS.inputs.get(self.key, 0)) != self._active_low())

		def release(self):
			PINS.requested.discard(self.key)

	class Chip:
		def __init__(self, path):
			if path not in CHIP_LABELS:
				raise FileNotFoundError(path)
			self.path = path

		def label(self):
			return CHIP_LABELS[self.path]

		def get_line(self, offset):
			return Line(self.path, offset)

		def close(self):
			pass

	gpiod.Chip = Chip
	return gpiod


def install(version=2):
	'''Install the fake as the importable "gpiod" module and return it.'''
	PINS.reset()
	for name in ('gpiod', 'gpiod.line'):
		sys.modules.pop(name, None)
	if version == 2:
		gpiod, line_mod = build_v2()
		sys.modules['gpiod'] = gpiod
		sys.modules['gpiod.line'] = line_mod
	else:
		gpiod = build_v1()
		sys.modules['gpiod'] = gpiod
	return gpiod
