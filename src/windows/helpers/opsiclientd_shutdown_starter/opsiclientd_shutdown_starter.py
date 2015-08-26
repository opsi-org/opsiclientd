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

__version__ = '4.0.6'

import os
import sys
import time

from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Logger import Logger, LOG_DEBUG, LOG_WARNING
from OPSI.Types import forceBool


logger = Logger()
if False:
	logger.setConsoleLevel(LOG_DEBUG)
else:
	logger.setConsoleLevel(LOG_WARNING)

try:
	myEvent = "gui_startup"  # THIS
	# myEvent = "shutdown_install"
	if len(sys.argv) > 1:
		myEvent = sys.argv[1]

	#reading the opsiclientd.conf for the machine-account
	basedir = os.getcwd()
	pathToConf = os.path.join(basedir, "opsiclientd", "opsiclientd.conf")

	username = None
	password = None
	try:
		with open(pathToConf) as f:
			for line in f:
				if line.lower().startswith(u"host_id"):
					username = line.split("=")[1].strip()
				elif line.lower().startswith(u"opsi_host_key"):
					password = line.split("=")[1].strip()

				if username and password:
					break
	except (IOError, OSError) as error:
		logger.warning(error)

	# Connect local service
	be = JSONRPCBackend(
		username=username,
		password=password,
		address=u'https://localhost:4441/opsiclientd'
	)
	logger.debug(u"Backend connected.")

	if forceBool(be.isInstallationPending()):
		logger.debug(u"State installation pending detected, don't starting shutdown event.")
		os.exit(0)

	# Trying to fire myEvent
	be.fireEvent(myEvent)
	logger.debug(u"Event fired")
	time.sleep(4)

	while True:
		if be.isEventRunning(myEvent):
			time.sleep(5)
		elif be.isEventRunning(myEvent+"{user_logged_in}"):
			time.sleep(5)
		else:
			break

	logger.debug(u"Task completed.")
except Exception as error:
	logger.critical(error)
	sys.exit(1)

sys.exit(0)
