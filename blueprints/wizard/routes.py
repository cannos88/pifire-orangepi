import os
from flask import render_template, request, jsonify, redirect, render_template_string
from common.common import read_settings, read_control, read_wizard, get_wizard_install_status, set_wizard_install_status, store_wizard_install_info, write_settings, is_real_hardware

from . import wizard_bp
from .wizard import *

@wizard_bp.route('/<action>', methods=['POST','GET'])
@wizard_bp.route('/', methods=['POST','GET'])
def wizard_page(action=None):
    settings = read_settings()
    control = read_control()
    wizardData = read_wizard()
    errors = []

    if is_real_hardware():
        python_exec = settings['globals'].get('python_exec', 'python')
    else:
        python_exec = 'python'  # Bug fix for development environment where python_exec isn't relevant

    if request.method == 'GET':
        if action=='installstatus':
            percent, status, output = get_wizard_install_status()
            return jsonify({'percent' : percent, 'status' : status, 'output' : output}) 
    elif request.method == 'POST':
        r = request.form
        if action=='cancel':
            settings['globals']['first_time_setup'] = False
            write_settings(settings)
            return redirect('/')

        if action=='finish':
            if control['mode'] == 'Stop':
                wizardInstallInfo = prepare_wizard_data(r)
                store_wizard_install_info(wizardInstallInfo)
                set_wizard_install_status(0, 'Starting Install...', '')
                os.system(f'{python_exec} wizard.py &')	# Kickoff Installation
                return render_template(
					                'wizard/wizard-finish.html', 
									page_theme=settings['globals'].get('page_theme', 'light'),
									grill_name=settings['globals'].get('grill_name', ''),
									wizardData=wizardData
									)

        if action=='modulecard':
            module = r['module']
            section = r['section']
            if section in ['grillplatform', 'display', 'distance']:
                moduleData = wizardData['modules'][section][module]
                moduleSettings = {}
                moduleSettings['settings'] = get_settings_dependencies_values(settings, moduleData)
                moduleSettings['config'] = {} if section != 'display' else settings['display']['config'][module]
                render_string = "{% from 'wizard/_macro_wizard_card.html' import render_wizard_card %}{{ render_wizard_card(moduleData, moduleSection, moduleSettings) }}"
                return render_template_string(render_string, moduleData=moduleData, moduleSection=section, moduleSettings=moduleSettings)
            else:
                return '<strong color="red">No Data</strong>'

    ''' Create Temporary Probe Device/Port Structure for Setup, Use Existing unless First Time Setup '''
    if settings['globals']['first_time_setup']: 
        wizardInstallInfo = wizardInstallInfoDefaults(wizardData, settings)
    else:
        wizardInstallInfo = wizardInstallInfoExisting(wizardData, settings)

    store_wizard_install_info(wizardInstallInfo)

    if control['mode'] != 'Stop':
        errors.append('PiFire configuration wizard cannot be run while the system is active.  Please stop the current cook before continuing.')

    return render_template(
                            'wizard/wizard.html',
                            settings=settings,
                            control=control,
							errors=errors,
							wizardData=wizardData, 
							wizardInstallInfo=wizardInstallInfo,
                            page_theme=settings['globals'].get('page_theme', 'light'),
                            grill_name=settings['globals'].get('grill_name', '')
                            )



