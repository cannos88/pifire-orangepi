#!/usr/bin/env python3

'''
*****************************************
 PiFire Flame-out Detector
*****************************************

 Description: Recognises a fire pot that has gone out while holding a
 temperature, long before the grill cools down to the startup safety
 threshold.

 Without it, PiFire only notices a flame-out when the grill temperature drops
 below the startup safety temperature (at most 100 F / 38 C).  Meanwhile the
 controller sees the grill cooling and runs the auger at its maximum, filling
 the fire pot with unburnt pellets.  When the igniter relights them they can
 all catch at once (a flare-up, or a puff of smoke out of the fire pot).

 Signature of a flame-out in Hold mode: the temperature keeps falling for a
 few minutes while the controller asks for high auger output, and keeps
 falling even when the pellet feed is brought back to the amount that held
 the set point before.

   ok       -> suspect   below the set point, falling steadily over the whole
                         window, auger output high for most of it.
                         PiFire limits the feed to the steady-state amount
                         (feed_limit), so a dead fire pot stops filling up.
   suspect  -> ok        the temperature rises again, or drops abruptly (lid).
   suspect  -> flameout  still falling clearly after the confirmation time,
                         even with the steady-state feed.  PiFire then starts
                         the re-ignite sequence (or errors out when no retries
                         are left), like the existing safety check.

 Opening the lid makes the temperature drop much faster than a dead fire
 does (several degrees per second instead of a fraction of a degree), so a
 fast drop pauses the detector for a few minutes instead of counting as a
 flame-out.  A live fire behind an open lid then settles on a plateau, which
 is not a steady fall.

 All thresholds are in degrees F internally, like the PID controllers; input
 temperatures are converted when the grill runs in Celsius.

*****************************************
'''

import collections


class FlameoutDetector:
	OK = 'ok'
	SUSPECT = 'suspect'
	FLAMEOUT = 'flameout'

	def __init__(self, units='F', enabled=True, window_s=150, min_drop=12.0, min_below_setpoint=15.0,
				 high_output_fraction=0.8, high_output_share=0.6, confirm_s=180, confirm_drop=8.0,
				 recovery_rise=3.0, lid_drop_rate=40.0, lid_holdoff_s=300, stable_band=5.0,
				 sample_interval_s=1.0):
		'''
		:param units: 'F' or 'C' (units of the temperatures passed to update)
		:param window_s: how long the temperature must keep falling, in seconds
		:param min_drop: minimum temperature drop over the window (F)
		:param min_below_setpoint: how far below the set point the grill must be (F)
		:param high_output_fraction: output counts as "high" at this fraction of u_max
		:param high_output_share: share of the window that must have high output
		:param confirm_s: time in suspect state before deciding
		:param confirm_drop: further drop during confirm_s that confirms a flame-out (F); half of it
			must happen in the last 60 s, so the fall is still going on (a live fire that
			was just short of pellets levels off within a minute of the steady feed)
		:param recovery_rise: rise above the lowest suspect temperature that clears the suspicion (F)
		:param lid_drop_rate: drop rate that means "lid opened", F per minute over 30 s
		:param lid_holdoff_s: pause after a lid-like drop
		:param stable_band: within this distance of the set point the cycle ratio is learned (F)
		'''
		self.units = units
		self.enabled = enabled
		self.window_s = window_s
		self.min_drop = min_drop
		self.min_below_setpoint = min_below_setpoint
		self.high_output_fraction = high_output_fraction
		self.high_output_share = high_output_share
		self.confirm_s = confirm_s
		self.confirm_drop = confirm_drop
		self.recovery_rise = recovery_rise
		self.lid_drop_rate = lid_drop_rate
		self.lid_holdoff_s = lid_holdoff_s
		self.stable_band = stable_band
		self.sample_interval_s = sample_interval_s
		self.stable_ratio = None   # cycle ratio that held the set point, learned while stable
		self.recent = collections.deque()  # last 30 s of (time, temp F) for the lid check
		self.reset()

	def reset(self):
		self.state = self.OK
		self.samples = collections.deque()
		self.suspect_since = None
		self.suspect_temp = None
		self.suspect_trace = collections.deque()
		self.lowest_temp = None
		self.holdoff_until = None
		self._last_sample_time = None

	def _to_f(self, temp):
		return temp * 9 / 5 + 32 if self.units == 'C' else temp

	def feed_limit(self, u_min):
		'''Cycle ratio PiFire should not exceed while a flame-out is suspected.'''
		if self.stable_ratio is None:
			return u_min
		return max(u_min, self.stable_ratio)

	def _window_is_falling(self):
		'''True when each third of the window is cooler than the one before.'''
		temps = [t for _, t, _ in self.samples]
		n = len(temps)
		if n < 6:
			return False
		third = n // 3
		first = sum(temps[:third]) / third
		middle = sum(temps[third:2 * third]) / third
		last = sum(temps[2 * third:]) / (n - 2 * third)
		return first > middle > last and (temps[0] - temps[-1]) >= self.min_drop

	def _lid_like_drop(self, now, temp_f):
		'''Fast drop over the last 30 s, typical of an opened lid.'''
		self.recent.append((now, temp_f))
		while self.recent and now - self.recent[0][0] > 30:
			self.recent.popleft()
		span = now - self.recent[0][0]
		if span < 20:
			return False
		rate_per_min = (self.recent[0][1] - temp_f) / span * 60
		return rate_per_min >= self.lid_drop_rate

	def update(self, now, temp, setpoint, cycle_ratio, u_max, active=True):
		'''
		Feed one reading.  Call it on every control loop pass in Hold mode.

		:param now: current time in seconds
		:param temp: grill (primary probe) temperature
		:param setpoint: hold set point
		:param cycle_ratio: auger cycle ratio currently commanded (0-1)
		:param u_max: maximum cycle ratio allowed by the settings
		:param active: False while detection must not run (not at temperature yet, lid open)
		:return: 'ok', 'suspect' or 'flameout'
		'''
		if not self.enabled or temp is None:
			return self.OK
		if not active:
			if self.state != self.OK or self.samples:
				self.reset()
			return self.state

		if self._last_sample_time is not None and now - self._last_sample_time < self.sample_interval_s:
			return self.state
		self._last_sample_time = now

		temp_f = self._to_f(temp)
		setpoint_f = self._to_f(setpoint)

		if self.state == self.FLAMEOUT:
			return self.state

		# An opened lid: pause detection for a while
		lid_drop = self._lid_like_drop(now, temp_f)

		# Learn the feed that holds the set point (slow average while near it and not drifting)
		drift = abs(temp_f - self.recent[0][1])
		if self.state == self.OK and abs(temp_f - setpoint_f) <= self.stable_band and drift < 3.0:
			if self.stable_ratio is None:
				self.stable_ratio = cycle_ratio
			else:
				self.stable_ratio += (cycle_ratio - self.stable_ratio) * 0.005

		if lid_drop:
			self.reset()
			self.holdoff_until = now + self.lid_holdoff_s
			return self.state
		if self.holdoff_until is not None:
			if now < self.holdoff_until:
				return self.state
			self.holdoff_until = None

		if self.state == self.SUSPECT:
			self.lowest_temp = min(self.lowest_temp, temp_f)
			self.suspect_trace.append((now, temp_f))
			if temp_f >= self.lowest_temp + self.recovery_rise:
				self.reset()  # coming back: slow but live fire
				return self.state
			if now - self.suspect_since >= self.confirm_s:
				minute_ago = next(t for ts, t in self.suspect_trace if ts >= now - 60)
				if (temp_f <= self.suspect_temp - self.confirm_drop
						and temp_f <= minute_ago - self.confirm_drop / 2):
					self.state = self.FLAMEOUT
				else:
					self.reset()  # levelled off with the steady feed: the fire is alive
			return self.state

		# State OK: collect the window
		self.samples.append((now, temp_f, cycle_ratio))
		while self.samples and now - self.samples[0][0] > self.window_s:
			self.samples.popleft()
		if now - self.samples[0][0] < self.window_s * 0.95:
			return self.state  # window not filled yet

		high = sum(1 for _, _, r in self.samples if r >= self.high_output_fraction * u_max)
		high_share = high / len(self.samples)
		if (setpoint_f - temp_f >= self.min_below_setpoint
				and high_share >= self.high_output_share
				and self._window_is_falling()):
			self.state = self.SUSPECT
			self.suspect_since = now
			self.suspect_temp = temp_f
			self.lowest_temp = temp_f
		return self.state
