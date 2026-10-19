#!/usr/bin/env python3

# *****************************************
# PiFire Orange Pi Zero 2W Platform Interface Library
# *****************************************
#
# Description: This library uses an Orange Pi Zero 2W (Allwinner H618) in
# place of a Raspberry Pi to control outputs and monitor inputs for PiFire.
#
# It is derived from PiFire's Raspberry Pi module (removed in this fork): same class,
# same functions, same settings.  Pins in settings.json stay Raspberry Pi BCM
# numbers, so the PiFire PCBs and the configuration wizard work unchanged;
# grillplat/opi_gpio.py translates them to the Orange Pi pins on the same
# physical header position.
#
# Relays (power, auger, igniter, and fan) are controlled via GPIO through
# libgpiod.  If a DC fan is installed, its 12V power is switched via GPIO and
# its speed via hardware PWM in sysfs.  As on the Raspberry Pi PWM board, the
# amplifier inverts the PWM signal, so PWM duty cycle = 100 - fan percent.
#
# Board notes (Orange Pi Zero 2W):
#  - Physical pin 33 (BCM13, the PCB v4 PWM pin) has no hardware PWM on this
#    board.  For a DC fan, link pin 33 to pin 32 (hardware PWM1) and set the
#    PWM output to GPIO12, or add 'pwm_pin' to the platform settings.
#  - Physical pins 8 and 10 (BCM14/15, buttons UP/ENTER on PCB v4) are the
#    debug serial console and only work as inputs once it is disabled.
#
# *****************************************

"""
	==============================
	  Imported Libraries
	==============================
"""

import os
from common import is_float, create_logger, get_os_info
from grillplat.opi_gpio import OutputDevice, Button, SysfsPWM, StoppableThread, \
	bcm_to_pwm_channel, bcm_to_physical, is_console_pin, find_main_chip

"""
	==============================
	  Class Definition
	==============================
"""

class GrillPlatform:

	def __init__(self, config):
		self.logger = create_logger('control')
		try:
			self.out_pins = config.get('outputs', None)  # Pins to control the PiFire outputs
			self.in_pins = config.get('inputs', None)  # Pins for input
			self.dc_fan = config.get('dc_fan', False)  # Save state for DC Fan
			self.frequency = config.get('frequency', 100)  # Save configured fan frequency
			self.standalone = config.get('standalone', True)  # Save configured state for Standalone
			self.gpiochip = config.get('gpiochip', None)  # Optional override, e.g. '/dev/gpiochip0'
			self.current = {}
		except:
			self.logger.error('Error parsing platform configuration.  Check your settings.json file.')
			raise

		# Resolve the pin controller once so every line uses the same chip
		if self.gpiochip is None:
			self.gpiochip = find_main_chip()
		self.logger.debug(f'Orange Pi platform using GPIO chip {self.gpiochip}')

		if not self.standalone:
			self.selector = Button(self.in_pins['selector'], chip_path=self.gpiochip)
		else:
			self.selector = None

		active_high = True if config.get('triggerlevel', 'HIGH') == 'HIGH' else False

		self.pwm = None
		self._ramp_thread = None
		if self.dc_fan:
			self.current_fan_speed_percent = 100  # Track the fan speed, sysfs PWM can't be read back reliably
			self.fan = OutputDevice(self.out_pins['dc_fan'], active_high=active_high, initial_value=False, chip_path=self.gpiochip)
			pwm_pin = config.get('pwm_pin', self.out_pins['pwm'])
			pwm_channel = bcm_to_pwm_channel(pwm_pin)
			if pwm_channel is None:
				message = (f'GPIO{pwm_pin} (physical pin {bcm_to_physical(pwm_pin)}) has no hardware PWM on the Orange Pi Zero 2W. '
						   'Link physical pin 33 to pin 32 and set the PWM output to GPIO12.')
				self.logger.error(message)
				raise ValueError(message)
			self.pwm = SysfsPWM(pwm_channel=pwm_channel, hz=self.frequency, chip=config.get('pwm_chip', None))
			self.logger.debug(f'Hardware PWM setup: Using PWM channel {pwm_channel} and PWM frequency {self.frequency}')
		else:
			self.fan = OutputDevice(self.out_pins['fan'], active_high=active_high, initial_value=False, chip_path=self.gpiochip)

		self.auger = OutputDevice(self.out_pins['auger'], active_high=active_high, initial_value=False, chip_path=self.gpiochip)
		self.igniter = OutputDevice(self.out_pins['igniter'], active_high=active_high, initial_value=False, chip_path=self.gpiochip)
		self.power = OutputDevice(self.out_pins['power'], active_high=active_high, initial_value=False, chip_path=self.gpiochip)

		for name in ('auger', 'igniter', 'power', 'fan'):
			pin = self.out_pins['dc_fan' if (name == 'fan' and self.dc_fan) else name]
			if is_console_pin(pin):
				self.logger.warning(f'{name} output is on GPIO{pin}, a debug console pin on the Orange Pi Zero 2W.  '
									'Disable the serial console or it may toggle at boot.')

	def auger_on(self):
		self.logger.debug('auger_on: Turning on auger')
		self.auger.on()

	def auger_off(self):
		self.logger.debug('auger_off: Turning off auger')
		self.auger.off()

	def fan_on(self, fan_speed_percent=100):
		self.fan.on()  # Turn on fan output pin to enable fan power
		if self.dc_fan:
			self._stop_ramp()
			self.logger.debug('fan_on: Turning on PWM fan with fan speed percent ' + str(fan_speed_percent))
			start_duty_cycle = float(100 - fan_speed_percent)  # PWM duty cycle = (100 - fan percent speed)
			self.pwm.start(start_duty_cycle)
			self.current_fan_speed_percent = fan_speed_percent

	def fan_off(self):
		self.fan.off()
		if self.dc_fan:
			self.logger.debug('fan_off: Turning off PWM fan')
			self._stop_ramp()
			self.pwm.stop()
			self.current_fan_speed_percent = 0

	def fan_toggle(self):
		self.fan.toggle()

	def set_duty_cycle(self, fan_speed_percent, override_ramping=True):
		# Called by control.py (override_ramping=True) and by the Smoke Plus ramp thread (False)
		if override_ramping:
			self._stop_ramp()
		self.logger.debug('set_duty_cycle: Changing fan speed percent to ' + str(fan_speed_percent))
		pwm_duty_cycle = float(100 - fan_speed_percent)  # Duty cycle is inverted due to PWM board amplifier circuitry
		self.pwm.change_duty_cycle(pwm_duty_cycle)
		self.current_fan_speed_percent = fan_speed_percent

	def pwm_fan_ramp(self, on_time=5, min_duty_cycle=20, max_duty_cycle=100):
		self.fan.on()
		self.logger.debug('pwm_fan_ramp: Starting fan ramp: on_time: ' + str(on_time) + ' min_duty_cycle: ' + str(min_duty_cycle) + ' max_duty_cycle: ' + str(max_duty_cycle))
		self._start_ramp(on_time=on_time, min_duty_cycle=min_duty_cycle, max_duty_cycle=max_duty_cycle)

	def set_pwm_frequency(self, frequency=30):
		self.logger.debug('set_pwm_frequency: Setting PWM signal frequency to ' + str(frequency))
		self.frequency = frequency
		if self.pwm is not None:
			self.pwm.change_frequency(frequency)

	def igniter_on(self):
		self.logger.debug('igniter_on: Turning on igniter')
		self.igniter.on()

	def igniter_off(self):
		self.logger.debug('igniter_off: Turning off igniter')
		self.igniter.off()

	def power_on(self):
		self.logger.debug('power_on: Powering on grill platform')
		self.power.on()

	def power_off(self):
		self.logger.debug('power_off: Powering off grill platform')
		self.power.off()

	def get_input_status(self):
		if self.in_pins['selector'] is not None and self.standalone == False:
			return self.selector.is_active
		return False

	def get_output_status(self):
		self.current = {}
		self.current['auger'] = self.auger.is_active
		self.current['igniter'] = self.igniter.is_active
		self.current['power'] = self.power.is_active
		self.current['fan'] = self.fan.is_active
		if self.dc_fan:
			self.current['pwm'] = self.current_fan_speed_percent
			self.current['frequency'] = self.frequency
		return self.current

	def _start_ramp(self, on_time, min_duty_cycle, max_duty_cycle, background=True):
		self._stop_ramp()
		self.logger.debug('_start_ramp: Starting fan ramp thread: on_time: ' + str(on_time) + ' min_duty_cycle: ' + str(min_duty_cycle) + ' max_duty_cycle: ' + str(max_duty_cycle))
		self.fan_on(min_duty_cycle)  # The setting passed in is a fan percent, not the eventual PWM duty cycle
		self._ramp_thread = StoppableThread(self._ramp_device, (on_time, min_duty_cycle, max_duty_cycle))
		self._ramp_thread.start()
		if not background:
			self._ramp_thread.join()
			self._ramp_thread = None

	def _stop_ramp(self):
		if self._ramp_thread:
			self.logger.debug('_stop_ramp: Stopping fan ramp')
			self._ramp_thread.stop()
			self._ramp_thread = None

	def _ramp_device(self, on_time, min_duty_cycle, max_duty_cycle, fps=25):
		duty_cycle = max_duty_cycle / 100
		sequence = [
			(1 - (i * (duty_cycle / fps) / on_time), 1 / fps)
			for i in range(int((fps * on_time) * (min_duty_cycle / max_duty_cycle)), int(fps * on_time))
		]
		sequence.append((1.0 - duty_cycle, 1 / fps))
		thread = self._ramp_thread
		for value, delay in sequence:
			new_duty_cycle = round(value, 4) * 100
			fan_speed_percent = float(100 - new_duty_cycle)  # Duty cycle is inverted due to PWM amplifier
			self.set_duty_cycle(fan_speed_percent, False)
			if thread is None or thread.stopping.wait(delay):
				break

	def cleanup(self):
		self._stop_ramp()
		self.power.close()
		self.igniter.close()
		self.auger.close()
		self.fan.close()
		if self.pwm is not None:
			self.pwm.stop()
		if self.selector is not None:
			self.selector.close()

	# MARK: System / Platform Commands
	"""
	==============================
	  System / Platform Commands
	==============================

		Commands callable by outside processes to get status or information, for the platform.

	"""

	def supported_commands(self, arglist):
		supported_commands = [
			'check_throttled',
			'check_wifi_quality',
			'check_cpu_temp',
			'supported_commands',
			'check_alive',
			'os_info',
			'network_info',
			'hardware_info'
		]

		data = {
			'result' : 'OK',
			'message' : 'Supported commands listed in "data".',
			'data' : {
				'supported_cmds' : supported_commands
			}
		}
		return data

	def check_throttled(self, arglist):
		'''
		The Orange Pi has no equivalent of vcgencmd get_throttled.  The H618 does
		not report under-voltage, so this always answers "not detected" with a
		note, keeping the WebUI and the API working.
		'''
		data = {
			'result' : 'OK',
			'message' : 'Under-voltage and throttling detection is not available on the Orange Pi.',
			'data' : {
				'cpu_under_voltage' : False,
				'cpu_throttled' : False
			}
		}
		self.logger.debug(f'Check Throttled Called. [data = {data}]')
		return data

	@staticmethod
	def _read_wifi_quality(interface='wlan0', proc_path='/proc/net/wireless'):
		'''
		Read the link quality from /proc/net/wireless (no iwconfig needed).
		Returns (quality, maximum) or None.  The kernel reports quality out of 70
		for most drivers.
		'''
		try:
			with open(proc_path) as f:
				for line in f:
					if line.strip().startswith(interface + ':'):
						fields = line.split()
						quality = float(fields[2].rstrip('.'))
						return int(quality), 70
		except (OSError, IndexError, ValueError):
			pass
		return None

	def check_wifi_quality(self, arglist):
		data = {
			'result' : 'ERROR',
			'message' : 'Unable to obtain wifi quality data.',
			'data' : {}
		}
		reading = self._read_wifi_quality()
		if reading is not None:
			quality_value, quality_max = reading
			percentage = min(100.0, (quality_value / quality_max) * 100)
			data['result'] = 'OK'
			data['message'] = 'Successfully obtained wifi quality data.'
			data['data']['wifi_quality_value'] = quality_value
			data['data']['wifi_quality_max'] = quality_max
			data['data']['wifi_quality_percentage'] = round(percentage, 2)
		self.logger.debug(f'Check Wifi Quality Called. [data = {data}]')
		return data

	@staticmethod
	def _read_cpu_temp(thermal_root='/sys/class/thermal'):
		'''
		Read the CPU temperature in degrees C from the thermal zones, preferring
		the CPU zone.  Returns None if no zone can be read.
		'''
		zones = []
		try:
			zones = sorted(z for z in os.listdir(thermal_root) if z.startswith('thermal_zone'))
		except OSError:
			return None
		fallback = None
		for zone in zones:
			try:
				with open(os.path.join(thermal_root, zone, 'temp')) as f:
					temp = int(f.read().strip()) / 1000
				zone_type = ''
				try:
					with open(os.path.join(thermal_root, zone, 'type')) as f:
						zone_type = f.read().strip().lower()
				except OSError:
					pass
				if 'cpu' in zone_type:
					return temp
				if fallback is None:
					fallback = temp
			except (OSError, ValueError):
				continue
		return fallback

	def check_cpu_temp(self, arglist):
		temp = self._read_cpu_temp()
		if temp is not None and is_float(temp):
			result = 'OK'
			message = 'Successfully obtained CPU temperature.'
			temp = float(temp)
		else:
			result = 'ERROR'
			message = 'Error obtaining CPU temperature.'
			temp = 0.0

		data = {
			'result' : result,
			'message' : message,
			'data' : {
				'cpu_temp' : round(float(temp), 1)
			}
		}
		self.logger.debug(f'Check CPU Temp Called. [data = {data}]')
		return data

	def check_alive(self, arglist):
		'''
		 Simple check to see if the platform is up and running.
		'''
		data = {
			'result' : 'OK',
			'message' : 'The control script is running.',
			'data' : {}
		}
		return data

	def os_info(self, arglist):
		"""
		Retrieve OS information such as version and architecture.
		"""
		data = {
			'result' : 'OK',
			'message' : 'OS information retrieved successfully.',
			'data' : get_os_info()
		}
		return data

	def network_info(self, arglist):
		"""
		Retrieve network information such as IP address and MAC address.
		"""
		from grillplat.netinfo import interfaces_info

		net_info = interfaces_info()

		data = {
			'result' : 'OK',
			'message' : 'Network information retrieved successfully.',
			'data' : net_info
		}
		return data

	def hardware_info(self, arglist):
		"""
		Retrieve hardware information such as board model, CPU and RAM size.
		"""
		import psutil

		cpu_info = {
			'hardware': 'Unknown',
			'model': 'Unknown',
			'model_name': 'Unknown',
			'cores': psutil.cpu_count(logical=True),
			'frequency': psutil.cpu_freq().current if psutil.cpu_freq() else 'Unknown'
		}

		# On ARM boards with a device tree, the board model lives here (e.g. "OrangePi Zero2W")
		try:
			with open('/proc/device-tree/model') as f:
				cpu_info['model'] = f.read().strip('\x00\n ')
		except OSError:
			pass

		try:
			with open('/proc/cpuinfo') as f:
				for line in f:
					lower = line.lower()
					if lower.startswith('hardware') and ':' in line:
						cpu_info['hardware'] = line.split(':', 1)[1].strip()
					elif lower.startswith('model name') and ':' in line:
						cpu_info['model_name'] = line.split(':', 1)[1].strip()
		except OSError:
			pass
		if cpu_info['hardware'] == 'Unknown':
			cpu_info['hardware'] = 'Allwinner H618'

		mem_info = psutil.virtual_memory()

		data = {
			'result' : 'OK',
			'message' : 'Hardware information retrieved successfully.',
			'data' : {
				'cpu_info': cpu_info,
				'total_ram': mem_info.total,
				'available_ram': mem_info.available
			}
		}
		return data
