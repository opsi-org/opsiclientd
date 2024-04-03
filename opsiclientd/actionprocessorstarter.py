# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
action processor starter helper for windows
"""

import getpass
import gettext
import locale
import os
import sys
from ipaddress import IPv6Address, ip_address
from urllib.parse import urlparse

from OPSI import System  # type: ignore[import]
from OPSI.Backend.JSONRPC import JSONRPCBackend  # type: ignore[import]
from opsicommon.logging import (
	LOG_NONE,
	get_logger,
	init_logging,
	log_context,
	secret_filter,
)

from opsiclientd import DEFAULT_FILE_LOG_FORMAT, DEFAULT_STDERR_LOG_FORMAT

logger = get_logger()


def set_status_message(backend: JSONRPCBackend, session_id: str, message: str) -> None:
	if session_id == "-1":
		logger.debug("Not setting status message")
		return
	try:
		backend.setStatusMessage(session_id, message)
	except Exception as err:
		logger.warning("Failed to set status message: %s", err)


def main() -> None:
	if len(sys.argv) != 17:
		print(
			f"Usage: {os.path.basename(sys.argv[0])} <hostId> <hostKey> <controlServerPort>"
			" <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword>"
			" <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout>"
			" <runAsUser> <runAsPassword> <createEnvironment>"
		)
		sys.exit(1)

	(
		hostId,
		hostKey,
		controlServerPort,
		logFile,
		logLevel,
		depotRemoteUrl,
		depotDrive,
		depotServerUsername,
		depotServerPassword,
		sessionId,
		actionProcessorDesktop,
		actionProcessorCommand,
		actionProcessorTimeout,
		runAsUser,
		runAsPassword,
		createEnvironment,
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
		file_format=DEFAULT_FILE_LOG_FORMAT,
	)

	log_instance = f'{os.path.basename(sys.argv[0]).rsplit(".", 1)[0]}_s{sessionId}'
	with log_context({"instance": log_instance}):
		logger.debug(
			"Called with arguments: %s",
			", ".join(
				(
					hostId,
					hostKey,
					controlServerPort,
					logFile,
					logLevel,
					depotRemoteUrl,
					depotDrive,
					depotServerUsername,
					depotServerPassword,
					sessionId,
					actionProcessorDesktop,
					actionProcessorCommand,
					actionProcessorTimeout,
					runAsUser,
					runAsPassword,
					createEnvironment,
				)
			),
		)

		language = "en"
		try:
			language = locale.getlocale()[0].split("_")[0]  # type: ignore[union-attr]
		except Exception as err:
			logger.debug("Failed to find default language: %s", err)

		def _(message: str) -> str:
			"""Fallback function"""
			return message

		sp = None
		try:
			logger.debug("Loading translation for language '%s'", language)
			sp = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
			if os.path.exists(os.path.join(sp, "site-packages")):
				sp = os.path.join(sp, "site-packages")
			sp = os.path.join(sp, "opsiclientd_data", "locale")
			translation = gettext.translation("opsiclientd", sp, [language])
			_ = translation.gettext
		except Exception as err:
			logger.debug("Failed to load locale for %s from %s: %s", language, sp, err)

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
					imp.start(
						logonType="INTERACTIVE",
						newDesktop=False,
						createEnvironment=bool(runAsUser and createEnvironment.lower() in ("yes", "true", "1")),
					)
			elif depot_url.scheme in ("smb", "cifs"):
				logger.info("Impersonating network account '%s'", depotServerUsername)
				imp = System.Impersonate(username=depotServerUsername, password=depotServerPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="NEW_CREDENTIALS")

			if (depot_url.hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
				logger.notice("Mounting depot share %s", depotRemoteUrl)
				set_status_message(be, sessionId, _("Mounting depot share %s") % depotRemoteUrl)

				if runAsUser or depot_url.scheme not in ("smb", "cifs"):
					System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)
				else:
					try:
						if isinstance(ip_address(depot_url.hostname or ""), IPv6Address):
							depotRemoteUrl = (
								depotRemoteUrl.replace(
									depot_url.hostname or "",
									f"{(depot_url.hostname or '').replace(':', '-')}.ipv6-literal.net",
								)
								.replace("[", "")
								.replace("]", "")
							)
							logger.notice("Using windows workaround to mount depot %s", depotRemoteUrl)
					except ValueError as err:
						# Can be a hostname
						logger.debug("Failed to check ip format, using %s for depot mount: %s", depotRemoteUrl, err)

					System.mount(depotRemoteUrl, depotDrive)
				depotShareMounted = True

			logger.notice("Starting action processor")
			set_status_message(be, sessionId, _("Action processor is running"))

			if imp:
				imp.runCommand(actionProcessorCommand, timeoutSeconds=int(actionProcessorTimeout))
			else:
				System.execute(actionProcessorCommand, waitForEnding=True, timeout=int(actionProcessorTimeout))

			logger.notice("Action processor ended")
			set_status_message(be, sessionId, _("Action processor ended"))
		except Exception as err:
			logger.error(err, exc_info=True)
			error = f"Failed to process action requests: {err}"
			logger.error(error)
			if be:
				set_status_message(be, sessionId, error)

		if depotShareMounted:
			try:
				logger.notice("Unmounting depot share")
				System.umount(depotDrive)
			except Exception as err:
				logger.debug("Caught exception in umount: %s", err)
		if imp:
			try:
				imp.end()
			except Exception as err:
				logger.debug("Caught exception in end of impersonation: %s", err)

		if be:
			try:
				be.backend_exit()
			except Exception as err:
				logger.debug("Caught exception in backend_exit: %s", err)
