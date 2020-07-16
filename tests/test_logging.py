from contextlib import contextmanager
import pytest
import time
import io
import logging

import opsicommon.logging
from opsiclientd.Config import Config
from opsiclientd.ControlServer import ControlServer
from opsicommon.logging import logger, LOG_DEBUG

@contextmanager
@pytest.fixture
def log_stream():
	stream = io.StringIO()
	handler = logging.StreamHandler(stream)
	try:
		logging.root.addHandler(handler)
		yield stream
	finally:
		logging.root.removeHandler(handler)

@pytest.mark.xfail
def test_logging(log_stream):
	with log_stream as stream:
		opsicommon.logging.set_format()
		logger.setConsoleLevel(LOG_DEBUG)

		config = Config()

		logger.debug(config)
		logger.debug('Configuration:')
		logger.debug('Server Port: {0}'.format(config.get('control_server', 'port')))
		logger.debug('Server ssl_server_key_file: {0}'.format(config.get('control_server', 'ssl_server_key_file')))
		logger.debug('Server ssl_server_cert_file: {0}'.format(config.get('control_server', 'ssl_server_cert_file')))
		logger.debug('Server static_dir: {0}'.format(config.get('control_server', 'static_dir')))

		c = ControlServer(
			opsiclientd=None,
			httpsPort=config.get('control_server', 'port'),
			sslServerKeyFile=config.get('control_server', 'ssl_server_key_file'),
			sslServerCertFile=config.get('control_server', 'ssl_server_cert_file'),
			staticDir=config.get('control_server', 'static_dir')
		)

		c.start()
		time.sleep(1)
		c.stop()
		stream.seek(0)
		log = stream.read()
		assert "] [control server" in log

@pytest.mark.xfail
def test_logging_filter(log_stream):
	with log_stream as stream:
		opsicommon.logging.set_format()
		logger.setConsoleLevel(LOG_DEBUG)
		opsicommon.logging.set_filter({'instance' : 'control server'})
		with opsicommon.logging.log_context({'instance' : 'test'}):
			config = Config()

			logger.debug("test message")
			c = ControlServer(
				opsiclientd=None,
				httpsPort=config.get('control_server', 'port'),
				sslServerKeyFile=config.get('control_server', 'ssl_server_key_file'),
				sslServerCertFile=config.get('control_server', 'ssl_server_cert_file'),
				staticDir=config.get('control_server', 'static_dir')
			)
			logger.debug("test message")

			c.start()
			c.stop()
		time.sleep(1)
		stream.seek(0)
		log = stream.read()
		assert "test message" not in log
		assert "] [control server" in log
