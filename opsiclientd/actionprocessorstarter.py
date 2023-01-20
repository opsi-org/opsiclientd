# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
action processor starter helper for windows
"""

import os
import sys
import getpass
import gettext
import locale
from ipaddress import ip_address, IPv6Address
from urllib.parse import urlparse

from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend

from opsicommon.logging import logger, init_logging, log_context, LOG_NONE, secret_filter

from opsiclientd import __version__, DEFAULT_STDERR_LOG_FORMAT, DEFAULT_FILE_LOG_FORMAT


def set_status_message(backend, session_id, message):
	if session_id == "-1":
		logger.debug("Not setting status message")
		return
	try:
		backend.setStatusMessage(session_id, message)  # pylint: disable=no-member
	except Exception as err:  # pylint: disable=broad-except
		logger.warning("Failed to set status message: %s", err)


def main():  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
	if len(sys.argv) != 17:
		print(
			f"Usage: {os.path.basename(sys.argv[0])} <hostId> <hostKey> <controlServerPort>"
			" <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword>"
			" <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout>"
			" <runAsUser> <runAsPassword> <createEnvironment>"
		)
		sys.exit(1)

	(  # pylint: disable=unbalanced-tuple-unpacking
		hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl,
		depotDrive, depotServerUsername, depotServerPassword, sessionId,
		actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout,
		runAsUser, runAsPassword, createEnvironment
	) = sys.argv[1:]

	if hostKey:
		secret_filter.add_secrets(hostKey)
	if depotServerPassword:
		secret_filter.add_secrets(depotServerPassword)
	if runAsPassword:
		secret_filter.add_secrets(runAsPassword)

	init_logging(
		stderr_level=LOG_NONE,
		stderr_format=DEFAULT_STDERR_LOG_FORMAT,
		log_file=logFile,
		file_level=int(logLevel),
		file_format=DEFAULT_FILE_LOG_FORMAT
	)

	log_instance = f'{os.path.basename(sys.argv[0]).rsplit(".", 1)[0]}_s{sessionId}'
	with log_context({'instance': log_instance}):
		logger.debug(
			"Called with arguments: %s",
			', '.join((
				hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl,
				depotDrive, depotServerUsername, depotServerPassword, sessionId,
				actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout,
				runAsUser, runAsPassword, createEnvironment
			))
		)

		language = "en"
		try:
			language = locale.getdefaultlocale()[0].split('_')[0]
		except Exception as err:  # pylint: disable=broad-except
			logger.debug("Failed to find default language: %s", err)

		def _(string):
			""" Fallback function """
			return string

		sp = None
		try:
			logger.debug("Loading translation for language '%s'", language)
			sp = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
			if os.path.exists(os.path.join(sp, "site-packages")):
				sp = os.path.join(sp, "site-packages")
			sp = os.path.join(sp, 'opsiclientd_data', 'locale')
			translation = gettext.translation('opsiclientd', sp, [language])
			_ = translation.gettext
		except Exception as err:  # pylint: disable=broad-except
			logger.debug("Failed to load locale for %s from %s: %s", language, sp, err)

		createEnvironment = bool(runAsUser and createEnvironment.lower() in ('yes', 'true', '1'))
		actionProcessorTimeout = int(actionProcessorTimeout)
		imp = None
		depotShareMounted = False
		be = None
		depot_url = urlparse(depotRemoteUrl)

		try:
			be = JSONRPCBackend(username=hostId, password=hostKey, address=f"https://127.0.0.1:{controlServerPort}/opsiclientd")

			if runAsUser:
				if getpass.getuser().lower() != runAsUser.lower():
					logger.info("Impersonating user '%s'", runAsUser)
					imp = System.Impersonate(username=runAsUser, password=runAsPassword, desktop=actionProcessorDesktop)
					imp.start(logonType="INTERACTIVE", newDesktop=False, createEnvironment=createEnvironment)
			elif depot_url.scheme in ("smb", "cifs"):
				logger.info("Impersonating network account '%s'", depotServerUsername)
				imp = System.Impersonate(username=depotServerUsername, password=depotServerPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="NEW_CREDENTIALS")

			if depot_url.hostname.lower() not in ("127.0.0.1", "localhost", "::1"):
				logger.notice("Mounting depot share %s", depotRemoteUrl)
				set_status_message(be, sessionId, _("Mounting depot share %s") % depotRemoteUrl)  # pylint: disable=no-member

				if runAsUser or depot_url.scheme not in ("smb", "cifs"):
					System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)
				else:
					if isinstance(ip_address(depot_url.hostname), IPv6Address):
						depotRemoteUrl = depotRemoteUrl.replace(
							depot_url.hostname,
							f"{depot_url.hostname.replace(':', '-')}.ipv6-literal.net",
						).replace("[", "").replace("]", "")
						logger.notice("Using windows workaround to mount depot %s", depotRemoteUrl)
					System.mount(depotRemoteUrl, depotDrive)
				depotShareMounted = True

			logger.notice("Starting action processor")
			set_status_message(be, sessionId, _("Action processor is running"))  # pylint: disable=no-member

			if imp:
				imp.runCommand(actionProcessorCommand, timeoutSeconds=actionProcessorTimeout)
			else:
				System.execute(actionProcessorCommand, waitForEnding=True, timeout=actionProcessorTimeout)

			logger.notice("Action processor ended")
			set_status_message(be, sessionId, _("Action processor ended"))  # pylint: disable=no-member
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)
			error = f"Failed to process action requests: {err}"
			logger.error(error)
			if be:
				set_status_message(be, sessionId, error)

		if depotShareMounted:
			try:
				logger.notice("Unmounting depot share")
				System.umount(depotDrive)
			except Exception as error:  # pylint: disable=broad-except
				logger.debug("Caught exception in umount: %s", error)
		if imp:
			try:
				imp.end()
			except Exception as error:  # pylint: disable=broad-except
				logger.debug("Caught exception in end of impersonation: %s", error)

		if be:
			try:
				be.backend_exit()
			except Exception as error:  # pylint: disable=broad-except
				logger.debug("Caught exception in backend_exit: %s", error)
