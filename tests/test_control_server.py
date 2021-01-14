# -*- coding: utf-8 -*-

import pytest
import requests

from opsiclientd import ControlServer
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import createEventGenerators

@pytest.fixture
def prepared_config(config, configFile):
	config.set('global', 'config_file', configFile)
	yield config

def test_fire_event(prepared_config): # pylint: disable=redefined-outer-name
	prepared_config.readConfigFile()

	createEventGenerators(None)
	getEventConfigs()

	controlServer = ControlServer.OpsiclientdRpcInterface(None)
	controlServer.fireEvent('on_demand')

def test_firing_unknown_event_raises_error(prepared_config): # pylint: disable=redefined-outer-name
	prepared_config.readConfigFile()

	controlServer = ControlServer.OpsiclientdRpcInterface(None)
	with pytest.raises(ValueError):
		controlServer.fireEvent('foobar')


def test_gui_startup_event_on_windows_only(prepared_config, onWindows): # pylint: disable=redefined-outer-name
	prepared_config.readConfigFile()

	createEventGenerators(None)
	configs = getEventConfigs()

	assert configs
	if onWindows:
		assert 'gui_startup' in configs

# Tests using running opsiclientd
def test_index_page(opsiclient_url):
	req = requests.get(f"{opsiclient_url}", verify=False)
	assert req.status_code == 200

"""
def test_jsonrpc_endpoints(opsiclient_url):
	for endpoint in ("opsiclientd", "rpc"):
		#req = requests.get(opsiclient_url, auth=(auth_data), verify=False)
		req = requests.get(f"{opsiclient_url}/{endpoint}", verify=False)
		assert req.status_code == 200
"""