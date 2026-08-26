# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
action processor starter helper for windows
"""

import gettext
import locale
import os
import sys
from urllib.parse import urlparse

from opsi.logging import LOG_NONE, get_logger, log_context, logging_config, secret_filter
from opsi.opsi.service.client import ServiceClient, ServiceVerificationFlags
from opsi.process import run_command
from opsi.system.network import mount_network_share, unmount_network_share
from opsi_legacy import System

from opsiclientd import DEFAULT_FILE_LOG_FORMAT, DEFAULT_STDERR_LOG_FORMAT

logger = get_logger()


def set_status_message(service_client: ServiceClient, session_id: str, message: str) -> None:
	if session_id == "-1":
		logger.debug("Not setting status message")
		return
	try:
		service_client.jsonrpc(method="setStatusMessage", params=[session_id, message])
	except Exception as err:
		logger.warning("Failed to set status message: %s", err)


def main() -> None:
	if len(sys.argv) != 14:
		print(
			f"Usage: {os.path.basename(sys.argv[0])} <hostId> <hostKey> <controlServerPort>"
			" <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword>"
			" <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout> [impersonation]"
		)
		sys.exit(1)

	(
		host_id,
		host_key,
		control_server_port,
		log_file,
		log_level,
		depot_remote_url,
		depot_drive,
		depot_server_username,
		depot_server_password,
		session_id,
		action_processor_desktop,
		action_processor_command,
		action_processor_timeout,
	) = sys.argv[1:]

	no_impersonation = len(sys.argv) > 14 and sys.argv[14].lower() in ("0", "false", "no")

	if host_key:
		secret_filter.add_secrets(host_key)
	if depot_server_password:
		secret_filter.add_secrets(depot_server_password)

	logging_config(
		stderr_level=LOG_NONE,
		stderr_format=DEFAULT_STDERR_LOG_FORMAT,
		log_file=log_file,
		file_level=int(log_level),
		file_format=DEFAULT_FILE_LOG_FORMAT,
	)

	log_instance = f"{os.path.basename(sys.argv[0]).rsplit('.', 1)[0]}_s{session_id}"
	with log_context({"instance": log_instance}):
		logger.debug(
			"Called with arguments: %s",
			f"{host_id}, {host_key}, {control_server_port}, {log_file}, {log_level}, {depot_remote_url}, {depot_drive}, {depot_server_username}, {depot_server_password}, {session_id}, {action_processor_desktop}, {action_processor_command}, {action_processor_timeout}",
		)

		language = "en"
		try:
			language = locale.getlocale()[0].split("_")[0]  # ty: ignore[unresolved-attribute]
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
			_ = translation.gettext  # ty: ignore[invalid-assignment]
		except Exception as err:
			logger.debug("Failed to load locale for %s from %s: %s", language, sp, err)

		depot_share_mounted = False
		impersonation = None
		service_client = None
		depot_url = urlparse(depot_remote_url)

		try:
			service_client = ServiceClient(
				address=f"https://127.0.0.1:{control_server_port}/opsiclientd",
				username=host_id,
				password=host_key,
				verify=ServiceVerificationFlags.ACCEPT_ALL,
			)

			if (depot_url.hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
				logger.notice("Mounting depot share %s", depot_remote_url)
				set_status_message(service_client, session_id, _("Mounting depot share %s") % depot_remote_url)
				if depot_url.scheme in ("smb", "cifs") and not no_impersonation:
					logger.info("Impersonating network account '%s'", depot_server_username)
					impersonation = System.Impersonate(
						username=depot_server_username, password=depot_server_password, desktop=action_processor_desktop
					)
					impersonation.start(logonType="NEW_CREDENTIALS")
				mount_network_share(
					url=depot_remote_url, mount_point=depot_drive, username=depot_server_username, password=depot_server_password
				)
				depot_share_mounted = True

			logger.notice("Starting action processor")
			set_status_message(service_client, session_id, _("Action processor is running"))

			if impersonation:
				impersonation.runCommand(action_processor_command, timeoutSeconds=int(action_processor_timeout))
			else:
				run_command(action_processor_command, timeout=int(action_processor_timeout))

			logger.notice("Action processor ended")
			set_status_message(service_client, session_id, _("Action processor ended"))
		except Exception as err:
			logger.exception(err)
			error = f"Failed to process action requests: {err}"
			logger.error(error)
			if service_client:
				set_status_message(service_client, session_id, error)

		if depot_share_mounted:
			try:
				logger.notice("Unmounting depot share")
				unmount_network_share(depot_drive)
			except Exception as err:
				logger.error("Failed to unmount depot share: %s", err)

		if impersonation:
			try:
				impersonation.end()
			except Exception as err:
				logger.error("Failed to end impersonation: %s", err)

		if service_client:
			try:
				service_client.stop()
			except Exception as err:
				logger.error("Failed to stop service client: %s", err)
