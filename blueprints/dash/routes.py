
from flask import render_template, request, redirect, render_template_string
import time

from flask import jsonify
from common.common import read_settings, read_control, process_command, read_errors, read_warnings, read_probe_status, write_settings, read_generic_json
from common.common import read_history, read_metrics, read_pellet_db, read_control_pending
from common.app import get_system_command_output
from common.safe_paths import safe_within
from file_mgmt.common import read_json_file_data
from .modern_data import HISTORY_POINTS_PER_MINUTE, downsample_history, cook_pellet_estimate, timer_state, recipe_state

from . import dash_bp

@dash_bp.route('/', methods=['POST','GET'])
def dash_page():
    settings = read_settings()
    control = read_control()
    errors = read_errors()
    warnings = read_warnings()

    current = settings['dashboard'].get('current', 'Modern')
    if current not in settings['dashboard']['dashboards']:
        current = 'Modern'  # the classic dashboards were removed (Orange Pi fork)
    dash_template = f"{current.lower()}/{settings['dashboard']['dashboards'][current].get('html_name', 'dash_modern.html')}"
    dash_data = settings['dashboard']['dashboards'].get(current, {})
    probe_status = read_probe_status(settings['probe_settings']['probe_map']['probe_info'])

    ''' Check if control process is up and running. '''
    process_command(action='sys', arglist=['check_alive'], origin='dash')  # Request supported commands 
    data = get_system_command_output(requested='check_alive')
    if data['result'] != 'OK':
        errors.append('The control process did not respond to a request and may be stopped.  Try reloading the page or restarting the system.  Check logs for details.')

    return render_template(
                            dash_template,
                            settings=settings,
                            control=control,
                            dash_data=dash_data,
                            probe_status=probe_status,
                            errors=errors,
                            warnings=warnings,
                            page_theme=settings['globals'].get('page_theme', 'light'),
                            grill_name=settings['globals'].get('grill_name', '')
                            )

@dash_bp.route('/config', methods=['POST','GET'])
def dash_config():
	settings = read_settings()
	current = settings['dashboard']['current']
	dash_data = settings['dashboard']['dashboards'].get(current, {})
	meta_data_filename = dash_data.get('metadata', None)
	dash_metadata = read_generic_json(f'./dashboard/{meta_data_filename}')

	if request.method == 'GET':
		render_string = "{% from '_macro_generic_config.html' import render_dash_config_card %}{{ render_dash_config_card(dash_metadata, dash_data) }}"
		return render_template_string(
			                render_string, 
							dash_metadata=dash_metadata, 
							dash_data=dash_data
                          )
	elif request.method == 'POST':
		dash_config_request = request.form
		for key, value in dash_config_request.items():
			if 'dashConfig_' in key:
				dash_data['config'][key.replace('dashConfig_','')] = value
		settings['dashboard']['dashboards'][current]['config'] = dash_data['config']
		write_settings(settings)
		return redirect('/dash')
	
	return 'Bad Request'

def _read_recipe_part(filename, part):
	# only files in the recipe folder (the filename comes from control data)
	if not safe_within(filename, './recipes/'):
		return {}, 'ERROR'
	return read_json_file_data(filename, part)

@dash_bp.route('/modern/data', methods=['GET'])
def dash_modern_data():
	'''
	Chart, timer and pellet data for the Modern dashboard.
	/dash/modern/data?minutes=90  (5 to 720 minutes of history)
	'''
	settings = read_settings()
	control = read_control_pending()  # timer commands sent a moment ago are already visible
	try:
		minutes = int(request.args.get('minutes', 90))
	except ValueError:
		minutes = 90
	minutes = max(5, min(720, minutes))

	history = read_history(num_items=minutes * HISTORY_POINTS_PER_MINUTE)
	chart = downsample_history(history, max_points=300)

	try:
		metrics_list = read_metrics(all=True)
	except Exception:
		metrics_list = []
	startup_timestamp = control.get('startup_timestamp', 0) if control.get('mode') not in ('Stop', 'Error', 'Monitor') else 0
	pellets_g = cook_pellet_estimate(metrics_list, startup_timestamp, settings['globals'].get('augerrate', 0.3))

	hopper = None
	if settings['modules'].get('dist', 'none') != 'none':
		try:
			hopper = read_pellet_db()['current']['hopper_level']
		except Exception:
			hopper = None

	return jsonify({
		'minutes': minutes,
		'chart': chart,
		'timer': timer_state(control.get('timer'), control.get('notify_data'), time.time()),
		'pellets_g': pellets_g,
		'hopper_level': hopper,
		'mqtt': bool(settings.get('notify_services', {}).get('mqtt', {}).get('enabled', False)),
		'recipe': recipe_state(control, _read_recipe_part),
		'server_time': time.time(),
	})
