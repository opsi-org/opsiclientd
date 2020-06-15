#!/usr/bin/env python
#-*- coding: utf-8 -*-

import os
import sys

from OPSI.Logger import Logger, LOG_DEBUG

# Hacking together our paths for working imports :(
LOCAL_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(LOCAL_DIR, '.'))
sys.path.insert(0, os.path.join(LOCAL_DIR, '..'))
sys.path.insert(0, os.path.join(LOCAL_DIR, '..', '..'))

from opsiclientd.Config import Config
from opsiclientd.ControlServer import ControlServer

LOGGER = Logger()


def start_with_defaults():
	"""
	Starting a control server with the default settings.
	"""
	config = Config()

	LOGGER.debug(config)
	LOGGER.debug('Configuration:')
	LOGGER.debug('Server Port: {0}'.format(config.get('control_server', 'port')))
	LOGGER.debug('Server ssl_server_key_file: {0}'.format(config.get('control_server', 'ssl_server_key_file')))
	LOGGER.debug('Server ssl_server_cert_file: {0}'.format(config.get('control_server', 'ssl_server_cert_file')))
	LOGGER.debug('Server static_dir: {0}'.format(config.get('control_server', 'static_dir')))

	c = ControlServer(
		opsiclientd=None,
		httpsPort=config.get('control_server', 'port'),
		sslServerKeyFile=config.get('control_server', 'ssl_server_key_file'),
		sslServerCertFile=config.get('control_server', 'ssl_server_cert_file'),
		staticDir=config.get('control_server', 'static_dir')
	)

	c.start()


if __name__ == '__main__':
	LOGGER.setConsoleLevel(LOG_DEBUG)
	start_with_defaults()
