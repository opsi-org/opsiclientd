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

import os
import sys
import gettext
import locale
from urllib.parse import urlparse

from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI import System

from opsicommon.logging import logger, init_logging, log_context, LOG_NONE

from opsiclientd import __version__, DEFAULT_STDERR_LOG_FORMAT, DEFAULT_FILE_LOG_FORMAT

def main(): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
	if len(sys.argv) != 17:
		print(
			f"Usage: {os.path.basename(sys.argv[0])} <hostId> <hostKey> <controlServerPort>"
			" <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword>"
			" <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout>"
			" <runAsUser> <runAsPassword> <createEnvironment>"
		)
		sys.exit(1)

	( # pylint: disable=unbalanced-tuple-unpacking
		hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl,
		depotDrive, depotServerUsername, depotServerPassword, sessionId,
		actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout,
		runAsUser, runAsPassword, createEnvironment
	) = sys.argv[1:]

	if hostKey:
		logger.addConfidentialString(hostKey)
	if depotServerPassword:
		logger.addConfidentialString(depotServerPassword)
	if runAsPassword:
		logger.addConfidentialString(runAsPassword)

	init_logging(
		stderr_level=LOG_NONE,
		stderr_format=DEFAULT_STDERR_LOG_FORMAT,
		log_file=logFile,
		file_level=int(logLevel),
		file_format=DEFAULT_FILE_LOG_FORMAT
	)

	with log_context({'instance' : os.path.basename(sys.argv[0])}):
		logger.debug(
			"Called with arguments: %s",
			', '.join((
				hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl,
				depotDrive, depotServerUsername, depotServerPassword, sessionId,
				actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout,
				runAsUser, runAsPassword, createEnvironment
			))
		)

		lang = None
		localeDir = None
		try:
			lang = locale.getdefaultlocale()[0].split('_')[0]
			localeDir = os.path.join(os.path.dirname(sys.argv[0]), 'locale')
			translation = gettext.translation('opsiclientd', localeDir, [lang])
			_ = translation.gettext
		except Exception as error: # pylint: disable=broad-except
			logger.debug("Failed to load locale for %s from %s: %s", lang, localeDir, error)

			def _(string):
				return string

		createEnvironment = bool(runAsUser and createEnvironment.lower() in ('yes', 'true', '1'))
		actionProcessorTimeout = int(actionProcessorTimeout)
		imp = None
		depotShareMounted = False
		be = None
		depot_url = urlparse(depotRemoteUrl)

		try:
			be = JSONRPCBackend(username=hostId, password=hostKey, address=f"https://localhost:{controlServerPort}/opsiclientd")

			if runAsUser:
				logger.info("Impersonating user '%s'", runAsUser)
				imp = System.Impersonate(username=runAsUser, password=runAsPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="INTERACTIVE", newDesktop=False, createEnvironment=createEnvironment)
			elif depot_url.scheme in ("smb", "cifs"):
				logger.info("Impersonating network account '%s'", depotServerUsername)
				imp = System.Impersonate(username=depotServerUsername, password=depotServerPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="NEW_CREDENTIALS")

			if depot_url.hostname.lower() not in ("127.0.0.1", "localhost"):
				logger.notice("Mounting depot share %s", depotRemoteUrl)
				be.setStatusMessage(sessionId, _("Mounting depot share %s") % depotRemoteUrl) # pylint: disable=no-member

				if runAsUser or depot_url.scheme not in ("smb", "cifs"):
					System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)
				else:
					System.mount(depotRemoteUrl, depotDrive)
				depotShareMounted = True

			logger.notice("Starting action processor")
			be.setStatusMessage(sessionId, _("Action processor is running")) # pylint: disable=no-member

			if imp:
				imp.runCommand(actionProcessorCommand, timeoutSeconds=actionProcessorTimeout)
			else:
				System.execute(actionProcessorCommand, waitForEnding=True, timeout=actionProcessorTimeout)

			logger.notice("Action processor ended")
			be.setStatusMessage(sessionId, _("Action processor ended")) # pylint: disable=no-member
		except Exception as err: # pylint: disable=broad-except
			logger.error(err, exc_info=True)
			error = f"Failed to process action requests: {err}"
			if be:
				try:
					be.setStatusMessage(sessionId, error)
				except Exception: # pylint: disable=broad-except
					pass
			logger.error(error)

		if depotShareMounted:
			try:
				logger.notice("Unmounting depot share")
				System.umount(depotDrive)
			except Exception: # pylint: disable=broad-except
				pass
		if imp:
			try:
				imp.end()
			except Exception: # pylint: disable=broad-except
				pass

		if be:
			try:
				be.backend_exit()
			except Exception: # pylint: disable=broad-except
				pass
