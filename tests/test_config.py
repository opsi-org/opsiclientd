# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
test_config
"""

import pytest

from opsiclientd.Config import Config, SectionNotFoundException, NoConfigOptionFoundException
from opsiclientd import RUNNING_ON_WINDOWS

from .utils import default_config  # pylint: disable=unused-import

config = Config()


def testGettingUnknownSectionFails():
	with pytest.raises(SectionNotFoundException):
		config.get('nothing', 'bla')


def testDefaultPathsExistPerOS():
	assert config.WINDOWS_DEFAULT_PATHS
	assert config.LINUX_DEFAULT_PATHS


def testConfigGetsFilledWithSystemDefaults():
	assert config.get('global', 'log_dir')
	assert config.get('global', 'state_file')
	assert config.get('global', 'timeline_db')
	assert config.get('global', 'server_cert_dir')
	assert config.get('cache_service', 'storage_dir')
	for section in ('log_dir', 'state_file', 'timeline_db', 'server_cert_dir'):
		if RUNNING_ON_WINDOWS:
			assert config.get('global', section).startswith('c:')
		else:
			assert config.get('global', section).startswith('/')

	if RUNNING_ON_WINDOWS:
		assert config.get('cache_service', 'storage_dir').startswith('c:')
	else:
		assert config.get('cache_service', 'storage_dir').startswith('/')


def testConfigGetsFilledWithSystemSpecificValues():
	assert config.get('global', 'config_file')
	assert config.get('global', 'server_cert_dir')
	assert config.get('cache_service', 'storage_dir')
	assert config.get('cache_service', 'extension_config_dir')
	assert config.get('global', 'config_file')
	assert config.get('global', 'state_file')
	assert config.get('global', 'timeline_db')
	assert config.get('global', 'log_dir')
	if RUNNING_ON_WINDOWS:
		assert config.get('system', 'program_files_dir')

def testGettingUnknownOptionFails():
	with pytest.raises(NoConfigOptionFoundException):
		config.get('global', 'non_existing_option')
