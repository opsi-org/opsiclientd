# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

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
:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import gettext
import locale
import os
import sys

import opsicommon.logging
from opsicommon.logging import logger, LOG_NONE
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI import System

from opsiclientd import __version__, DEFAULT_STDERR_LOG_FORMAT, DEFAULT_FILE_LOG_FORMAT

def main():
	if len(sys.argv) != 17:
		print("Usage: %s <hostId> <hostKey> <controlServerPort> <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword> <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout> <runAsUser> <runAsPassword> <createEnvironment>" % os.path.basename(sys.argv[0]))
		sys.exit(1)

	(hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, depotServerUsername, depotServerPassword, sessionId, actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout, runAsUser, runAsPassword, createEnvironment) = sys.argv[1:]

	if hostKey:
		logger.addConfidentialString(hostKey)
	if depotServerPassword:
		logger.addConfidentialString(depotServerPassword)
	if runAsPassword:
		logger.addConfidentialString(runAsPassword)

	opsicommon.logging.init_logging(
		stderr_level=LOG_NONE,
		stderr_format=DEFAULT_STDERR_LOG_FORMAT,
		log_file=logFile,
		file_level=int(logLevel),
		file_format=DEFAULT_FILE_LOG_FORMAT
	)
	
	with opsicommon.logging.log_context({'instance' : os.path.basename(sys.argv[0])}):
		logger.debug("Called with arguments: %s", ', '.join((hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, depotServerUsername, depotServerPassword, sessionId, actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout, runAsUser, runAsPassword, createEnvironment)) )
		
		try:
			lang = locale.getdefaultlocale()[0].split('_')[0]
			localeDir = os.path.join(os.path.dirname(sys.argv[0]), 'locale')
			translation = gettext.translation('opsiclientd', localeDir, [lang])
			_ = translation.ugettext
		except Exception as e:
			logger.error("Locale not found: %s", e)

			def _(string):
				return string

		if runAsUser and createEnvironment.lower() in ('yes', 'true', '1'):
			createEnvironment = True
		else:
			createEnvironment = False
		actionProcessorTimeout = int(actionProcessorTimeout)
		imp = None
		depotShareMounted = False
		be = None

		try:
			be = JSONRPCBackend(username=hostId, password=hostKey, address=f"https://localhost:{controlServerPort}/opsiclientd")

			if runAsUser:
				logger.info("Impersonating user '%s'", runAsUser)
				imp = System.Impersonate(username=runAsUser, password=runAsPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="INTERACTIVE", newDesktop=True, createEnvironment=createEnvironment)
			else:
				logger.info("Impersonating network account '%s'", depotServerUsername)
				imp = System.Impersonate(username=depotServerUsername, password=depotServerPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="NEW_CREDENTIALS")

			if depotRemoteUrl.split('/')[2] not in ("127.0.0.1", "localhost"):
				logger.notice("Mounting depot share %s", depotRemoteUrl)
				be.setStatusMessage(sessionId, _("Mounting depot share %s") % depotRemoteUrl)

				if runAsUser:
					System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)
				else:
					System.mount(depotRemoteUrl, depotDrive)
				depotShareMounted = True

			logger.notice("Starting action processor")
			be.setStatusMessage(sessionId, _("Action processor is running"))

			imp.runCommand(actionProcessorCommand, timeoutSeconds=actionProcessorTimeout)

			logger.notice("Action processor ended")
			be.setStatusMessage(sessionId, _("Action processor ended"))
		except Exception as e:
			logger.logException(e)
			error = f"Failed to process action requests: {e}"
			if be:
				try:
					be.setStatusMessage(sessionId, error)
				except:
					pass
			logger.error(error)

		if depotShareMounted:
			try:
				logger.notice("Unmounting depot share")
				System.umount(depotDrive)
			except:
				pass
		if imp:
			try:
				imp.end()
			except:
				pass

		if be:
			try:
				be.backend_exit()
			except:
				pass
