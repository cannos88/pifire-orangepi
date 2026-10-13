'''
Data helpers for the "Modern" dashboard.

The dashboard polls /api/current for live values and asks /dash/modern/data
every few seconds for the chart, the timer and the pellet estimate.  History
is stored every 3 s (20 points a minute), so 3 hours are ~3600 points: they
are averaged down to a few hundred so a phone redraws the chart without
effort.
'''

HISTORY_POINTS_PER_MINUTE = 20


def downsample_history(history, max_points=300):
	'''
	Average consecutive history entries into at most max_points buckets.

	:param history: list of history dicts {T, P:{label:temp}, F:{label:temp}, PSP, ...}
	:return: {'T': [ms...], 'PSP': [...], 'P': {label: [...]}, 'F': {label: [...]}}
	         Probe values that were missing in a whole bucket become None, so a
	         disconnected probe leaves a gap instead of a line to zero.
	'''
	result = {'T': [], 'PSP': [], 'P': {}, 'F': {}}
	if not history:
		return result

	bucket = max(1, -(-len(history) // max_points))  # ceil division
	labels = {'P': [], 'F': []}
	for entry in history:
		for group in ('P', 'F'):
			for label in (entry.get(group) or {}):
				if label not in labels[group]:
					labels[group].append(label)
	for group in ('P', 'F'):
		for label in labels[group]:
			result[group][label] = []

	def mean(values):
		values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
		return round(sum(values) / len(values), 1) if values else None

	for start in range(0, len(history), bucket):
		chunk = history[start:start + bucket]
		result['T'].append(chunk[-1].get('T'))
		setpoints = [e.get('PSP') for e in chunk]
		psp = mean(setpoints)
		result['PSP'].append(psp if psp else None)  # 0 = no set point (Smoke, Startup...)
		for group in ('P', 'F'):
			for label in labels[group]:
				values = [(e.get(group) or {}).get(label) for e in chunk]
				# A probe reading 0 or less is a missing/unplugged probe on PiFire
				result[group][label].append(mean([v for v in values if isinstance(v, (int, float)) and v > 0]))
	return result


def cook_pellet_estimate(metrics_list, startup_timestamp, auger_rate):
	'''
	Grams of pellets fed since the grill was started, from the auger on-time
	recorded in the metrics of every mode run since startup_timestamp (s).
	'''
	if not startup_timestamp or not metrics_list:
		return None
	start_ms = startup_timestamp * 1000 - 5000
	seconds = 0.0
	for metric in metrics_list:
		try:
			if metric.get('starttime', 0) >= start_ms:
				seconds += float(metric.get('augerontime', 0) or 0)
		except (TypeError, ValueError, AttributeError):
			continue
	return int(seconds * auger_rate)


def timer_state(timer, notify_data, now):
	'''
	Timer as the dashboard needs it: state idle/running/paused, the seconds
	left and the end time (epoch s), plus the shutdown/keep warm options.
	'''
	timer = timer or {}
	start, end, paused = timer.get('start', 0), timer.get('end', 0), timer.get('paused', 0)
	info = {'state': 'idle', 'remaining': 0, 'end': 0, 'duration': 0, 'shutdown': False, 'keep_warm': False}
	for item in notify_data or []:
		if item.get('type') == 'timer':
			info['shutdown'] = bool(item.get('shutdown'))
			info['keep_warm'] = bool(item.get('keep_warm'))
			break
	if not start or not end:
		return info
	info['duration'] = max(0, int(end - start))
	if paused:
		info['state'] = 'paused'
		info['remaining'] = max(0, int(end - paused))
	else:
		info['state'] = 'running' if end > now else 'done'
		info['remaining'] = max(0, int(end - now))
		info['end'] = end
	return info
