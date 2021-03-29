# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Helper to trigger an event on shutdown.
"""

import os
import sys
import time

from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Logger import Logger, LOG_DEBUG, LOG_WARNING
from OPSI.Types import forceBool

__version__ = '4.0.6'

SECONDS_TO_SLEEP_AFTER_ACTION = 5

LOGGER = Logger()
if False:
	LOGGER.setConsoleLevel(LOG_DEBUG)
else:
	LOGGER.setConsoleLevel(LOG_WARNING)


def main(event):
	basedir = os.getcwd()
	pathToConf = os.path.join(basedir, "opsiclientd", "opsiclientd.conf")

	username, password = readCredentialsFromConfig(pathToConf)

	backend = JSONRPCBackend(
		username=username,
		password=password,
		address=u'https://localhost:4441/opsiclientd'
	)
	LOGGER.debug(u"Backend connected.")

	if forceBool(backend.isInstallationPending()):
		LOGGER.debug(u"State installation pending detected, don't starting shutdown event.")
		return

	LOGGER.debug(u"Firing event {0!r}".format(event))
	backend.fireEvent(event)
	LOGGER.debug(u"Event fired")
	time.sleep(SECONDS_TO_SLEEP_AFTER_ACTION)

	while True:
		if backend.isEventRunning(event):
			time.sleep(SECONDS_TO_SLEEP_AFTER_ACTION)
		elif backend.isEventRunning("{0}{{user_logged_in}}".format(event)):
			time.sleep(SECONDS_TO_SLEEP_AFTER_ACTION)
		else:
			break

	LOGGER.debug(u"Task completed.")


def readCredentialsFromConfig(pathToConfig):
	username = None
	password = None

	try:
		with open(pathToConfig) as configFile:
			for line in configFile:
				if line.lower().startswith(u"host_id"):
					username = line.split("=")[1].strip()
				elif line.lower().startswith(u"opsi_host_key"):
					password = line.split("=")[1].strip()

				if username and password:
					break
	except (IOError, OSError) as error:
		LOGGER.warning(error)

	return username, password


if __name__ == '__main__':
	LOGGER.setLogFile(os.path.join('C:\\', 'opsi.org', 'log', 'opsiclientd_shutdown_starter.log'))
	LOGGER.setFileLevel(LOG_DEBUG)

	try:
		myEvent = "gui_startup"
		if len(sys.argv) > 1:
			myEvent = sys.argv[1]

		main(myEvent)
	except Exception as error:
		LOGGER.critical(error)
		sys.exit(1)
