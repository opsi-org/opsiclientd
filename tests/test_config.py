# -*- coding: utf-8 -*-

from __future__ import absolute_import

import os
import pytest

from opsiclientd.Config import SectionNotFoundException, NoConfigOptionFoundException

from .helper import workInTemporaryDirectory


def testGettingUnknownSectionFails(config):
	with pytest.raises(SectionNotFoundException):
		config.get('nothing', 'bla')


def testDefaultPathsExistPerOS(config):
	assert config.WINDOWS_DEFAULT_PATHS
	assert config.LINUX_DEFAULT_PATHS


def testConfigGetsFilledWithSystemDefaults(config, onWindows):
	assert config.get('global', 'log_dir')
	assert config.get('global', 'state_file')
	assert config.get('global', 'timeline_db')
	assert config.get('global', 'server_cert_dir')

	assert config.get('cache_service', 'storage_dir')

	for section in ('log_dir', 'state_file', 'timeline_db', 'server_cert_dir'):
		if onWindows:
			assert config.get('global', section).startswith('c:')
		else:
			assert config.get('global', section).startswith('/')

	if onWindows:
		assert config.get('cache_service', 'storage_dir').startswith('c:')
	else:
		assert config.get('cache_service', 'storage_dir').startswith('/')


def testConfigGetsFilledWithSystemSpecificValues(config, onWindows):
	assert config.get('global', 'config_file')
	assert config.get('global', 'server_cert_dir')

	assert config.get('cache_service', 'storage_dir')
	assert config.get('cache_service', 'extension_config_dir')

	assert config.get('global', 'config_file')
	assert config.get('global', 'state_file')
	assert config.get('global', 'timeline_db')
	assert config.get('global', 'log_dir')

	if onWindows:
		assert config.get('system', 'program_files_dir')


def testGettingUnknownOptionFails(config):
	with pytest.raises(NoConfigOptionFoundException):
		config.get('global', 'non_existing_option')

'''
def testRotatingLogfile(config):
	with workInTemporaryDirectory() as tempDir:
		dummyConfig = os.path.join(tempDir, 'config')
		logFile = os.path.join(tempDir, 'testlog.log')

		with open(logFile, 'w') as f:
			pass

		with open(dummyConfig, 'w') as f:
			f.write("""[global]
log_file = {0}""".format(logFile))

		config.set('global', 'config_file', dummyConfig)
		config.set('global', 'log_dir', tempDir)

		# First rotation
		config.readConfigFile()
		print(os.listdir(tempDir))
		assert os.path.exists(os.path.join(tempDir, 'testlog.log.0'))

		# Second rotation
		config.readConfigFile()
		print(os.listdir(tempDir))
		assert os.path.exists(os.path.join(tempDir, 'testlog.log.1'))
'''
