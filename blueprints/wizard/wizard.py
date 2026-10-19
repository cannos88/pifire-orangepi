from common.common import read_wizard, load_wizard_install_info

def get_settings_dependencies_values(settings, moduleData):
	moduleSettings = {}
	for setting, data in moduleData['settings_dependencies'].items():
		setting_location = data['settings']
		setting_value = settings
		for setting_name in setting_location:
			setting_value = setting_value[setting_name]
		moduleSettings[setting] = setting_value 
	return moduleSettings 

def wizardInstallInfoDefaults(wizardData, settings):
	
	wizardInstallInfo = {
		'modules' : {
			'grillplatform' : {
				'profile_selected' : [],  # Reference the profile in wizardData > wizard_manifest.json
				'settings' : {},
				'config' : {}
			}, 
			'display' : {
				'profile_selected' : [],
				'settings' : {},
				'config' : {}
			}, 
			'distance' : {
				'profile_selected' : [],
				'settings' : {},
				'config' : {}
			}, 
			'probes' : {
				'profile_selected' : [],
				'settings' : {
					'units' : 'C'  # Orange Pi fork: °C by default on the first setup
				},
				'config' : {}
			}
		},
		'probe_map' : {}
	}
	''' Populate Modules Info with Defaults from Wizard Data including Settings '''
	for component in ['grillplatform', 'display', 'distance']:
		for module in wizardData['modules'][component]:
			if wizardData['modules'][component][module]['default']:
				''' Populate Module Filename'''
				wizardInstallInfo['modules'][component]['profile_selected'].append(module) #TODO: Change wizard.py to reference the module filename instead, or in grill_platform use platform>system_type
				for setting in wizardData['modules'][component][module]['settings_dependencies']: 
					''' Populate all settings with default value '''
					wizardInstallInfo['modules'][component]['settings'][setting] = list(wizardData['modules'][component][module]['settings_dependencies'][setting]['options'].keys())[0]
				if module == 'display':
					wizardInstallInfo['modules'][component]['config'] = settings['display']['config'][module]

	''' Populate the default probe device / probe map from the default PCB Board '''
	wizardInstallInfo['probe_map'] = wizardData['boards'][wizardInstallInfo['modules']['grillplatform']['profile_selected'][0]]['probe_map']

	''' Populate Probes Module List with all configured probe devices '''
	for device in wizardInstallInfo['probe_map']['probe_devices']:
		wizardInstallInfo['modules']['probes']['profile_selected'].append(device['module'])

	return wizardInstallInfo

def wizardInstallInfoExisting(wizardData, settings):
	wizardInstallInfo = {
		'modules' : {
			'grillplatform' : {
				'profile_selected' : [settings['platform']['current']],
				'settings' : {},
				'config' : {}
			}, 
			'display' : {
				'profile_selected' : [settings['modules']['display']],
				'settings' : {},
				'config' : {}
			}, 
			'distance' : {
				'profile_selected' : [settings['modules']['dist']],
				'settings' : {},
				'config' : {}
			}, 
			'probes' : {
				'profile_selected' : [],
				'settings' : {
					'units' : settings['globals']['units']
				},
				'config' : {}
			}
		}, 
		'probe_map' : settings['probe_settings']['probe_map']
	} 
	''' Populate Probes Module List with all configured probe devices '''
	for device in wizardInstallInfo['probe_map']['probe_devices']:
		wizardInstallInfo['modules']['probes']['profile_selected'].append(device['module'])
	
	''' Populate Modules Info with current Settings '''
	for module in ['grillplatform', 'display', 'distance']:
		selected = wizardInstallInfo['modules'][module]['profile_selected'][0]
		''' Error condition if the item in settings doesn't match the wizard manifest '''
		if selected not in wizardData['modules'][module].keys():
			if module == 'grillplatform':
				selected = 'pcb_4.x.x_opizero2w'  # fork: the only platform
				settings['platform']['current'] = selected
			else:
				selected = 'none'
			wizardInstallInfo['modules'][module]['profile_selected'] = [selected]

		for setting in wizardData['modules'][module][selected]['settings_dependencies']:
			settingsLocation = wizardData['modules'][module][selected]['settings_dependencies'][setting]['settings']
			settingsValue = settings.copy() 
			for index in range(0, len(settingsLocation)):
				settingsValue = settingsValue[settingsLocation[index]]
			wizardInstallInfo['modules'][module]['settings'][setting] = str(settingsValue)
		if module == 'display':
			wizardInstallInfo['modules'][module]['config'] = settings['display']['config'].get(selected, {})
	return wizardInstallInfo

def prepare_wizard_data(form_data):
	wizardData = read_wizard()
	
	wizardInstallInfo = load_wizard_install_info()

	wizardInstallInfo['modules'] = {
		'grillplatform' : {
			'profile_selected' : [form_data['grillplatformSelect']],
			'settings' : {},
			'config' : {}
		}, 
		'display' : {
			'profile_selected' : [form_data['displaySelect']],
			'settings' : {},
			'config' : {}
		}, 
		'distance' : {
			'profile_selected' : [form_data['distanceSelect']],
			'settings' : {},
			'config' : {}
		}, 
		'probes' : {
			'profile_selected' : [],
			'settings' : {
				'units' : form_data['probes_units']
			},
			'config' : {}
		}
	}

	for device in wizardInstallInfo['probe_map']['probe_devices']:
		wizardInstallInfo['modules']['probes']['profile_selected'].append(device['module'])

	for module in ['grillplatform', 'display', 'distance']:
		module_ = module + '_'
		moduleSelect = module + 'Select'
		selected = form_data[moduleSelect]
		for setting in wizardData['modules'][module][selected]['settings_dependencies']:
			settingName = module_ + setting
			if(settingName in form_data):
				wizardInstallInfo['modules'][module]['settings'][setting] = form_data[settingName]
		for config, value in form_data.items():
			if config.startswith(module_ + 'config_'):
				wizardInstallInfo['modules'][module]['config'][config.replace(module_ + 'config_', '')] = value

	return(wizardInstallInfo)