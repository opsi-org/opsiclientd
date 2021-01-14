# -*- coding: utf-8 -*-

import os
import mock
import pytest
import configparser

from opsiclientd.Config import Config

@pytest.fixture
def opsiclient_url():
	return "https://localhost:4441"

@pytest.fixture
def opsiclient_auth(configFile):
	conf = configparser.ConfigParser()
	conf.read(configFile)
	return (conf.get("global", "host_id"), conf.get("global", "opsi_host_key"))

@pytest.fixture
def config():
	testconfig = Config()
	with mock.patch('opsiclientd.Events.Utilities.Configs.config', testconfig):
		yield testconfig


@pytest.fixture
def configFile(onWindows):
	if onWindows:
		return os.path.join(os.path.dirname(__file__), '..', 'opsiclientd_data', 'windows', 'opsiclientd.conf')
	else:
		if os.path.exists("/etc/opsi/opsiclientd.conf"):
			return "/etc/opsi/opsiclientd.conf"
		return os.path.join(os.path.dirname(__file__), '..', 'opsiclientd_data', 'linux', 'opsiclientd.conf')


@pytest.fixture
def onWindows():
	return bool(os.name == 'nt')
