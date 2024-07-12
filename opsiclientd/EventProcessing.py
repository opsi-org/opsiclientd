# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Processing of events.
"""

from __future__ import annotations

import datetime
import filecmp
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal
from urllib.parse import urlparse

import psutil  # type: ignore[import]
from OPSI import System  # type: ignore[import]
from OPSI.Object import ProductOnClient  # type: ignore[import]
from OPSI.Util.Message import (  # type: ignore[import]
	ChoiceSubject,
	MessageSubject,
	MessageSubjectProxy,
	ProgressSubjectProxy,
)
from OPSI.Util.Path import cd  # type: ignore[import]
from OPSI.Util.Thread import KillableThread  # type: ignore[import]
from opsicommon.logging import (  # type: ignore[import]
	LOG_INFO,
	get_logger,
	log_context,
	logging_config,
)
from opsicommon.objects import Product
from opsicommon.types import (  # type: ignore[import]
	forceInt,
	forceStringList,
	forceUnicode,
	forceUnicodeLower,
)

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.Events.SyncCompleted import SyncCompletedEvent
from opsiclientd.Events.Utilities.Generators import reconfigureEventGenerators
from opsiclientd.Exceptions import CanceledByUserError, ConfigurationError
from opsiclientd.Localization import _
from opsiclientd.notification_server import NotificationServer
from opsiclientd.OpsiService import ServiceConnection
from opsiclientd.State import State
from opsiclientd.SystemCheck import (
	RUNNING_ON_DARWIN,
	RUNNING_ON_LINUX,
	RUNNING_ON_MACOS,
	RUNNING_ON_WINDOWS,
)
from opsiclientd.Timeline import Timeline
from opsiclientd.utils import (
	get_include_exclude_product_ids,
	get_version_from_dos_binary,
	get_version_from_elf_binary,
	get_version_from_mach_binary,
)

if RUNNING_ON_WINDOWS:
	from opsiclientd.windows import runCommandInSession
else:
	from OPSI.System import runCommandInSession  # type: ignore

if TYPE_CHECKING:
	from subprocess import Popen

	from opsiclientd.Events.Basic import Event
	from opsiclientd.Opsiclientd import Opsiclientd


logger = get_logger()
config = Config()
state = State()
timeline = Timeline()


@dataclass
class ProductInfo:
	id: str
	productVersion: str
	packageVersion: str
	name: str


class EventProcessingCanceled(Exception):
	pass


class EventProcessingThread(KillableThread, ServiceConnection):
	def __init__(self, opsiclientd: Opsiclientd, event: Event) -> None:
		KillableThread.__init__(self, name="EventProcessingThread")
		ServiceConnection.__init__(self, opsiclientd)

		self.opsiclientd = opsiclientd
		self.event = event

		self.running = False
		self.actionCancelled = False
		self.waitCancelled = False
		self._is_cancelable = False
		self._should_cancel = False

		self.shutdownCancelled = False
		self.shutdownWaitCancelled = False

		self._serviceConnection = None

		self._notificationServer: NotificationServer | None = None

		self._depotShareMounted = False

		self._statusSubject = MessageSubject("status")
		self._messageSubject = MessageSubject("message")
		self._serviceUrlSubject = MessageSubject("configServiceUrl")
		self._clientIdSubject = MessageSubject("clientId")
		self._actionProcessorInfoSubject = MessageSubject("actionProcessorInfo")
		self._opsiclientdInfoSubject = MessageSubject("opsiclientdInfo")
		self._detailSubjectProxy = MessageSubjectProxy("detail")
		self._currentProgressSubjectProxy = ProgressSubjectProxy("currentProgress", fireAlways=False)
		self._overallProgressSubjectProxy = ProgressSubjectProxy("overallProgress", fireAlways=False)
		self._choiceSubject = None
		self._notificationServerShouldStop = False

		self._statusSubject.setMessage(_("Processing event %s") % self.event.eventConfig.getName())
		self._clientIdSubject.setMessage(config.get("global", "host_id"))
		self._opsiclientdInfoSubject.setMessage(f"opsiclientd {__version__}")
		self._actionProcessorInfoSubject.setMessage("")

		self._shutdownWarningRepetitionTime = self.event.eventConfig.shutdownWarningRepetitionTime
		self._shutdownWarningTime = self.event.eventConfig.shutdownWarningTime

		self.isLoginEvent = bool(self.event.eventConfig.actionType == "login")
		if self.isLoginEvent:
			logger.info("Event is user login event")

	def _cancelable_sleep(self, secs: int) -> bool:
		"""Wait for the given number of seconds.
		The running event can be canceled in the meantime.
		Returns whether the number of seconds to wait corresponds
		to the actual time elapsed (no standby / wakeup occured)."""
		start = time.time()
		while True:
			seconds_remaining = secs - (time.time() - start)
			if seconds_remaining <= -60:
				# Time jump possibly caused by standby
				return False
			if seconds_remaining <= 0:
				return True
			if self._is_cancelable and self._should_cancel:
				raise EventProcessingCanceled()
			time.sleep(1)

	def is_cancelable(self) -> bool:
		return self._is_cancelable

	def _set_cancelable(self, cancelable: bool) -> None:
		assert self.opsiclientd
		if cancelable:
			with self.opsiclientd.eventLock:
				self._is_cancelable = True
				if self._should_cancel:
					raise EventProcessingCanceled()
		else:
			while not self.opsiclientd.eventLock.acquire():
				self._cancelable_sleep(1)
			try:
				self._is_cancelable = False
			finally:
				self.opsiclientd.eventLock.release()

	def should_cancel(self) -> bool:
		return self._should_cancel

	# use no_lock only if you have already acquired the lock
	def cancel(self, no_lock: bool = False) -> None:
		if no_lock:
			if not self._is_cancelable:
				raise RuntimeError("Event processing currently not cancelable")
			self._should_cancel = True
		else:
			assert self.opsiclientd
			with self.opsiclientd.eventLock:
				if not self._is_cancelable:
					raise RuntimeError("Event processing currently not cancelable")
				self._should_cancel = True

	# ServiceConnection
	def connectionThreadOptions(self) -> dict[str, MessageSubject]:
		return {"statusSubject": self._statusSubject}

	def connectionStart(self, configServiceUrl: str) -> None:
		self._serviceUrlSubject.setMessage(configServiceUrl)
		try:
			cancellableAfter = forceInt(config.get("config_service", "user_cancelable_after"))
			if self._notificationServer and cancellableAfter >= 0:
				logger.info("User is allowed to cancel connection after %d seconds", cancellableAfter)
				self._choiceSubject = ChoiceSubject(id="choice")
		except Exception as err:
			logger.error(err)

	def connectionCancelable(self, stopConnectionCallback: Callable) -> None:
		if self._notificationServer and self._choiceSubject:
			self._choiceSubject.setChoices(["Stop connection"])
			self._choiceSubject.setCallbacks([stopConnectionCallback])
			self._notificationServer.addSubject(self._choiceSubject)

	def connectionTimeoutChanged(self, timeout: float) -> None:
		if self._detailSubjectProxy:
			self._detailSubjectProxy.setMessage(_("Timeout: %ds") % timeout)

	def connectionCanceled(self) -> None:
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage("")
		ServiceConnection.connectionCanceled(self)

	def connectionTimedOut(self) -> None:
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage("")
		ServiceConnection.connectionTimedOut(self)

	def connectionEstablished(self) -> None:
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage("")

	def connectionFailed(self, error: str) -> None:
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage("")
		ServiceConnection.connectionFailed(self, error)

	# End of ServiceConnection

	def getSessionId(self) -> int:
		if RUNNING_ON_WINDOWS:
			if self.isLoginEvent:
				user_session_ids = System.getUserSessionIds(self.event.eventInfo["User"])
				if user_session_ids:
					session_id = user_session_ids[0]
					logger.info("Using session id of user '%s': %s", self.event.eventInfo["User"], session_id)
					return session_id

			# Prefer active console/rdp sessions
			for session in System.getActiveSessionInformation():
				if session.get("StateName") == "active":
					session_id = session["SessionId"]
					logger.info("Using session id of user '%s': %s", session.get("UserName"), session_id)
					return session_id

			session_id = System.getActiveConsoleSessionId()
			logger.info("Using active console session id: %s", session_id)
			return session_id

		session_id = System.getActiveSessionId()
		logger.info("Using active session id: %s", session_id)
		return session_id

	def setStatusMessage(self, message: str) -> None:
		logger.debug("Setting status message to: %s", message)
		self._statusSubject.setMessage(message)

	@property
	def notificationServerPort(self) -> int | None:
		if not self._notificationServer:
			return None
		return self._notificationServer.port

	def startNotificationServer(self) -> None:
		logger.notice("Starting notification server")

		try:
			self._notificationServerShouldStop = False
			start_delay = config.get("notification_server", "start_delay") or 0
			if start_delay and start_delay > 0:
				logger.notice("Starting control server with delay of %d seconds", start_delay)
				for _ in range(start_delay):
					if self._notificationServerShouldStop:
						return
					time.sleep(1)

			self._notificationServer = NotificationServer(
				address=config.get("notification_server", "interface"),
				start_port=forceInt(config.get("notification_server", "start_port")),
				subjects=[
					self._statusSubject,
					self._messageSubject,
					self._serviceUrlSubject,
					self._clientIdSubject,
					self._actionProcessorInfoSubject,
					self._opsiclientdInfoSubject,
					self._detailSubjectProxy,
					self._currentProgressSubjectProxy,
					self._overallProgressSubjectProxy,
				],
			)
			with log_context({"instance": "notification server"}):
				self._notificationServer.start_and_wait(timeout=30)
				logger.notice("Notification server started (listening on port %d)", self.notificationServerPort)
		except Exception as err:
			logger.error("Failed to start notification server: %s", err)
			raise RuntimeError(f"Failed to start notification server: {err}") from err

	def _stopNotificationServer(self) -> None:
		try:
			logger.info("Stopping notification server")
			self._notificationServerShouldStop = True
			if self._notificationServer:
				self._notificationServer.stop()
		except Exception as err:
			logger.error(err, exc_info=True)

	def stopNotificationServer(self) -> None:
		if not self._notificationServer:
			return
		threading.Thread(target=self._stopNotificationServer, name="stopNotificationServer").start()

	def getConfigFromService(self) -> None:
		"""Get settings from service"""
		logger.notice("Getting config from service")
		try:
			assert self.opsiclientd
			if not self.isConfigServiceConnected():
				logger.warning("Cannot get config from service: not connected")
				return
			self.setStatusMessage(_("Getting config from service"))
			config.getFromService(self._configService)
			config.updateConfigFile(force=True)
			self.setStatusMessage(_("Got config from service"))
			logger.notice("Reconfiguring event generators")
			reconfigureEventGenerators()
			if config.get("config_service", "permanent_connection"):
				self.opsiclientd.start_permanent_service_connection()
			else:
				self.opsiclientd.stop_permanent_service_connection()

		except Exception as err:
			logger.error("Failed to get config from service: %s", err)
			raise

	def writeLogToService(self) -> None:
		logger.notice("Writing log to service")
		try:
			if not self._configService or not self.isConfigServiceConnected():
				logger.warning("Cannot write log to service: not connected")
				return

			self.setStatusMessage(_("Writing log to service"))

			data = ""
			size = os.path.getsize(config.get("global", "log_file"))
			with open(config.get("global", "log_file"), "rb") as file:
				max_size = 5_000_000
				try:
					max_size = int(float(config.get("global", "max_log_transfer_size")) * 1_000_000)
				except ValueError as err:
					logger.error(err, exc_info=True)
				if max_size and size > max_size:
					file.seek(size - max_size)
					# Read to next newline character
					file.readline()
				data = file.read().decode("utf-8", errors="replace").replace("\ufffd", "?")

			data += "-------------------- submitted part of log file ends here, see the rest of log file on client --------------------\n"
			# Do not log jsonrpc request
			if config.get("global", "log_level") > LOG_INFO:
				logging_config(file_level=LOG_INFO)
			try:
				self._configService.log_write("clientconnect", data=data, objectId=config.get("global", "host_id"), append=False)
			finally:
				logging_config(file_level=config.get("global", "log_level"))
		except Exception as err:
			logger.error("Failed to write log to service: %s", err, exc_info=True)
			raise

	def runCommandInSession(
		self,
		command: str | list[str],
		sessionId: int | None = None,
		desktop: str | None = None,
		waitForProcessEnding: bool = False,
		timeoutSeconds: int = 0,
		noWindow: bool = False,
	) -> tuple[Popen | int | None, int | None]:
		if sessionId is None:
			sessionId = self.getSessionId()

		if not desktop or (forceUnicodeLower(desktop) == "current"):
			if self.isLoginEvent:
				desktop = "default"
			else:
				logger.debug("Getting current active desktop name")
				assert self.opsiclientd
				desktop = forceUnicodeLower(self.opsiclientd.getCurrentActiveDesktopName(sessionId))
				logger.debug("Got current active desktop name: %s", desktop)

		if not desktop:
			desktop = "winlogon"

		processId = None
		try:
			process, _hThread, processId, _dwThreadId = runCommandInSession(
				command=command,
				sessionId=sessionId,
				desktop=desktop,
				waitForProcessEnding=waitForProcessEnding,
				timeoutSeconds=timeoutSeconds,
				noWindow=noWindow,
				shell=False,
			)
		except Exception as err:
			logger.error(err, exc_info=True)

		return process, processId

	def startNotifierApplication(
		self,
		command: str,
		notifierId: Literal["block_login", "popup", "motd", "action", "shutdown", "shutdown_select", "event", "userlogin"],
		sessionId: int | None = None,
		desktop: str | None = None,
	) -> tuple[Popen | int | None, int | None]:
		if sessionId is None:
			sessionId = self.getSessionId()

		logger.notice("Starting notifier application in session '%s' on desktop '%s'", sessionId, desktop)
		try:
			assert self.opsiclientd
			command, _elevation_required = self.opsiclientd.getNotifierCommand(
				command=command, notifier_id=notifierId, port=self.notificationServerPort, desktop=desktop
			)
			process, pid = self.runCommandInSession(
				sessionId=sessionId,
				# Call process directly without shell for posix, keep string structure for windows
				command=command if RUNNING_ON_WINDOWS else shlex.split(command),
				desktop=desktop,
				waitForProcessEnding=False,
			)
			logger.debug("Starting notifier with pid %s", pid)
			return process, pid
		except Exception as err:
			logger.error("Failed to start notifier application '%s': %s", command, err)
		return None, None

	def closeProcessWindows(self, processId: int) -> None:
		try:
			opsiclientd_rpc = config.get("opsiclientd_rpc", "command")
			command = f'{opsiclientd_rpc} "exit(); System.closeProcessWindows(processId={processId})"'
		except Exception as err:
			raise RuntimeError(f"opsiclientd_rpc command not defined: {err}") from err

		# TODO: collect exit codes to avoid Zombie Process
		self.runCommandInSession(command=command, waitForProcessEnding=False, noWindow=True)

	def setActionProcessorInfo(self) -> None:
		action_processor_filename = config.get("action_processor", "filename")
		action_processor_local_dir = config.get("action_processor", "local_dir")
		action_processor_local_file = os.path.join(action_processor_local_dir, action_processor_filename)
		name = os.path.basename(action_processor_local_file).replace(".exe", "")
		version = "?"
		try:
			if RUNNING_ON_WINDOWS:
				version = get_version_from_dos_binary(action_processor_local_file)
			elif RUNNING_ON_LINUX:
				version = get_version_from_elf_binary(action_processor_local_file)
			elif RUNNING_ON_MACOS:
				version = get_version_from_mach_binary(action_processor_local_file)
		except ValueError as err:
			logger.error(err)

		logger.notice("Action processor name '%s', version '%s'", name, version)
		self._actionProcessorInfoSubject.setMessage(f"{name} {version}")

	def mountDepotShare(self) -> None:
		if self._depotShareMounted:
			logger.debug("Depot share already mounted")
			return
		if not config.get("depot_server", "url"):
			raise RuntimeError("Cannot mount depot share, depot_server.url undefined")
		if config.get("depot_server", "url").split("/")[2] in ("127.0.0.1", "localhost", "::1"):
			logger.notice("No need to mount depot share %s, working on local depot cache", config.get("depot_server", "url"))
			return

		logger.notice("Mounting depot share %s", config.get("depot_server", "url"))
		self.setStatusMessage(_("Mounting depot share %s") % config.get("depot_server", "url"))

		mount_options = {}
		(mount_username, mount_password) = config.getDepotserverCredentials(configService=self._configService)

		if RUNNING_ON_WINDOWS:
			url = urlparse(config.get("depot_server", "url"))
			try:
				if url.scheme in ("smb", "cifs"):
					System.setRegistryValue(
						System.HKEY_LOCAL_MACHINE,
						f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\ZoneMap\\Domains\\{url.hostname}",
						"file",
						1,
					)
				elif url.scheme in ("webdavs", "https"):
					System.setRegistryValue(
						System.HKEY_LOCAL_MACHINE,
						f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\ZoneMap\\Domains\\{url.hostname}@SSL@{url.port}",
						"file",
						1,
					)
					System.setRegistryValue(
						System.HKEY_LOCAL_MACHINE,
						"SYSTEM\\CurrentControlSet\\Services\\WebClient\\Parameters",
						"FileSizeLimitInBytes",
						0xFFFFFFFF,
					)
				logger.info("Added depot '%s' to trusted domains", url.hostname)
			except Exception as err:
				logger.error("Failed to add depot to trusted domains: %s", err)

		elif RUNNING_ON_LINUX or RUNNING_ON_DARWIN:
			mount_options["ro"] = ""
			if RUNNING_ON_LINUX:
				mount_options["dir_mode"] = "0700"
				mount_options["file_mode"] = "0700"
				# Currently for WebDAV and Linux only
				mount_options["verify_server_cert"] = config.get("global", "verify_server_cert") or config.get(
					"global", "verify_server_cert_by_ca"
				)
				mount_options["ca_cert_file"] = config.ca_cert_file

		depot_server_url = config.get("depot_server", "url")
		if RUNNING_ON_WINDOWS:
			depot_url_parsed = urlparse(depot_server_url)
			try:
				if isinstance(ip_address(depot_url_parsed.hostname), IPv6Address):
					depot_server_url = (
						depot_server_url.replace(
							depot_url_parsed.hostname,
							f"{depot_url_parsed.hostname.replace(':', '-')}.ipv6-literal.net",
						)
						.replace("[", "")
						.replace("]", "")
					)
					logger.notice("Using windows workaround to mount depot %s", depot_server_url)
			except ValueError as error:
				logger.info("Not an IP address '%s', using %s for depot mount: %s", depot_url_parsed.hostname, depot_server_url, error)
		System.mount(depot_server_url, config.getDepotDrive(), username=mount_username, password=mount_password, **mount_options)

		self._depotShareMounted = True

	def umountDepotShare(self) -> None:
		if not self._depotShareMounted:
			logger.debug("Depot share not mounted")
			return
		try:
			logger.notice("Unmounting depot share")
			System.umount(config.getDepotDrive())
			self._depotShareMounted = False
		except Exception as err:
			logger.warning(err)

	def updateActionProcessor(self) -> None:
		logger.notice("Updating action processor")
		self.setStatusMessage(_("Updating action processor"))

		try:
			assert self.opsiclientd
			assert self._configService
			url = urlparse(config.get("depot_server", "url"))
			actionProcessorRemoteDir = None
			actionProcessorCommonDir = None
			if url.hostname.lower() in ("127.0.0.1", "localhost", "::1"):
				dirname = config.get("action_processor", "remote_dir")
				dirname.lstrip(os.sep)
				dirname.lstrip("install" + os.sep)
				dirname.lstrip(os.sep)
				actionProcessorRemoteDir = os.path.join(self.opsiclientd.getCacheService().getProductCacheDir(), dirname)
				commonname = config.get("action_processor", "remote_common_dir")
				commonname.lstrip(os.sep)
				commonname.lstrip("install" + os.sep)
				commonname.lstrip(os.sep)
				actionProcessorCommonDir = os.path.join(self.opsiclientd.getCacheService().getProductCacheDir(), commonname)
				logger.notice(
					"Updating action processor from local cache '%s' (common dir '%s')", actionProcessorRemoteDir, actionProcessorCommonDir
				)
			else:
				dd = config.getDepotDrive()
				if RUNNING_ON_WINDOWS:
					dd += os.sep
				dirname = config.get("action_processor", "remote_dir")
				dirname.lstrip(os.sep)
				actionProcessorRemoteDir = os.path.join(dd, dirname)
				commonname = config.get("action_processor", "remote_common_dir")
				commonname.lstrip(os.sep)
				actionProcessorCommonDir = os.path.join(dd, commonname)
				logger.notice(
					"Updating action processor from depot dir '%s' (common dir '%s')", actionProcessorRemoteDir, actionProcessorCommonDir
				)

			actionProcessorFilename = config.get("action_processor", "filename")
			actionProcessorLocalDir = config.get("action_processor", "local_dir")
			assert actionProcessorFilename
			assert actionProcessorLocalDir
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorRemoteFile = os.path.join(actionProcessorRemoteDir, actionProcessorFilename)

			if not os.path.exists(actionProcessorLocalFile):
				logger.notice("Action processor needs update because file '%s' not found", actionProcessorLocalFile)
			elif abs(os.stat(actionProcessorLocalFile).st_mtime - os.stat(actionProcessorRemoteFile).st_mtime) > 10:
				logger.notice("Action processor needs update because modification time difference is more than 10 seconds")
			elif not filecmp.cmp(actionProcessorLocalFile, actionProcessorRemoteFile):
				logger.notice("Action processor needs update because file changed")
			else:
				logger.notice("Local action processor exists and seems to be up to date")
				if self.event.eventConfig.useCachedProducts:
					self._configService.productOnClient_updateObjects(
						[
							ProductOnClient(
								productId=config.action_processor_name,
								productType="LocalbootProduct",
								clientId=config.get("global", "host_id"),
								installationStatus="installed",
								actionProgress="",
							)
						]
					)
				return actionProcessorLocalFile

			if RUNNING_ON_WINDOWS:
				logger.info("Checking if action processor files are in use")
				for proc in psutil.process_iter():
					try:
						full_path = proc.exe()
						if full_path and not os.path.relpath(full_path, actionProcessorLocalDir).startswith(".."):
							raise RuntimeError(f"Action processor files are in use by process '{full_path}''")
					except (PermissionError, psutil.AccessDenied, ValueError):
						pass

			# Update files
			if "opsi-script" in actionProcessorLocalDir:
				self.updateActionProcessorUnified(actionProcessorRemoteDir, actionProcessorCommonDir)
			else:
				self.updateActionProcessorOld(actionProcessorRemoteDir)
			logger.notice("Local action processor successfully updated")

			productVersion = None
			packageVersion = None
			for productOnDepot in self._configService.productOnDepot_getIdents(
				productType="LocalbootProduct",
				productId=config.action_processor_name,
				depotId=config.get("depot_server", "depot_id"),
				returnType="dict",
			):
				productVersion = productOnDepot["productVersion"]
				packageVersion = productOnDepot["packageVersion"]
			self._configService.productOnClient_updateObjects(
				[
					ProductOnClient(
						productId=config.action_processor_name,
						productType="LocalbootProduct",
						productVersion=productVersion,
						packageVersion=packageVersion,
						clientId=config.get("global", "host_id"),
						installationStatus="installed",
						actionProgress="",
						actionResult="successful",
					)
				]
			)
			try:
				self.setActionProcessorInfo()
			except Exception as err:
				logger.error("Failed to set action processor info: %s", err)

		except Exception as err:
			logger.error("Failed to update action processor: %s", err, exc_info=True)

	def updateActionProcessorUnified(self, actionProcessorRemoteDir: str, actionProcessorCommonDir: str) -> None:
		actionProcessorFilename = config.get("action_processor", "filename")
		actionProcessorLocalDir = config.get("action_processor", "local_dir")
		actionProcessorLocalTmpDir = actionProcessorLocalDir + ".tmp"
		actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)

		logger.notice("Start copying the action processor files")
		if os.path.exists(actionProcessorLocalTmpDir):
			logger.info("Deleting dir '%s'", actionProcessorLocalTmpDir)
			shutil.rmtree(actionProcessorLocalTmpDir)
		logger.info("Copying from '%s' to '%s'", actionProcessorRemoteDir, actionProcessorLocalTmpDir)
		shutil.copytree(actionProcessorRemoteDir, actionProcessorLocalTmpDir)
		if RUNNING_ON_LINUX or RUNNING_ON_WINDOWS:
			for common in os.listdir(actionProcessorCommonDir):
				source = os.path.join(actionProcessorCommonDir, common)
				if os.path.isdir(source):
					shutil.copytree(source, os.path.join(actionProcessorLocalTmpDir, common))
				else:
					shutil.copy2(source, os.path.join(actionProcessorLocalTmpDir, common))
		if RUNNING_ON_WINDOWS:
			# saving current opsi-script skin (set during opsi-client-agent setup with optional corporate identity)
			if os.path.exists(os.path.join(actionProcessorLocalDir, "skin")) and os.listdir(os.path.join(actionProcessorLocalDir, "skin")):
				if os.path.exists(os.path.join(actionProcessorLocalTmpDir, "skin")):
					shutil.rmtree(os.path.join(actionProcessorLocalTmpDir, "skin"))
				shutil.move(os.path.join(actionProcessorLocalDir, "skin"), os.path.join(actionProcessorLocalTmpDir, "skin"))

		if not os.path.exists(os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)):
			raise RuntimeError(f"File '{os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)}' does not exist after copy")

		if os.path.exists(actionProcessorLocalDir):
			logger.info("Deleting dir '%s'", actionProcessorLocalDir)
			shutil.rmtree(actionProcessorLocalDir)

		logger.info("Moving dir '%s' to '%s'", actionProcessorLocalTmpDir, actionProcessorLocalDir)
		shutil.move(actionProcessorLocalTmpDir, actionProcessorLocalDir)

		if RUNNING_ON_WINDOWS:
			logger.notice("Setting permissions for opsi-script")
			opsi_script_dir = actionProcessorLocalDir.replace("\\\\", "\\")
			System.execute(f'icacls "{opsi_script_dir}" /q /c /t /reset', shell=False)
			System.execute(f'icacls "{opsi_script_dir}" /grant *S-1-5-32-545:(OI)(CI)RX', shell=False)
		else:
			if RUNNING_ON_LINUX:
				symlink = os.path.join("/usr/bin", actionProcessorFilename.split("/")[-1])
			if RUNNING_ON_DARWIN:
				symlink = os.path.join("/usr/local/bin", actionProcessorFilename.split("/")[-1])
			logger.info("Making symlink '%s' to '%s'", symlink, actionProcessorLocalFile)
			if os.path.exists(symlink):
				if not os.path.islink(symlink):
					logger.warning("replacing binary '%s' with symlink to %s", symlink, actionProcessorLocalFile)
				os.remove(symlink)
			os.symlink(actionProcessorLocalFile, symlink)

			logger.info("Setting Permissions for actionProcessorLocalDir '%s'", actionProcessorLocalDir)
			os.chmod(symlink, 0o755)
			os.chmod(actionProcessorLocalDir, 0o755)
			for root, dirs, files in os.walk(actionProcessorLocalDir):
				for filename in files:
					os.chmod(os.path.join(root, filename), 0o755)
				for subdir in dirs:
					os.chmod(os.path.join(root, subdir), 0o755)

	def updateActionProcessorOld(self, actionProcessorRemoteDir: str) -> None:
		if not RUNNING_ON_WINDOWS and not RUNNING_ON_LINUX:
			logger.error("Update of action processor without installed opsi-script package not implemented on this os")
			return

		actionProcessorFilename = config.get("action_processor", "filename")
		actionProcessorLocalDir = config.get("action_processor", "local_dir")
		actionProcessorLocalTmpDir = actionProcessorLocalDir + ".tmp"

		logger.notice("Start copying the action processor files")
		if RUNNING_ON_WINDOWS:
			if os.path.exists(actionProcessorLocalTmpDir):
				logger.info("Deleting dir '%s'", actionProcessorLocalTmpDir)
				shutil.rmtree(actionProcessorLocalTmpDir)
			logger.info("Copying from '%s' to '%s'", actionProcessorRemoteDir, actionProcessorLocalTmpDir)
			shutil.copytree(actionProcessorRemoteDir, actionProcessorLocalTmpDir)

			if not os.path.exists(os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)):
				raise RuntimeError(f"File '{os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)}' does not exist after copy")

			if os.path.exists(actionProcessorLocalDir):
				logger.info("Deleting dir '%s'", actionProcessorLocalDir)
				shutil.rmtree(actionProcessorLocalDir)

			logger.info("Moving dir '%s' to '%s'", actionProcessorLocalTmpDir, actionProcessorLocalDir)
			shutil.move(actionProcessorLocalTmpDir, actionProcessorLocalDir)

			logger.notice("Trying to set the right permissions for opsi-winst")
			setaclcmd = os.path.join(config.get("global", "base_dir"), "utilities", "setacl.exe")
			winstdir = actionProcessorLocalDir.replace("\\\\", "\\")
			cmd = (
				f'"{setaclcmd}" -on "{winstdir}" -ot file'
				' -actn ace -ace "n:S-1-5-32-544;p:full;s:y" -ace "n:S-1-5-32-545;p:read_ex;s:y"'
				' -actn clear -clr "dacl,sacl" -actn rstchldrn -rst "dacl,sacl"'
			)
			System.execute(cmd, shell=False)
		elif RUNNING_ON_LINUX:
			logger.info("Copying from '%s' to '%s'", actionProcessorRemoteDir, actionProcessorLocalDir)
			for fn in os.listdir(actionProcessorRemoteDir):
				if os.path.isfile(os.path.join(actionProcessorRemoteDir, fn)):
					shutil.copy2(os.path.join(actionProcessorRemoteDir, fn), os.path.join(actionProcessorLocalDir, fn))
				else:
					logger.warning(
						"Skipping '%s' while updating action processor because it is not a file", os.path.join(actionProcessorRemoteDir, fn)
					)

	def processUserLoginActions(self) -> None:
		self.setStatusMessage(_("Processing login actions"))
		try:
			if not self._configService:
				raise RuntimeError("Not connected to config service")

			productsByIdAndVersion: dict[str, dict[str, dict[str, Product]]] = {}
			for product in self._configService.product_getObjects(type="LocalbootProduct", userLoginScript="*.*"):
				if product.id not in productsByIdAndVersion:
					productsByIdAndVersion[product.id] = {}
				if product.productVersion not in productsByIdAndVersion[product.id]:
					productsByIdAndVersion[product.id][product.productVersion] = {}
				productsByIdAndVersion[product.id][product.productVersion][product.packageVersion] = product

			if not productsByIdAndVersion:
				logger.notice("No user login script found, nothing to do")
				return

			clientToDepotservers = self._configService.configState_getClientToDepotserver(clientIds=config.get("global", "host_id"))
			if not clientToDepotservers:
				raise RuntimeError(f"Failed to get depotserver for client '{config.get('global', 'host_id')}'")
			depotId = clientToDepotservers[0]["depotId"]

			dd = config.getDepotDrive()
			if RUNNING_ON_WINDOWS:
				dd += os.sep
			productDir = os.path.join(dd, "install")

			userLoginScripts = []
			productInfo: list[ProductInfo] = []
			for productOnDepot in self._configService.productOnDepot_getIdents(
				productType="LocalbootProduct", depotId=depotId, returnType="dict"
			):
				product = (
					productsByIdAndVersion.get(productOnDepot["productId"], {})
					.get(productOnDepot["productVersion"], {})
					.get(productOnDepot["packageVersion"])
				)
				if not product:
					continue
				logger.info(
					"User login script '%s' found for product %s_%s-%s",
					product.userLoginScript,
					product.id,
					product.productVersion,
					product.packageVersion,
				)
				userLoginScripts.append(os.path.join(productDir, product.userLoginScript))
				productInfo.append(ProductInfo(product.id, product.productVersion, product.packageVersion, product.name))

			if not userLoginScripts:
				logger.notice("No user login script found, nothing to do")
				return

			logger.notice("User login scripts found, executing")
			additionalParams = f"/usercontext {self.event.eventInfo.get('User')}"
			self.runActions(productInfo, additionalParams)

		except Exception as err:
			logger.error("Failed to process login actions: %s", err, exc_info=True)
			self.setStatusMessage(_("Failed to process login actions: %s") % forceUnicode(err))

	def processProductActionRequests(self) -> None:
		self.setStatusMessage(_("Getting action requests from config service"))

		try:
			assert self.opsiclientd
			bootmode = None
			if RUNNING_ON_WINDOWS:
				try:
					bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode").upper()
				except Exception as err:
					logger.warning("Failed to get bootmode from registry: %s", err)
			bootmode = bootmode or "BKSTD"

			if not self._configService:
				raise RuntimeError("Not connected to config service")

			productIds: list[str] = []
			productInfo: list[ProductInfo] = []
			includeProductIds: list[str] = []
			excludeProductIds: list[str] = []
			actionRequests = ["setup", "uninstall", "update", "always", "once", "custom"]

			if self.event.eventConfig.actionProcessorProductIds:
				includeProductIds = self.event.eventConfig.actionProcessorProductIds
				actionRequests = []
			else:
				if self.event.eventInfo.get("product_ids"):
					includeProductIds = forceStringList(self.event.eventInfo["product_ids"])
					logger.notice("Got product IDs from eventConfig: %r", includeProductIds)
				else:
					includeProductIds, excludeProductIds = get_include_exclude_product_ids(
						self._configService, self.event.eventConfig.includeProductGroupIds, self.event.eventConfig.excludeProductGroupIds
					)

			for productOnClient in [
				poc
				for poc in self._configService.productOnClient_getObjects(
					productType="LocalbootProduct",
					clientId=config.get("global", "host_id"),
					actionRequest=actionRequests,
					attributes=["actionRequest", "productVersion", "packageVersion"],
					productId=includeProductIds,
				)
				if poc.productId not in excludeProductIds
			]:
				if productOnClient.productId not in productIds:
					productIds.append(productOnClient.productId)
					productInfo.append(
						ProductInfo(
							productOnClient.productId,
							productOnClient.productVersion,
							productOnClient.packageVersion,
							"",
						)
					)
					logger.notice(
						"   [%2s] product %-20s %s", len(productIds), productOnClient.productId + ":", productOnClient.actionRequest
					)

			if (not productIds) and bootmode == "BKSTD":
				logger.notice("No product action requests set")
				self.setStatusMessage(_("No product action requests set"))
				state.set("installation_pending", "false")
				try:
					if self.event.eventConfig.useCachedConfig:
						self.opsiclientd.getCacheService().setConfigCacheObsolete()
				except Exception as err:
					logger.error(err)
				try:
					self.cleanup_temp_dir()
				except Exception as err:
					logger.error(err)
			else:
				state.set("installation_pending", "true")

				logger.notice("Start processing action requests")
				if productIds:
					if self.event.eventConfig.useCachedProducts:
						if self.opsiclientd.getCacheService().productCacheCompleted(self._configService, productIds):
							logger.notice("Event '%s' uses cached products and product caching is done", self.event.eventConfig.getId())
						else:
							raise RuntimeError(
								f"Event '{self.event.eventConfig.getId()}' uses cached products but product caching is not done"
							)

				additionalParams = ""
				if includeProductIds or excludeProductIds:
					if RUNNING_ON_LINUX or RUNNING_ON_DARWIN:
						additionalParams = "-processproducts " + ",".join(productIds)
					elif RUNNING_ON_WINDOWS:
						additionalParams = "/processproducts " + ",".join(productIds)
					else:
						logger.error("Unknown operating system - skipping processproducts parameter for action processor call")

				if productInfo:
					for product in self._configService.product_getObjects(
						attributes=["id", "name", "productVersion", "packageVersion"], id=productIds
					):
						for p_info in productInfo:
							if p_info.id == product.id:
								if p_info.productVersion == product.productVersion and p_info.packageVersion == product.packageVersion:
									p_info.name = product.name
								break

				self.processActionWarningTime(productInfo)
				try:
					try:
						cache_service = self.opsiclientd.getCacheService()
					except RuntimeError:
						cache_service = None
					if cache_service and not self.event.eventConfig.useCachedConfig:
						# Event like on_demand that does not use cached config - changes are not reflected in cache
						logger.info("Performing event that did not use cached config, setting config cache obsolete to suggest update")
						cache_service.setConfigCacheObsolete()
				except Exception as err:
					logger.error(err)

				self.runActions(productInfo, additionalParams=additionalParams)
				try:
					try:
						cache_service = self.opsiclientd.getCacheService()
					except RuntimeError:
						cache_service = None
					if (
						cache_service
						and self.event.eventConfig.useCachedConfig
						and not self._configService.productOnClient_getIdents(
							productType="LocalbootProduct",
							clientId=config.get("global", "host_id"),
							actionRequest=["setup", "uninstall", "update", "always", "once", "custom"],
						)
					):  # TODO: what about always scripts?
						# After having performed all cached actions, request new sync
						logger.info("No more actions to perform, setting config cache obsolete")
						cache_service.setConfigCacheObsolete()

					pocs_with_action = self._configService.productOnClient_getIdents(
						returnType="dict",
						productType="LocalbootProduct",
						clientId=config.get("global", "host_id"),
						actionRequest=["setup", "uninstall", "update", "once", "custom"],
					)
					logger.info("pocs_with_action: %r, productIds: %r", pocs_with_action, productIds)
					if not any(poc for poc in pocs_with_action if not productIds or poc["productId"] in productIds):
						# No more product actions pending of the actions requested
						logger.info("Setting installation pending to false")
						state.set("installation_pending", "false")
					logger.notice("Installation pending is: %s", state.get("installation_pending"))
				except Exception as err:
					logger.error(err)
		except Exception as err:
			logger.error("Failed to process product action requests: %s", err, exc_info=True)
			self.setStatusMessage(_("Failed to process product action requests: %s") % str(err))
			timeline.addEvent(
				title="Failed to process product action requests",
				description=f"Failed to process product action requests ({self.name}): {err}",
				category="error",
				isError=True,
			)
		time.sleep(3)

	def runActions(self, productInfo: list[ProductInfo], additionalParams: str = "") -> None:
		productIds = [p.id for p in productInfo]
		description = f"Running actions {', '.join(productIds)}"
		if productInfo:
			prod_desc = [f"{p.id} {p.productVersion}-{p.packageVersion}" for p in productInfo]
			description = f"Running actions {', '.join(prod_desc)}"
		runActionsEventId = timeline.addEvent(title="Running actions", description=description, category="run_actions", durationEvent=True)

		try:
			assert self.opsiclientd
			config.selectDepotserver(configService=self._configService, mode="mount", event=self.event, productIds=productIds)
			if not additionalParams:
				additionalParams = ""
			if not self.event.getActionProcessorCommand():
				raise RuntimeError("No action processor command defined")

			if (
				sys.platform == "win32"
				and self.event.eventConfig.name == "gui_startup"
				and self.event.eventConfig.trustedInstallerDetection
			):
				# Wait for windows installer before Running Action Processor
				try:
					logger.notice("Getting windows installer status")
					self.setStatusMessage(_("Waiting for TrustedInstaller"))
					if self.opsiclientd.isWindowsInstallerBusy():
						logger.notice("Windows installer is running, waiting until upgrade process is finished")
						waitEventId = timeline.addEvent(
							title="Waiting for TrustedInstaller",
							description="Windows installer is running, waiting until upgrade process is finished",
							category="wait",
							durationEvent=True,
						)

						while self.opsiclientd.isWindowsInstallerBusy():
							time.sleep(10)
							logger.debug("Windows installer is running, waiting until upgrade process is finished")

						# We will use this information as soon as we know whether it is reliable
						try:
							is_windows_reboot_pending = self.opsiclientd.isWindowsRebootPending()
							logger.info("Windows reboot pending: %s", is_windows_reboot_pending)
						except Exception as err:
							logger.error("Failed to get windows reboot pending status: %s", err, exc_info=True)

						wait_time = float(config.get("global", "post_trusted_installer_delay"))
						logger.info("Windows installer finished, waiting %r s for potential reboot", wait_time)
						time.sleep(wait_time)
						logger.notice("Windows installer finished")
						timeline.setEventEnd(eventId=waitEventId)
					else:
						logger.notice("Windows installer not running")
				except Exception as err:
					logger.error("Failed to get windows installer status: %s", err, exc_info=True)

			self.setStatusMessage(_("Starting actions"))

			if RUNNING_ON_WINDOWS:
				# Setting some registry values before starting action
				# Mainly for action processor
				System.setRegistryValue(
					System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depoturl", config.get("depot_server", "url")
				)
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depotdrive", config.getDepotDrive())
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configurl", "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configdrive", "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsurl", "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsdrive", "<deprecated>")

			# action processor desktop can be one of current / winlogon / default
			desktop = self.event.eventConfig.actionProcessorDesktop

			# Choose desktop for action processor
			if not desktop or (forceUnicodeLower(desktop) == "current"):
				if self.isLoginEvent:
					desktop = "default"
				else:
					desktop = forceUnicodeLower(self.opsiclientd.getCurrentActiveDesktopName(self.getSessionId()))
					if desktop and desktop.lower() == "screen-saver":
						desktop = "default"

			if not desktop:
				# Default desktop is winlogon
				desktop = "winlogon"

			depotServerUsername = ""
			depotServerPassword = ""
			try:
				(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService=self._configService)
			except Exception:
				if not self.event.eventConfig.useCachedProducts:
					raise
				logger.error("Failed to get depotserver credentials, continuing because event uses cached products", exc_info=True)
				depotServerUsername = "pcpatch"

			if not RUNNING_ON_WINDOWS:
				self.mountDepotShare()

			# Update action processor
			if self.event.eventConfig.updateActionProcessor:
				if RUNNING_ON_WINDOWS:
					self.mountDepotShare()
				self.updateActionProcessor()
				if RUNNING_ON_WINDOWS:
					self.umountDepotShare()

			# Run action processor
			serviceSession = "none"
			try:
				serviceSession = self.getConfigService().jsonrpc_getSessionId()
				if not serviceSession:
					serviceSession = "none"
			except Exception:
				pass

			actionProcessorUserName = ""
			actionProcessorUserPassword = ""
			if not self.isLoginEvent:
				actionProcessorUserName = self.opsiclientd._actionProcessorUserName
				actionProcessorUserPassword = self.opsiclientd._actionProcessorUserPassword

			createEnvironment = config.get("action_processor", "create_environment")

			actionProcessorCommand = config.replace(self.event.getActionProcessorCommand())
			actionProcessorCommand = actionProcessorCommand.replace("%service_url%", self._configServiceUrl or "?")
			actionProcessorCommand = actionProcessorCommand.replace("%service_session%", serviceSession)
			actionProcessorCommand = actionProcessorCommand.replace("%depot_path%", config.get_depot_path())
			actionProcessorCommand = actionProcessorCommand.replace(
				"%action_processor_productids%", ",".join(self.event.eventConfig.actionProcessorProductIds)
			)
			actionProcessorCommand += f" {additionalParams}"
			actionProcessorCommand = actionProcessorCommand.replace('"', '\\"')

			if RUNNING_ON_WINDOWS:
				command = (
					f'"{os.path.join(os.path.dirname(sys.argv[0]), "action_processor_starter.exe")}"'
					r' "%global.host_id%" "%global.opsi_host_key%" "%control_server.port%"'
					r' "%global.log_file%" "%global.log_level%" "%depot_server.url%"'
					f' "{config.getDepotDrive()}" "{depotServerUsername}" "{depotServerPassword}"'
					f' "{self.getSessionId()}" "{desktop}" '
					f' "{actionProcessorCommand}" "{self.event.eventConfig.actionProcessorTimeout}"'
					f' "{actionProcessorUserName}" "{actionProcessorUserPassword}"'
					f' "{str(createEnvironment).lower()}"'
				)
			else:
				command = actionProcessorCommand

			command = config.replace(command)

			if self.event.eventConfig.preActionProcessorCommand:
				logger.notice(
					"Starting pre action processor command '%s' in session '%s' on desktop '%s'",
					self.event.eventConfig.preActionProcessorCommand,
					self.getSessionId(),
					desktop,
				)
				self.runCommandInSession(
					command=self.event.eventConfig.preActionProcessorCommand, desktop=desktop, waitForProcessEnding=True
				)

			if RUNNING_ON_WINDOWS:
				logger.notice("Starting action processor in session '%s' on desktop '%s'", self.getSessionId(), desktop)
				self.runCommandInSession(command=command, desktop=desktop, waitForProcessEnding=True, noWindow=True)
			else:
				(username, password) = (None, None)
				new_cmd = []
				cmd = command.split()
				skip_next = False
				for num, part in enumerate(cmd):
					if skip_next:
						skip_next = False
						continue
					if part.strip().lower() == "-username" and len(cmd) > num:
						username = cmd[num + 1].strip()
						skip_next = True
					elif part.strip().lower() == "-password" and len(cmd) > num:
						password = cmd[num + 1].strip()
						skip_next = True
					else:
						new_cmd.append(part)

				if cmd and cmd[0] and os.path.isfile(cmd[0]) and not os.access(cmd[0], os.X_OK):
					os.chmod(cmd[0], 0o0755)

				with tempfile.TemporaryDirectory() as tmpdir:
					logger.debug("Working in temp dir '%s'", tmpdir)
					if username is not None and password is not None:
						credentialfile = os.path.join(tmpdir, "credentials")
						with open(credentialfile, mode="w", encoding="utf-8") as cfile:
							cfile.write(f"username={username}\npassword={password}\n")
						new_cmd.extend(["-credentialfile", credentialfile])
						command = " ".join(new_cmd)

					self.setStatusMessage(_("Action processor is running"))

					with cd(tmpdir):
						runCommandInSession(
							command=command,
							sessionId=self.getSessionId(),
							waitForProcessEnding=True,
							timeoutSeconds=self.event.eventConfig.actionProcessorTimeout,
						)

			if self.event.eventConfig.postActionProcessorCommand:
				logger.notice(
					"Starting post action processor command '%s' in session '%s' on desktop '%s'",
					self.event.eventConfig.postActionProcessorCommand,
					self.getSessionId(),
					desktop,
				)
				self.runCommandInSession(
					command=self.event.eventConfig.postActionProcessorCommand, desktop=desktop, waitForProcessEnding=True
				)

			self.setStatusMessage(_("Actions completed"))
		finally:
			timeline.setEventEnd(eventId=runActionsEventId)
			self.umountDepotShare()

	def setEnvironment(self) -> None:
		try:
			logger.debug("Current environment:")
			for key, value in os.environ.items():
				logger.debug("   %s=%s", key, value)
			logger.debug("Updating environment")
			hostname = os.environ["COMPUTERNAME"]
			(homeDrive, homeDir) = os.environ["USERPROFILE"].split("\\")[0:2]
			# TODO: is this correct?
			username = config.get("global", "username")
			# TODO: Anwendungsdaten
			os.environ["APPDATA"] = f"{homeDrive}\\{homeDir}\\{username}\\AppData\\Roaming"
			os.environ["HOMEDRIVE"] = homeDrive
			os.environ["HOMEPATH"] = f"\\{homeDir}\\{username}"
			os.environ["LOGONSERVER"] = f"\\\\{hostname}"
			os.environ["SESSIONNAME"] = "Console"
			os.environ["USERDOMAIN"] = hostname
			os.environ["USERNAME"] = username
			os.environ["USERPROFILE"] = f"{homeDrive}\\{homeDir}\\{username}"
			logger.debug("Updated environment:")
			for key, value in os.environ.items():
				logger.debug("   %s=%s", key, value)
		except Exception as err:
			logger.error("Failed to set environment: %s", err)

	def abortActionCallback(self, choiceSubject: ChoiceSubject) -> None:
		logger.notice("Event aborted by user")
		self.actionCancelled = True

	def startActionCallback(self, choiceSubject: ChoiceSubject) -> None:
		logger.notice("Event wait canceled by user")
		self.waitCancelled = True

	def processActionWarningTime(self, productInfo: list[ProductInfo]) -> None:
		if not self.event.eventConfig.actionWarningTime:
			return
		assert self._notificationServer

		product_ids = [p.id for p in productInfo]
		product_list = ", ".join(product_ids)
		if config.get("opsiclientd_notifier", "product_info") == "name":
			product_list = ", ".join(p.name for p in productInfo)

		logger.info("Notifying user of actions to process %s (%s)", self.event, product_ids)
		cancelCounter = state.get(f"action_processing_cancel_counter_{self.event.eventConfig.name}", 0)
		# State action_processing_cancel_counter without appended event name is needed for notification server
		state.set("action_processing_cancel_counter", cancelCounter)

		waitEventId = timeline.addEvent(
			title="Action warning",
			description=(
				f"Notifying user of actions to process {self.event.eventConfig.getId()} ({', '.join(product_ids)})\n"
				f"actionWarningTime: {self.event.eventConfig.actionWarningTime}, "
				f"actionUserCancelable: {self.event.eventConfig.actionUserCancelable}, "
				f"cancelCounter: {cancelCounter}"
			),
			category="wait",
			durationEvent=True,
		)
		self._messageSubject.setMessage(f'{self.event.eventConfig.getActionMessage()}\n{_("Products")}: {product_list}')
		choiceSubject = ChoiceSubject(id="choice")
		if cancelCounter < self.event.eventConfig.actionUserCancelable:
			choiceSubject.setChoices([_("Abort"), _("Start now")])
			choiceSubject.setCallbacks([self.abortActionCallback, self.startActionCallback])
		else:
			choiceSubject.setChoices([_("Start now")])
			choiceSubject.setCallbacks([self.startActionCallback])
		self._notificationServer.addSubject(choiceSubject)
		notifierPids: list[int] = []
		notifierHandles: list[Popen | int] = []
		try:
			if self.event.eventConfig.actionNotifierCommand:
				desktops = [self.event.eventConfig.actionNotifierDesktop]
				if RUNNING_ON_WINDOWS and self.event.eventConfig.actionNotifierDesktop == "all":
					desktops = ["winlogon", "default"]
				for desktop in desktops:
					notifier_process, notifier_pid = self.startNotifierApplication(
						command=self.event.eventConfig.actionNotifierCommand, notifierId="action", desktop=desktop
					)
					if notifier_process and notifier_pid:
						notifierPids.append(notifier_pid)
						notifierHandles.append(notifier_process)

			timeout = int(self.event.eventConfig.actionWarningTime)
			endTime = time.time() + timeout
			while timeout > 0 and not self.actionCancelled and not self.waitCancelled:
				now = time.time()
				minutes = 0
				seconds = endTime - now
				if seconds >= 60:
					minutes = int(seconds / 60)
					seconds -= minutes * 60
				seconds = int(seconds)
				seconds = max(seconds, 0)
				minutes = max(minutes, 0)
				self.setStatusMessage(
					_("Event %s: action processing will start in %s:%s")
					% (self.event.eventConfig.getName(), f"{minutes:02d}", f"{seconds:02d}")
				)
				if endTime - now <= 0:
					break
				self._cancelable_sleep(1)

			if self.waitCancelled:
				timeline.addEvent(
					title="Action processing started by user",
					description="Action processing wait time canceled by user",
					category="user_interaction",
				)

			if self.actionCancelled:
				cancelCounter += 1
				state.set(f"action_processing_cancel_counter_{self.event.eventConfig.name}", cancelCounter)
				logger.notice(
					"Action processing canceled by user for the %d. time (max: %d)",
					cancelCounter,
					self.event.eventConfig.actionUserCancelable,
				)
				timeline.addEvent(
					title="Action processing canceled by user",
					description=(
						f"Action processing canceled by user for the {cancelCounter}. time"
						f" (max: {self.event.eventConfig.actionUserCancelable})"
					),
					category="user_interaction",
				)
				raise CanceledByUserError("Action processing canceled by user")
			state.set(f"action_processing_cancel_counter_{self.event.eventConfig.name}", 0)
		finally:
			timeline.setEventEnd(waitEventId)
			try:
				if self._notificationServer:
					self._notificationServer.requestEndConnections()
					self._notificationServer.removeSubject(choiceSubject)
				if notifierPids:
					try:
						time.sleep(3)
						for notifierHandle, notifierPid in zip(notifierHandles, notifierPids):
							if hasattr(notifierHandle, "poll"):
								notifierHandle.poll()
							System.terminateProcess(processId=notifierPid)
					except Exception:
						pass

			except Exception as err:
				logger.error(err, exc_info=True)

	def abortShutdownCallback(self, choiceSubject: ChoiceSubject) -> None:
		logger.notice("Shutdown aborted by user")
		self._shutdownWarningRepetitionTime = self.event.eventConfig.shutdownWarningRepetitionTime
		self._shutdownWarningTime = self.event.eventConfig.shutdownWarningTime
		selected = choiceSubject.getChoices()[choiceSubject.getSelectedIndexes()[0]]
		match = re.search(r"(\d+):00", selected)
		if match:
			self._shutdownWarningTime = self.event.eventConfig.shutdownWarningTimeAfterTimeSelect
			hour = int(match.group(1))
			now = datetime.datetime.now()
			shutdown_time = datetime.datetime.now()
			if now.hour > hour:
				shutdown_time += datetime.timedelta(days=1)
			shutdown_time = shutdown_time.replace(hour=hour, minute=0, second=0)
			self._shutdownWarningRepetitionTime = int((shutdown_time - now).total_seconds())
		logger.notice(
			"User selected '%s', shutdownWarningRepetitionTime=%s, shutdownWarningTime=%s",
			selected,
			self._shutdownWarningRepetitionTime,
			self._shutdownWarningTime,
		)
		self.shutdownCancelled = True

	def startShutdownCallback(self, choiceSubject: ChoiceSubject) -> None:
		logger.notice("Shutdown wait canceled by user")
		self.shutdownWaitCancelled = True

	def isRebootRequested(self) -> bool:
		if self.event.eventConfig.reboot:
			return True
		if self.event.eventConfig.processShutdownRequests and self.opsiclientd and self.opsiclientd.isRebootRequested():
			return True
		return False

	def isShutdownRequested(self) -> bool:
		if self.event.eventConfig.shutdown:
			return True
		if self.event.eventConfig.processShutdownRequests and self.opsiclientd and self.opsiclientd.isShutdownRequested():
			return True
		return False

	def processShutdownRequests(self) -> None:
		try:
			assert self.opsiclientd
			shutdown = self.isShutdownRequested()
			reboot = self.isRebootRequested()
			if reboot or shutdown:
				if reboot:
					timeline.addEvent(title="Reboot requested", category="system")
					self.setStatusMessage(_("Reboot requested"))
				else:
					timeline.addEvent(title="Shutdown requested", category="system")
					self.setStatusMessage(_("Shutdown requested"))

				if self._shutdownWarningTime:
					if not self.event.eventConfig.shutdownNotifierCommand:
						raise ConfigurationError(
							f"Event {self.event.eventConfig.getName()} defines shutdownWarningTime but shutdownNotifierCommand is not set"
						)
					assert self._notificationServer
					self._notificationServer.requestEndConnections()
					while True:
						shutdownCancelCounter = state.get("shutdown_cancel_counter", 0)
						waitEventId = None
						if reboot:
							logger.info("Notifying user of reboot")
							waitEventId = timeline.addEvent(
								title="Reboot warning",
								description=(
									"Notifying user of reboot\n"
									f"shutdownWarningTime: {self.event.eventConfig.shutdownWarningTime}, "
									f"shutdownWarningTimeAfterTimeSelect: {self.event.eventConfig.shutdownWarningTimeAfterTimeSelect}, "
									f"shutdownUserSelectableTime: {self.event.eventConfig.shutdownUserSelectableTime}, "
									f"shutdownLatestSelectableHour: {self.event.eventConfig.shutdownLatestSelectableHour}, "
									f"shutdownUserCancelable: {self.event.eventConfig.shutdownUserCancelable}, "
									f"shutdownCancelCounter: {shutdownCancelCounter}"
								),
								category="wait",
								durationEvent=True,
							)
						else:
							logger.info("Notifying user of shutdown")
							waitEventId = timeline.addEvent(
								title="Shutdown warning",
								description=(
									"Notifying user of shutdown\n"
									f"shutdownWarningTime: {self.event.eventConfig.shutdownWarningTime}, "
									f"shutdownWarningTimeAfterTimeSelect: {self.event.eventConfig.shutdownWarningTimeAfterTimeSelect}, "
									f"shutdownUserSelectableTime: {self.event.eventConfig.shutdownUserSelectableTime}, "
									f"shutdownLatestSelectableHour: {self.event.eventConfig.shutdownLatestSelectableHour}, "
									f"shutdownUserCancelable: {self.event.eventConfig.shutdownUserCancelable}, "
									f"shutdownCancelCounter: {shutdownCancelCounter}"
								),
								category="wait",
								durationEvent=True,
							)

						self.shutdownCancelled = False
						self.shutdownWaitCancelled = False

						shutdownWarningMessage = self.event.eventConfig.getShutdownWarningMessage()
						if isinstance(self.event, SyncCompletedEvent):
							try:
								productIds = list(self.opsiclientd.getCacheService().getProductCacheState()["products"])
								if productIds:
									shutdownWarningMessage += f"\n{_('Products')}: {', '.join(productIds)}"
							except Exception as stateErr:
								logger.error(stateErr, exc_info=True)
						self._messageSubject.setMessage(shutdownWarningMessage)

						choiceSubject = ChoiceSubject(id="choice")

						def set_choices_and_callbacks(choice_subject: ChoiceSubject) -> None:
							choices = []
							if reboot:
								choices.append(_("Reboot now"))
							else:
								choices.append(_("Shutdown now"))
							callbacks = [self.startShutdownCallback]

							logger.info(
								"Shutdown cancel counter: %s/%s", shutdownCancelCounter, self.event.eventConfig.shutdownUserCancelable
							)
							if shutdownCancelCounter < self.event.eventConfig.shutdownUserCancelable:
								if self.event.eventConfig.shutdownUserSelectableTime:
									hour = time.localtime().tm_hour
									while len(choices) < 24:
										hour += 1
										if hour == 24:
											hour = 0
										if reboot:
											choices.append(_("Reboot at %s") % f" {hour:02d}:00")
										else:
											choices.append(_("Shutdown at %s") % f" {hour:02d}:00")
										callbacks.append(self.abortShutdownCallback)
										if hour == self.event.eventConfig.shutdownLatestSelectableHour:
											break
								else:
									if reboot:
										choices.append(_("Reboot later"))
									else:
										choices.append(_("Shutdown later"))
									callbacks.append(self.abortShutdownCallback)

							choice_subject.setChoices(choices)
							choice_subject.setCallbacks(callbacks)

						set_choices_and_callbacks(choiceSubject)
						self._notificationServer.addSubject(choiceSubject)

						failed_to_start_notifier = False
						notifierPids: list[int] = []
						notifierHandles: list[Popen | int] = []
						desktops = [self.event.eventConfig.shutdownNotifierDesktop]

						if RUNNING_ON_WINDOWS and self.event.eventConfig.shutdownNotifierDesktop == "all":
							desktops = ["winlogon", "default"]

						notifierId: Literal["shutdown", "shutdown_select"] = "shutdown"
						shutdownNotifierCommand = self.event.eventConfig.shutdownNotifierCommand
						if self.event.eventConfig.shutdownUserSelectableTime and len(choiceSubject.getChoices()) > 1:
							notifierId = "shutdown_select"
							shutdownNotifierCommand = shutdownNotifierCommand.replace("shutdown.ini", "shutdown_select.ini")

						for desktop in desktops:
							notifier_handle, notifier_pid = self.startNotifierApplication(
								command=shutdownNotifierCommand, notifierId=notifierId, desktop=desktop
							)
							if notifier_handle and notifier_pid:
								notifierPids.append(notifier_pid)
								notifierHandles.append(notifier_handle)
							else:
								logger.error("Failed to start shutdown notifier, shutdown will not be executed")
								failed_to_start_notifier = True

						current_hour = time.localtime().tm_hour
						timeout = int(self._shutdownWarningTime)
						endTime = time.time() + timeout
						while (timeout > 0) and not self.shutdownCancelled and not self.shutdownWaitCancelled and not self._should_cancel:
							if current_hour != time.localtime().tm_hour:
								# Remove choices which are in the past
								set_choices_and_callbacks(choiceSubject)
								current_hour = time.localtime().tm_hour
							now = time.time()
							minutes = 0
							seconds = endTime - now
							if seconds >= 60:
								minutes = int(seconds / 60)
								seconds -= minutes * 60
							seconds = int(seconds)
							seconds = max(seconds, 0)
							minutes = max(minutes, 0)
							if reboot:
								self.setStatusMessage(_("Reboot in %s:%s") % (f"{minutes:02d}", f"{seconds:02d}"))
							else:
								self.setStatusMessage(_("Shutdown in %s:%s") % (f"{minutes:02d}", f"{seconds:02d}"))
							if endTime - now <= 0:
								break
							self._cancelable_sleep(1)

						try:
							if self._notificationServer:
								self._notificationServer.requestEndConnections()
								self._notificationServer.removeSubject(choiceSubject)
							if notifierPids:
								try:
									time.sleep(3)
									for notifierHandle, notifierPid in zip(notifierHandles, notifierPids):
										if hasattr(notifierHandle, "poll"):
											notifierHandle.poll()
										System.terminateProcess(processId=notifierPid)
								except Exception:
									pass
						except Exception as err:
							logger.error(err, exc_info=True)

						self._messageSubject.setMessage("")

						timeline.setEventEnd(waitEventId)

						if self.shutdownWaitCancelled:
							if reboot:
								timeline.addEvent(
									title="Reboot started by user",
									description="Reboot wait time canceled by user",
									category="user_interaction",
								)
							else:
								timeline.addEvent(
									title="Shutdown started by user",
									description="Shutdown wait time canceled by user",
									category="user_interaction",
								)

						if self.should_cancel():
							raise EventProcessingCanceled()

						if self.shutdownCancelled or failed_to_start_notifier or self._should_cancel:
							self.opsiclientd.setBlockLogin(False)
							shutdown_type = "Reboot" if reboot else "Shutdown"

							if failed_to_start_notifier:
								message = f"{shutdown_type} canceled because user could not be notified."
								logger.warning(message)
								timeline.addEvent(title=f"{shutdown_type} canceled (notifier error)", description=message, category="error")
							else:
								shutdownCancelCounter += 1
								state.set("shutdown_cancel_counter", shutdownCancelCounter)
								message = (
									f"{shutdown_type} canceled by user for the {shutdownCancelCounter}. time"
									f" (max: {self.event.eventConfig.shutdownUserCancelable})."
								)
								if self._shutdownWarningRepetitionTime >= 0:
									rep_at = datetime.datetime.now() + datetime.timedelta(seconds=self._shutdownWarningRepetitionTime)
									message += (
										f" Shutdown warning will be repeated in {self._shutdownWarningRepetitionTime:.0f}"
										f" seconds at {rep_at.strftime('%H:%M:%S')}"
									)
								logger.notice(message)

								timeline.addEvent(
									title=f"{shutdown_type} canceled by user", description=message, category="user_interaction"
								)

							if self._shutdownWarningRepetitionTime >= 0:
								rep_at = datetime.datetime.now() + datetime.timedelta(seconds=self._shutdownWarningRepetitionTime)
								logger.info(
									"Shutdown warning will be repeated in %d seconds at %s",
									self._shutdownWarningRepetitionTime,
									rep_at.strftime("%H:%M:%S"),
								)
								exact_time_passed = self._cancelable_sleep(self._shutdownWarningRepetitionTime)
								if not exact_time_passed:
									# Time jump possibly caused by standby
									# Use shutdownWarningTime, not shutdownWarningTimeAfterTimeSelect
									logger.notice(
										"Time jump possibly caused by standby, using shutdownWarningTime, not shutdownWarningTimeAfterTimeSelect"
									)
									self._shutdownWarningTime = self.event.eventConfig.shutdownWarningTime
								continue
						break
				if reboot:
					timeline.addEvent(title="Rebooting", category="system")
					self.opsiclientd.rebootMachine()
				elif shutdown:
					timeline.addEvent(title="Shutting down", category="system")
					self.opsiclientd.shutdownMachine()
		except EventProcessingCanceled:
			raise
		except Exception as err:
			logger.error(err, exc_info=True)

	def inWorkingWindow(self) -> bool:
		start_str, end_str, now = (None, None, None)
		try:
			# Working window is specified like: 07:00-22:00
			start_str, end_str = self.event.eventConfig.workingWindow.split("-")
			start = datetime.time(int(start_str.split(":")[0]), int(start_str.split(":")[1]))
			end = datetime.time(int(end_str.split(":")[0]), int(end_str.split(":")[1]))
			now = datetime.datetime.now().time()

			logger.debug("Working window configuration: start=%s, end=%s, now=%s", start, end, now)

			in_window = False
			if start <= end:
				in_window = start <= now <= end
			else:
				# Crosses midnight
				in_window = now >= start or now <= end

			if in_window:
				logger.info("Current time %s is within the configured working window (%s-%s)", now, start, end)
				return True

			logger.info("Current time %s is outside the configured working window (%s-%s)", now, start, end)
			return False

		except Exception as err:
			logger.error("Working window processing failed (start=%s, end=%s, now=%s): %s", start_str, end_str, now, err, exc_info=True)
			return True

	def cache_products(self, wait_for_ending: bool = False) -> None:
		assert self.opsiclientd
		if self.opsiclientd.getCacheService().isProductCacheServiceWorking():
			logger.info("Already caching products")
			return

		self.setStatusMessage(_("Caching products"))
		try:
			self._currentProgressSubjectProxy.attachObserver(self._detailSubjectProxy)
			self.opsiclientd.getCacheService().cacheProducts(
				waitForEnding=wait_for_ending,
				productProgressObserver=self._currentProgressSubjectProxy,
				overallProgressObserver=self._overallProgressSubjectProxy,
				dynamicBandwidth=self.event.eventConfig.cacheDynamicBandwidth,
				maxBandwidth=self.event.eventConfig.cacheMaxBandwidth,
			)
			if wait_for_ending:
				self.setStatusMessage(_("Products cached"))
		finally:
			self._detailSubjectProxy.setMessage("")
			try:
				self._currentProgressSubjectProxy.detachObserver(self._detailSubjectProxy)
				self._currentProgressSubjectProxy.reset()
				self._overallProgressSubjectProxy.reset()
			except Exception as err:
				logger.error(err, exc_info=True)

	def sync_config(self, wait_for_ending: bool = False) -> None:
		assert self.opsiclientd
		if self.opsiclientd.getCacheService().isConfigCacheServiceWorking():
			logger.info("Already syncing config")
			return

		if self.event.eventConfig.syncConfigToServer:
			self.setStatusMessage(_("Syncing config to server"))
			self.opsiclientd.getCacheService().syncConfigToServer(waitForEnding=True)
			self.setStatusMessage(_("Sync completed"))

		if self.event.eventConfig.syncConfigFromServer:
			self.setStatusMessage(_("Syncing config from server"))
			self.opsiclientd.getCacheService().syncConfigFromServer(waitForEnding=wait_for_ending)
			if wait_for_ending:
				self.setStatusMessage(_("Sync completed"))

	def cleanup_temp_dir(self) -> None:
		tmp_dir = config.get("global", "tmp_dir")
		if not RUNNING_ON_WINDOWS or not config.get("global", "tmp_dir_cleanup") or not tmp_dir:
			return
		logger.notice("Cleaning up temp dir %r", tmp_dir)

		for path in Path(tmp_dir).iterdir():
			if path.is_dir():
				shutil.rmtree(path)
			else:
				path.unlink()

	def run(self) -> None:
		with log_context({"instance": f"event processing {self.event.eventConfig.getId()}"}):
			assert self.opsiclientd
			timelineEventId = None
			notifierPids: list[int] = []
			notifierHandles: list[Popen | int] = []

			try:
				if self.event.eventConfig.workingWindow:
					if not self.inWorkingWindow():
						logger.notice("We are not in the configured working window, stopping Event")
						return
				logger.notice(
					"============= EventProcessingThread for occurrcence of event '%s' started =============",
					self.event.eventConfig.getId(),
				)
				timelineEventId = timeline.addEvent(
					title=f"Processing event {self.event.eventConfig.getName()}",
					description=f"EventProcessingThread for occurrcence of event '{self.event.eventConfig.getId()}' ({self.name}) started",
					category="event_processing",
					durationEvent=True,
				)
				self.running = True
				self.actionCancelled = False
				self.waitCancelled = False
				self._set_cancelable(True)
				self.opsiclientd.setBlockLogin(self.event.eventConfig.blockLogin)

				try:
					config.set_temporary_depot_path(None)
					config.setTemporaryDepotDrive(None)
					config.setTemporaryConfigServiceUrls([])

					self.startNotificationServer()
					try:
						self.setActionProcessorInfo()
					except Exception as err:
						logger.error("Failed to set action processor info: %s", err)
					self._messageSubject.setMessage(self.event.eventConfig.getActionMessage())

					self.setStatusMessage(_("Processing event %s") % self.event.eventConfig.getName())

					if self.event.eventConfig.logoffCurrentUser:
						System.logoffCurrentUser()
						time.sleep(15)
					elif self.event.eventConfig.lockWorkstation:
						System.lockWorkstation()
						time.sleep(15)

					if self.should_cancel():
						raise EventProcessingCanceled()

					if self.event.eventConfig.eventNotifierCommand:
						notifierId: Literal["userlogin", "event"] = "userlogin" if self.event.eventConfig.actionType == "login" else "event"
						desktops = [self.event.eventConfig.eventNotifierDesktop]
						if RUNNING_ON_WINDOWS and self.event.eventConfig.eventNotifierDesktop == "all":
							desktops = ["winlogon", "default"]
						for desktop in desktops:
							notifier_handle, notifier_pid = self.startNotifierApplication(
								command=self.event.eventConfig.eventNotifierCommand, notifierId=notifierId, desktop=desktop
							)
							if notifier_handle and notifier_pid:
								notifierPids.append(notifier_pid)
								notifierHandles.append(notifier_handle)

					if self.event.eventConfig.useCachedConfig:
						if self.opsiclientd.getCacheService().configCacheCompleted():
							logger.notice("Event '%s' uses cached config and config caching is done", self.event.eventConfig.getId())
							config.setTemporaryConfigServiceUrls(["https://127.0.0.1:4441/rpc"])
						else:
							raise RuntimeError(
								f"Event '{self.event.eventConfig.getId()}' uses cached config but config caching is not done"
							)

					if self.event.eventConfig.getConfigFromService or self.event.eventConfig.processActions:
						if not self.isConfigServiceConnected():
							self.connectConfigService()

						if self.event.eventConfig.getConfigFromService:
							config.readConfigFile()
							self.getConfigFromService()
							if self.event.eventConfig.updateConfigFile:
								config.updateConfigFile()

						if self.event.eventConfig.processActions:
							if self.should_cancel():
								raise EventProcessingCanceled()
							self._set_cancelable(False)

							if self.event.eventConfig.actionType == "login":
								self.processUserLoginActions()
							else:
								self.processProductActionRequests()

					if self.should_cancel():
						raise EventProcessingCanceled()
					self._set_cancelable(False)

					shutdown_or_reboot = self.isShutdownRequested() or self.isRebootRequested()
					if self.event.eventConfig.syncConfigToServer or self.event.eventConfig.syncConfigFromServer:
						self.sync_config(wait_for_ending=shutdown_or_reboot)

					if self.event.eventConfig.cacheProducts:
						self.cache_products(wait_for_ending=shutdown_or_reboot)

				finally:
					self._messageSubject.setMessage("")
					if self.event.eventConfig.writeLogToService:
						try:
							self.writeLogToService()
						except Exception as err:
							logger.error(err, exc_info=True)

					try:
						self.disconnectConfigService()
					except Exception as err:
						logger.error(err, exc_info=True)

					config.setTemporaryConfigServiceUrls([])

					# if cancelled, skip further execution
					if not self.should_cancel():
						if self.event.eventConfig.postEventCommand:
							logger.notice("Running post event command '%s'", self.event.eventConfig.postEventCommand)
							encoding = "cp850" if RUNNING_ON_WINDOWS else "utf-8"
							try:
								output = subprocess.check_output(
									self.event.eventConfig.postEventCommand, shell=True, stderr=subprocess.STDOUT
								)
								logger.info(
									"Post event command '%s' output: %s",
									self.event.eventConfig.postEventCommand,
									output.decode(encoding, errors="replace"),
								)
							except subprocess.CalledProcessError as err:
								logger.error(
									"Post event command '%s' returned exit code %s: %s",
									self.event.eventConfig.postEventCommand,
									err.returncode,
									err.output.decode(encoding, errors="replace"),
								)

						# processActions is False for passive events like sync/sync_completed
						if self.event.eventConfig.processActions:
							self._set_cancelable(False)
						else:
							self._set_cancelable(True)
						self.processShutdownRequests()
						# Shutdown / reboot not cancelable if triggered by opsi script
						self._set_cancelable(False)

						if self.opsiclientd.isShutdownTriggered():
							self.setStatusMessage(_("Shutting down machine"))
						elif self.opsiclientd.isRebootTriggered():
							self.setStatusMessage(_("Rebooting machine"))
						else:
							self.setStatusMessage(_("Unblocking login"))

						if self.opsiclientd.isRebootTriggered() or self.opsiclientd.isShutdownTriggered():
							if os.path.exists(config.restart_marker):
								os.remove(config.restart_marker)
						else:
							self.opsiclientd.setBlockLogin(False)

			except EventProcessingCanceled:
				logger.notice("Processing of event %s canceled", self.event)
				timeline.addEvent(
					title=f"Processing of event {self.event.eventConfig.getName()} canceled",
					description=f"Processing of event {self.event} ({self.name}) canceled",
					category="event_processing",
					isError=True,
				)
			except Exception as err:
				logger.error("Failed to process event %s: %s", self.event, err, exc_info=True)
				timeline.addEvent(
					title=f"Failed to process event {self.event.eventConfig.getName()}",
					description=f"Failed to process event {self.event} ({self.name}): {err}",
					category="event_processing",
					isError=True,
				)

			self.setStatusMessage("")
			self.stopNotificationServer()
			if notifierPids:
				try:
					time.sleep(3)
					for notifierHandle, notifierPid in zip(notifierHandles, notifierPids):
						if psutil.pid_exists(notifierPid) and hasattr(notifierHandle, "poll"):
							notifierHandle.poll()
						time.sleep(0.1)
						if psutil.pid_exists(notifierPid):
							logger.trace("killing notifier with pid %s", notifierPid)
							System.terminateProcess(processId=notifierPid)
				except Exception as error:
					logger.error("Could not kill notifier: %s", error, exc_info=True)

			self.opsiclientd.setBlockLogin(False)
			self.running = False
			logger.notice("============= EventProcessingThread for event '%s' ended =============", self.event.eventConfig.getId())
			if timelineEventId:
				timeline.setEventEnd(eventId=timelineEventId)

			if os.path.exists(config.restart_marker):
				logger.notice("Restart marker found, restarting in 3 seconds")
				self.opsiclientd.restart(3)
