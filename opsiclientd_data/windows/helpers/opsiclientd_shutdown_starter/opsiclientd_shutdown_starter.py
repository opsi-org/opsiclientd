#! /usr/bin/env python
# -*- coding: utf-8 -*-

# opsiclientd_shutdown_starter is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2015 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Helper to trigger an event on shutdown.

:copyright:	uib GmbH <info@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
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
