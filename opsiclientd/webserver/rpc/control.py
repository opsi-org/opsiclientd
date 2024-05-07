# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
webserver.rpc.control
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import MethodType
from typing import TYPE_CHECKING, Any, Generator
from uuid import uuid4

import psutil  # type: ignore[import]
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from OPSI import System  # type: ignore[import]
from OPSI import __version__ as python_opsi_version  # type: ignore[import]
from OPSI.Util.Log import truncateLogData  # type: ignore[import]
from opsicommon import __version__ as opsicommon_version
from opsicommon.logging import get_logger, secret_filter
from opsicommon.objects import ConfigState, ObjectToGroup, Product, ProductDependency, ProductOnClient, ProductOnDepot
from opsicommon.system.info import is_windows
from opsicommon.types import forceBool, forceInt, forceProductIdList, forceUnicode
from opsicommon.utils import generate_opsi_host_key

from opsiclientd import __version__
from opsiclientd.Config import OPSI_SETUP_USER_NAME
from opsiclientd.Events.SwOnDemand import SwOnDemandEventGenerator
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import getEventGenerator, getEventGenerators
from opsiclientd.Localization import _, get_translation_info
from opsiclientd.OpsiService import ServiceConnection, download_from_depot
from opsiclientd.Timeline import Timeline
from opsiclientd.webserver.rpc.interface import Interface

if is_windows():
	from opsiclientd.windows import runCommandInSession
else:
	from OPSI.System import runCommandInSession  # type: ignore

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd


logger = get_logger()


class PipeControlInterface(Interface):
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		super().__init__()
		self.opsiclientd = opsiclientd

	@contextmanager
	def _config_service_connection(self, disconnect: bool = True) -> Generator[ServiceConnection, None, None]:
		service_connection = ServiceConnection(self.opsiclientd)
		connected = service_connection.isConfigServiceConnected()
		if not connected:
			service_connection.connectConfigService()
		try:
			yield service_connection
		finally:
			if not connected and disconnect:
				service_connection.disconnectConfigService()

	def _fireEvent(self, name: str, can_cancel: bool = True, event_info: dict[str, str | list[str]] | None = None) -> None:
		# can_cancel: Allow event cancellation for new events called via the ControlServer
		can_cancel = forceBool(can_cancel)
		event_info = event_info or {}
		event_generator = getEventGenerator(name)
		logger.notice("rpc firing event %r, event_info=%r, can_cancel=%r", name, event_info, can_cancel)
		event_generator.createAndFireEvent(eventInfo=event_info, can_cancel=can_cancel)

	def _processActionRequests(self, product_ids: list[str] | None = None) -> None:
		event = self.opsiclientd.config.get("control_server", "process_actions_event")
		if not event or event == "auto":
			timer_active = False
			on_demand_active = False
			for event_config in getEventConfigs().values():
				if event_config["name"] == "timer" and event_config["active"]:
					timer_active = True
				elif event_config["name"] == "on_demand" and event_config["active"]:
					on_demand_active = True

			if timer_active:
				event = "timer"
			elif on_demand_active:
				event = "on_demand"
			else:
				raise RuntimeError("Neither timer nor on_demand event active")

		event_info: dict[str, str | list[str]] = {}
		if product_ids:
			event_info = {"product_ids": forceProductIdList(product_ids)}
		self._fireEvent(name=event, event_info=event_info)

	def getPossibleMethods_listOfHashes(self) -> list[dict[str, Any]]:
		return self._interface_list

	def backend_getInterface(self) -> list[dict[str, Any]]:
		return self._interface_list

	def backend_info(self) -> dict[str, Any]:
		return {}

	def exit(self) -> None:
		return

	def backend_exit(self) -> None:
		return

	def getBlockLogin(self) -> bool:
		return self.opsiclientd._blockLogin

	def isRebootRequested(self) -> bool:
		return self.isRebootTriggered()

	def isShutdownRequested(self) -> bool:
		return self.isShutdownTriggered()

	def isRebootTriggered(self) -> bool:
		return self.opsiclientd.isRebootTriggered()

	def isShutdownTriggered(self) -> bool:
		return self.opsiclientd.isShutdownTriggered()


class KioskControlInterface(PipeControlInterface):
	def getClientId(self) -> str:
		return self.opsiclientd.config.get("global", "host_id")

	def processActionRequests(self, product_ids: list[str] | None = None) -> None:
		return self._processActionRequests(product_ids=product_ids)

	def fireEvent_software_on_demand(self) -> None:
		for eventGenerator in getEventGenerators(generatorClass=SwOnDemandEventGenerator):
			# Allow event cancellation for new events called via the Kiosk
			eventGenerator.createAndFireEvent(can_cancel=True)

	def getConfigDataFromOpsiclientd(self, get_depot_id: bool = True, get_active_events: bool = True) -> dict[str, Any]:
		result: dict[str, Any] = {}
		result["opsiclientd_version"] = (
			f"Opsiclientd {__version__} [python-opsi={python_opsi_version}python-opsi-common={opsicommon_version}]"
		)

		if get_depot_id:
			result["depot_id"] = self.opsiclientd.config.get("depot_server", "master_depot_id")

		if get_active_events:
			active_events = []
			for event_config in getEventConfigs().values():
				if event_config["active"]:
					active_events.append(event_config["name"])

			result["active_events"] = list(set(active_events))
		return result

	def backend_setOptions(self, options: dict[str, Any]) -> None:
		with self._config_service_connection(disconnect=False) as service_connection:
			service_connection.getConfigService().backend_setOptions(options)

	def configState_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ConfigState]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().configState_getObjects(attributes, **filter)

	def getDepotId(self, clientId: str | None = None) -> str:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().getDepotId(self.opsiclientd.config.get("global", "host_id"))

	def configState_getClientToDepotserver(
		self,
		depotIds: list[str] | None = None,
		clientIds: list[str] | None = None,
		masterOnly: bool = True,
		productIds: list[str] | None = None,
	) -> list[dict[str, Any]]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().configState_getClientToDepotserver(depotIds, clientIds, masterOnly, productIds)

	def getGeneralConfigValue(self, key: str, objectId: str | None = None) -> str:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().getGeneralConfigValue(key, objectId)

	def getKioskProductInfosForClient(self, clientId: str, addConfigs: bool = False) -> dict | list:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().getKioskProductInfosForClient(clientId, addConfigs)

	def hostControlSafe_fireEvent(self, event: str, hostIds: list[str] | None = None) -> dict[str, Any]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().hostControlSafe_fireEvent(event, hostIds)

	def objectToGroup_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ObjectToGroup]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().objectToGroup_getObjects(attributes, **filter)

	def product_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Product]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().product_getObjects(attributes, **filter)

	def productDependency_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ProductDependency]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().productDependency_getObjects(attributes, **filter)

	def productOnClient_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ProductOnClient]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().productOnClient_getObjects(attributes, **filter)

	def productOnDepot_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ProductOnDepot]:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().productOnDepot_getObjects(attributes, **filter)

	def setProductActionRequestWithDependencies(self, productId: str, clientId: str, actionRequest: str) -> None:
		with self._config_service_connection(disconnect=False) as service_connection:
			return service_connection.getConfigService().setProductActionRequestWithDependencies(productId, clientId, actionRequest)


class ControlInterface(PipeControlInterface):
	_run_as_opsi_setup_user_lock = threading.Lock()

	def wait(self, seconds: int = 0) -> None:
		for _sec in range(int(seconds)):
			time.sleep(1)

	def noop(self, arg: str) -> None:
		pass

	def cacheService_syncConfig(self, waitForEnding: bool = False, force: bool = False) -> None:
		self.opsiclientd.getCacheService().syncConfig(waitForEnding, force)

	def cacheService_getConfigCacheState(self) -> dict[str, Any]:
		return self.opsiclientd.getCacheService().getConfigCacheState()

	def cacheService_getProductCacheState(self) -> dict[str, Any]:
		return self.opsiclientd.getCacheService().getProductCacheState()

	def cacheService_getConfigModifications(self) -> dict[str, Any]:
		return self.opsiclientd.getCacheService().getConfigModifications()

	def cacheService_deleteCache(self) -> str:
		cacheService = self.opsiclientd.getCacheService()
		cacheService.setConfigCacheObsolete()
		cacheService.clear_product_cache()
		return "config and product cache deleted"

	def timeline_getEvents(self) -> list[dict[str, Any]]:
		timeline = Timeline()
		return timeline.getEvents()

	def setBlockLogin(self, blockLogin: bool, handleNotifier: bool = True) -> str:
		self.opsiclientd.setBlockLogin(forceBool(blockLogin), forceBool(handleNotifier))
		logger.notice("rpc setBlockLogin: blockLogin set to '%s'", self.opsiclientd._blockLogin)
		if self.opsiclientd._blockLogin:
			return "Login blocker is on"
		return "Login blocker is off"

	def readLog(self, logType: str = "opsiclientd") -> str:
		logType = forceUnicode(logType)
		if logType != "opsiclientd":
			raise ValueError(f"Unknown log type '{logType}'")

		logger.notice("rpc readLog: reading log of type '%s'", logType)

		with open(self.opsiclientd.config.get("global", "log_file"), "r", encoding="utf-8", errors="replace") as log:
			return log.read()

	def log_read(self, logType: str = "opsiclientd", extension: str = "", maxSize: int = 5000000) -> str:
		"""
		Return the content of a log.

		:param logType: Type of log. \
		Currently supported: *opsiclientd*, *opsi-script*, *opsi_loginblocker*, \
		*opsiclientdguard*,	'notifier_block_login',	'notifier_event', 'opsi-client-agent'
		:type data: Unicode
		:param extension: count for history log. Possible Values 0-9
		:param maxSize: Limit for the size of returned characters in bytes. \
		Setting this to `0` disables limiting.
		"""
		LOG_DIR = os.path.dirname(self.opsiclientd.config.get("global", "log_file"))
		LOG_TYPES = [  # possible logtypes
			"opsiclientd",
			"opsi-script",
			"opsi_loginblocker",
			"opsiclientdguard",
			"notifier_block_login",
			"notifier_event",
			"opsi-client-agent",
		]
		logType = forceUnicode(logType)

		if logType not in LOG_TYPES:
			raise ValueError(f"Unknown log type {logType}")

		if extension:
			extension = forceUnicode(extension)
			logFile = os.path.join(LOG_DIR, f"{logType}.log.{extension}")
			if not os.path.exists(logFile):
				# Try the other format:
				logFile = os.path.join(LOG_DIR, f"{logType}_{extension}.log")
		else:
			logFile = os.path.join(LOG_DIR, f"{logType}.log")

		try:
			with open(logFile, "r", encoding="utf-8", errors="replace") as log:
				data = log.read()
		except IOError as ioerr:
			if ioerr.errno == 2:  # This is "No such file or directory"
				return "No such file or directory"
			raise

		if maxSize > 0:
			return truncateLogData(data, maxSize)

		return data

	def runCommand(self, command: str, sessionId: int | None = None, desktop: str | None = None) -> str:
		command = forceUnicode(command)
		if not command:
			raise ValueError("No command given")

		if sessionId:
			sessionId = forceInt(sessionId)
		else:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()

		if desktop:
			desktop = forceUnicode(desktop)
		else:
			desktop = self.opsiclientd.getCurrentActiveDesktopName()

		logger.notice("rpc runCommand: executing command '%s' in session %d on desktop '%s'", command, sessionId, desktop)
		runCommandInSession(command=command, sessionId=sessionId, desktop=desktop, waitForProcessEnding=False)
		return f"command '{command}' executed"

	def execute(
		self, command: str, waitForEnding: bool = True, captureStderr: bool = True, encoding: str | None = None, timeout: int = 300
	) -> str:
		return System.execute(cmd=command, waitForEnding=waitForEnding, captureStderr=captureStderr, encoding=encoding, timeout=timeout)

	def logoffSession(self, session_id: str | None = None, username: str | None = None) -> None:
		System.logoffSession(session_id=session_id, username=username)

	def logoffCurrentUser(self) -> None:
		logger.notice("rpc logoffCurrentUser: logging of current user now")
		System.logoffCurrentUser()

	def lockSession(self, session_id: str | None = None, username: str | None = None) -> None:
		System.lockSession(session_id=session_id, username=username)

	def lockWorkstation(self) -> None:
		logger.notice("rpc lockWorkstation: locking workstation now")
		System.lockWorkstation()

	def shutdown(self, waitSeconds: int = 0) -> None:
		waitSeconds = forceInt(waitSeconds)
		logger.notice("rpc shutdown: shutting down computer in %s seconds", waitSeconds)
		self.opsiclientd.shutdownMachine(waitSeconds)

	def reboot(self, waitSeconds: int = 0) -> None:
		waitSeconds = forceInt(waitSeconds)
		logger.notice("rpc reboot: rebooting computer in %s seconds", waitSeconds)
		self.opsiclientd.rebootMachine(waitSeconds)

	def restart(self, waitSeconds: int = 0) -> None:
		waitSeconds = forceInt(waitSeconds)
		logger.notice("rpc restart: restarting opsiclientd in %s seconds", waitSeconds)
		self.opsiclientd.restart(waitSeconds)

	def uptime(self) -> int:
		uptime = int(time.time() - self.opsiclientd._startupTime)
		logger.notice("rpc uptime: opsiclientd is running for %d seconds", uptime)
		return uptime

	def fireEvent(self, name: str, can_cancel: bool = True, event_info: dict[str, str | list[str]] | None = None) -> None:
		return self._fireEvent(name=name, can_cancel=can_cancel, event_info=event_info)

	def processActionRequests(self, product_ids: list[str] | None = None) -> None:
		return self._processActionRequests(product_ids=product_ids)

	def setStatusMessage(self, sessionId: int, message: str) -> None:
		sessionId = forceInt(sessionId)
		message = forceUnicode(message)
		try:
			ept = self.opsiclientd.getEventProcessingThread(sessionId)
			logger.notice("rpc setStatusMessage: Setting status message to '%s'", message)
			ept.setStatusMessage(message)
		except LookupError as error:
			logger.warning("Session does not match EventProcessingThread: %s", error, exc_info=True)

	def isEventRunning(self, name: str) -> bool:
		running = False
		for ept in self.opsiclientd.getEventProcessingThreads():
			if ept.event.eventConfig.getId() == name:
				running = True
				break
		return running

	def getRunningEvents(self) -> list[str]:
		"""
		Returns a list with running events.
		"""
		running = [ept.event.eventConfig.getId() for ept in self.opsiclientd.getEventProcessingThreads()]
		if not running:
			logger.debug("Currently no event is running")
		return running

	def cancelEvents(self, ids: list[str] | None = None) -> bool:
		for ept in self.opsiclientd.getEventProcessingThreads():
			if not ids or ept.event.eventConfig.getId() in ids:
				ept.cancel()
				return True
		return False

	def isInstallationPending(self) -> bool:
		return forceBool(self.opsiclientd.isInstallationPending())

	def getCurrentActiveDesktopName(self, sessionId: int | None = None) -> str | None:
		desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
		logger.notice("rpc getCurrentActiveDesktopName: current active desktop name is %s", desktop)
		return desktop

	def setCurrentActiveDesktopName(self, sessionId: int, desktop: str) -> None:
		sessionId = forceInt(sessionId)
		desktop = forceUnicode(desktop)
		self.opsiclientd._currentActiveDesktopName[sessionId] = desktop
		logger.notice("rpc setCurrentActiveDesktopName: current active desktop name for session %s set to '%s'", sessionId, desktop)

	def switchDesktop(self, desktop: str, sessionId: int | None = None) -> None:
		self.opsiclientd.switchDesktop(desktop, sessionId)

	def getConfig(self) -> dict[str, str | int | float | bool | list[str] | dict[str, str]]:
		return self.opsiclientd.config.getDict()

	def getConfigValue(self, section: str, option: str) -> str | int | float | bool | list[str] | dict[str, str]:
		section = forceUnicode(section)
		option = forceUnicode(option)
		return self.opsiclientd.config.get(section, option)

	def setConfigValue(self, section: str, option: str, value: str | int | float | bool | list[str] | dict[str, str]) -> None:
		section = forceUnicode(section)
		option = forceUnicode(option)
		value = forceUnicode(value)
		self.opsiclientd.config.set(section, option, value)

	def set(self, section: str, option: str, value: str | int | float | bool | list[str] | dict[str, str]) -> None:
		# Legacy method
		self.setConfigValue(section, option, value)

	def readConfigFile(self) -> None:
		self.opsiclientd.config.readConfigFile()

	def updateConfigFile(self, force: bool = False) -> None:
		self.opsiclientd.config.updateConfigFile(force)

	def showPopup(self, message: str, mode: str = "prepend", addTimestamp: bool = True, displaySeconds: int = 0) -> None:
		message = forceUnicode(message)
		self.opsiclientd.showPopup(message=message, mode=mode, addTimestamp=addTimestamp, displaySeconds=displaySeconds)

	def deleteServerCerts(self) -> None:
		config = self.opsiclientd.config
		cert_dir = config.get("global", "server_cert_dir")
		if os.path.exists(cert_dir):
			for filename in os.listdir(cert_dir):
				if os.path.basename(config.ca_cert_file).lower() in filename.strip().lower():
					continue
				os.remove(os.path.join(cert_dir, filename))

	def updateOpsiCaCert(self, ca_cert_pem: str) -> None:
		config = self.opsiclientd.config
		ca_certs: list[x509.Certificate] = []
		for match in re.finditer(r"(-+BEGIN CERTIFICATE-+.*?-+END CERTIFICATE-+)", ca_cert_pem, re.DOTALL):
			try:
				ca_certs.append(x509.load_pem_x509_certificate(match.group(1).encode("utf-8")))
			except Exception as err:
				logger.error(err, exc_info=True)

		if ca_certs:
			if not os.path.isdir(os.path.dirname(config.ca_cert_file)):
				os.makedirs(os.path.dirname(config.ca_cert_file))
			with open(config.ca_cert_file, "wb") as file:
				for cert in ca_certs:
					file.write(cert.public_bytes(encoding=serialization.Encoding.PEM))

	def getActiveSessions(self) -> list[dict[str, str | int | bool | None]]:
		sessions = System.getActiveSessionInformation()
		for session in sessions:
			session["LogonDomain"] = session.get("DomainName")
		return sessions

	def getBackendInfo(self) -> dict[str, Any]:
		with self._config_service_connection() as service_connection:
			return service_connection.getConfigService().backend_info()

	def getState(self, name: str, default: Any = None) -> Any:
		"""
		Return a specified state.

		:param name: Name of the state.
		:param default: Default value if something goes wrong.
		"""
		return self.opsiclientd.state.get(name, default)

	def setState(self, name: str, value: Any) -> None:
		"""
		Set a specified state.

		:param name: Name of the State.
		:param value: Value to set the state.
		"""
		self.opsiclientd.state.set(name, value)

	def updateComponent(self, component: str, url: str) -> None:
		if component != "opsiclientd":
			raise ValueError(f"Invalid component {component}")
		self.opsiclientd.self_update_from_url(url)

	def execPythonCode(self, code: str) -> Any:
		"""Execute lines of python code, returns the result of the last line"""
		code_lines = code.split("\n")
		exec("\n".join(code_lines[:-1]))
		return eval(code_lines[-1])

	def loginUser(self, username: str, password: str) -> None:
		try:
			secret_filter.add_secrets(password)
			self.opsiclientd.loginUser(username, password)
		except Exception as err:
			logger.error(err, exc_info=True)
			raise

	def loginOpsiSetupUser(self, admin: bool = True, recreate_user: bool = False) -> None:
		for session_id in System.getUserSessionIds(OPSI_SETUP_USER_NAME):
			System.logoffSession(session_id)
		user_info = self.opsiclientd.createOpsiSetupUser(admin=admin, delete_existing=recreate_user)
		self.opsiclientd.loginUser(user_info["name"], user_info["password"])

	def getOpenFiles(self, process_filter: str = ".*", path_filter: str = ".*") -> list[dict[str, str]]:
		re_process_filter = re.compile(process_filter, flags=re.IGNORECASE)
		re_path_filter = re.compile(path_filter, flags=re.IGNORECASE)

		file_list = set()
		for proc in psutil.process_iter():
			proc_name = proc.name()
			if not re_process_filter.match(proc_name):
				continue
			try:
				for file in proc.open_files():
					if not re_path_filter.match(file.path):
						continue
					file_list.add((file.path, proc_name))
			except Exception as err:
				logger.warning("Failed to get open files for: %s", err, exc_info=True)

		return [{"file_path": x[0], "process_name": x[1]} for x in sorted(list(file_list))]

	def runOpsiScriptAsOpsiSetupUser(
		self,
		script: str,
		product_id: str | None = None,
		admin: bool = True,
		wait_for_ending: bool | int = 7200,
		remove_user: bool = False,
	) -> None:
		if not is_windows():
			raise NotImplementedError()

		if re.fullmatch(r"^\d+$", str(wait_for_ending)):
			wait_for_ending = int(wait_for_ending)
		else:
			wait_for_ending = forceBool(wait_for_ending)

		logger.notice(
			"Executing opsi script '%s' as opsisetupuser (product_id=%s, admin=%s, wait_for_ending=%s, remove_user=%s)",
			script,
			product_id,
			admin,
			wait_for_ending,
			remove_user,
		)

		config = self.opsiclientd.config
		with self._config_service_connection() as service_connection:
			configServiceUrl = service_connection.getConfigServiceUrl()
			config.selectDepotserver(
				configService=service_connection.getConfigService(),
				mode="mount",
				productIds=[product_id] if product_id else None,
			)
			depot_server_username, depot_server_password = config.getDepotserverCredentials(
				configService=service_connection.getConfigService()
			)

			depot_server_url = config.get("depot_server", "url")
			if not depot_server_url:
				raise RuntimeError("depot_server.url not defined")
			depot_path = config.get_depot_path()
			depot_drive = config.getDepotDrive()
			if depot_path == depot_drive:
				# Prefer depot drive if not in use
				depot_path = depot_drive = System.get_available_drive_letter(start=depot_drive.rstrip(":")).rstrip(":") + ":"

			if not os.path.isabs(script):
				script = os.path.join(depot_path, os.sep, script)

			log_file = os.path.join(config.get("global", "log_dir"), "opsisetupuser.log")

			command = os.path.join(config.get("action_processor", "local_dir"), config.get("action_processor", "filename"))
			if product_id:
				product_id = f'/productid \\"{product_id}\\" '
			else:
				product_id = ""

			command = (
				f'\\"{command}\\" \\"{script}\\" \\"{log_file}\\" /servicebatch {product_id}'
				f'/opsiservice \\"{configServiceUrl}\\" '
				f'/clientid \\"{config.get("global", "host_id")}\\" '
				f'/username \\"{config.get("global", "host_id")}\\" '
				f'/password \\"{config.get("global", "opsi_host_key")}\\"'
			)

			ps_script = Path(config.get("global", "tmp_dir")) / f"run_as_opsi_setup_user_{uuid4()}.ps1"

			ps_script.write_text(
				(
					f"$args = @("
					f"'{config.get('global', 'host_id')}',"
					f"'{config.get('global', 'opsi_host_key')}',"
					f"'{config.get('control_server', 'port')}',"
					f"'{config.get('global', 'log_file')}',"
					f"'{config.get('global', 'log_level')}',"
					f"'{depot_server_url}',"
					f"'{depot_drive}',"
					f"'{depot_server_username}',"
					f"'{depot_server_password}',"
					f"'-1',"
					f"'default',"
					f"'{command}',"
					f"'3600',"
					f"'{OPSI_SETUP_USER_NAME}',"
					f"'\"\"',"
					f"'false'"
					f")\r\n"
					f'& "{os.path.join(os.path.dirname(sys.argv[0]), "action_processor_starter.exe")}" $args\r\n'
					f'Remove-Item -Path "{str(ps_script)}" -Force\r\n'
				),
				encoding="windows-1252",
			)

			self._run_powershell_script_as_opsi_setup_user(
				script=ps_script,
				admin=admin,
				recreate_user=False,
				remove_user=remove_user,
				wait_for_ending=wait_for_ending,
				shell_window_style="hidden",
			)

	def runAsOpsiSetupUser(
		self,
		command: str = "powershell.exe -ExecutionPolicy Bypass",
		admin: bool = True,
		recreate_user: bool = False,
		remove_user: bool = False,
		wait_for_ending: bool | int = False,
	) -> None:
		script = Path(self.opsiclientd.config.get("global", "tmp_dir")) / f"run_as_opsi_setup_user_{uuid4()}.ps1"
		# catch <Drive>:.....exe and put in quotes if not already quoted
		if re.search("[A-Z]:.*\\.exe", command) and not command.startswith(('"', "'")):
			command = re.sub("([A-Z]:.*\\.exe)", '"\\1"', command, count=1)
		parts = shlex.split(command, posix=False)
		if not parts:
			raise ValueError(f"Invalid command {command}")
		if len(parts) == 1:
			script_content = f"Start-Process -FilePath {parts[0]} -Wait\r\n"
		else:
			script_content = (
				f"""Start-Process -FilePath {parts[0]} -ArgumentList {','.join((f'"{entry}"' for entry in parts[1:]))} -Wait\r\n"""
			)
		# WARNING: This part is not executed if the command call above initiates reboot
		script_content += f'Remove-Item -Path "{str(script)}" -Force\r\n'
		script.write_text(script_content, encoding="windows-1252")
		logger.debug("Preparing script:\n%s", script_content)
		try:
			self._run_powershell_script_as_opsi_setup_user(
				script=script,
				admin=admin,
				recreate_user=recreate_user,
				remove_user=remove_user,
				wait_for_ending=wait_for_ending,
				shell_window_style="normal",
			)
		except Exception as err:
			logger.error(err, exc_info=True)
			raise

	def _run_process_as_opsi_setup_user(self, command: str, admin: bool, recreate_user: bool) -> None:
		# https://bugs.python.org/file46988/issue.py
		if not is_windows():
			raise NotImplementedError(f"Not implemented on {platform.system()}")
		import winreg  # type: ignore[import]

		import pywintypes  # type: ignore[import]
		import win32profile  # type: ignore[import]
		import win32security  # type: ignore[import]

		for session_id in System.getUserSessionIds(OPSI_SETUP_USER_NAME):
			System.logoffSession(session_id)
		user_info = self.opsiclientd.createOpsiSetupUser(admin=admin, delete_existing=recreate_user)

		logon = win32security.LogonUser(
			user_info["name"],
			None,
			user_info["password"],
			win32security.LOGON32_LOGON_INTERACTIVE,
			win32security.LOGON32_PROVIDER_DEFAULT,
		)

		try:
			for attempt in (1, 2, 3, 4, 5):
				try:
					# This will create the user home dir and ntuser.dat gets loaded
					# Can fail if C:\users\default\ntuser.dat is locked by an other process
					hkey = win32profile.LoadUserProfile(logon, {"UserName": user_info["name"]})  # type: ignore[arg-type]
					break
				except pywintypes.error as err:
					logger.warning("Failed to load user profile (attempt #%d): %s", attempt, err)
					time.sleep(5)
					if attempt == 5:
						raise

			try:
				# env = win32profile.CreateEnvironmentBlock(logon, False)
				str_sid = win32security.ConvertSidToStringSid(user_info["user_sid"])
				reg_key = winreg.OpenKey(  # type: ignore[attr-defined]
					winreg.HKEY_USERS,  # type: ignore[attr-defined]
					str_sid + r"\Software\Microsoft\Windows NT\CurrentVersion\Winlogon",
					0,
					winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,  # type: ignore[attr-defined]
				)
				with reg_key:
					winreg.SetValueEx(reg_key, "Shell", 0, winreg.REG_SZ, command)  # type: ignore[attr-defined]
			finally:
				win32profile.UnloadUserProfile(logon, hkey)  # type: ignore[arg-type]

		finally:
			logon.close()

		assert self.opsiclientd._controlPipe, "Control pipe not initialized"
		if not self.opsiclientd._controlPipe.credentialProviderConnected():  # type: ignore[attr-defined]
			for _unused in range(20):
				if self.opsiclientd._controlPipe.credentialProviderConnected():  # type: ignore[attr-defined]
					break
				time.sleep(0.5)

		self.opsiclientd.loginUser(user_info["name"], user_info["password"])

	def _run_powershell_script_as_opsi_setup_user(
		self,
		script: Path,
		admin: bool = True,
		recreate_user: bool = False,
		remove_user: bool = False,
		wait_for_ending: bool | int = False,
		shell_window_style: str = "normal",  # Normal / Minimized / Maximized / Hidden
	) -> None:
		if shell_window_style.lower() not in ("normal", "minimized", "maximized", "hidden"):
			raise ValueError(f"Invalid value for shell_window_style: {shell_window_style!r}")
		if not self._run_as_opsi_setup_user_lock.acquire(blocking=False):
			raise RuntimeError("Another process is already running")
		if remove_user and not wait_for_ending:
			wait_for_ending = True

		# Remove inherited permissions, allow SYSTEM only
		logger.info("Setting permissions: %s", ["icacls", str(script), " /inheritance:r", "/grant:r", "SYSTEM:(OI)(CI)F"])
		subprocess.run(["icacls", str(script), " /inheritance:r", "/grant:r", "SYSTEM:(OI)(CI)F"], check=False)

		try:
			self._run_process_as_opsi_setup_user(
				f'powershell.exe -ExecutionPolicy Bypass -WindowStyle {shell_window_style} -File "{str(script)}"',
				admin,
				recreate_user,
			)
			if wait_for_ending:
				timeout = 7200
				if not isinstance(wait_for_ending, bool):
					timeout = int(wait_for_ending)
				logger.info("Wait for process to complete (timeout=%r)", timeout)
				try:
					start = time.time()
					while script.exists():
						time.sleep(1)
						if time.time() >= start + timeout:
							logger.warning("Timed out after %r seconds while waiting for process to complete", timeout)
							break
				finally:
					for session_id in System.getUserSessionIds(OPSI_SETUP_USER_NAME):
						System.logoffSession(session_id)
					if script.exists():
						script.unlink()
					if remove_user:
						self.opsiclientd.cleanup_opsi_setup_user()  # type: ignore[attr-defined]
		except Exception as err:
			logger.error(err, exc_info=True)
			raise
		finally:
			self._run_as_opsi_setup_user_lock.release()

	def removeOpsiSetupUser(self) -> None:
		self.opsiclientd.cleanup_opsi_setup_user()

	def runOnShutdown(self) -> bool:
		on_shutdown_active = False
		for event_config in getEventConfigs().values():
			if event_config["name"] == "on_shutdown" and event_config["active"]:
				on_shutdown_active = True
				break

		if not on_shutdown_active:
			logger.info("on_shutdown event is not active")
			return False

		if self.opsiclientd.isRebootTriggered() or self.opsiclientd.isShutdownTriggered():
			logger.info("Reboot or shutdown is triggered, not firing on_shutdown")
			return False

		if self.isInstallationPending():
			logger.info("Installations are pending, not firing on_shutdown")
			return False

		logger.info("Firing on_shutdown and waiting for event to complete")
		self.fireEvent("on_shutdown")
		time.sleep(10)
		while self.isEventRunning("on_shutdown"):
			time.sleep(10)

		logger.info("on_shutdown event completed")
		return True

	def messageOfTheDayUpdated(
		self,
		device_message: str | None = None,
		device_message_valid_until: int = 0,
		user_message: str | None = None,
		user_message_valid_until: int = 0,
	) -> list[str]:
		return self.opsiclientd.updateMOTD(
			device_message=device_message,
			device_message_valid_until=device_message_valid_until,
			user_message=user_message,
			user_message_valid_until=user_message_valid_until,
		)

	def downloadFromDepot(self, product_id: str, destination: str, sub_path: str | None = None) -> None:
		download_from_depot(product_id, Path(destination).resolve(), sub_path)

	def getLogs(self, log_types: list[str] | None = None, max_age_days: int = 0) -> str:
		file_path = self.opsiclientd.collectLogfiles(types=log_types, max_age_days=max_age_days)
		assert self.opsiclientd._permanent_service_connection, "Need permanent service connection for getLogs"
		logger.notice("Delivering file %s", file_path)
		with open(file_path, "rb") as file_handle:
			# requests accepts "Dictionary, list of tuples, bytes, or file-like object to send in the body of the Request" as data
			response = self.opsiclientd._permanent_service_connection.service_client.post("/file-transfer", data=file_handle)  # type: ignore[call-overload]
			logger.debug("Got response with status %s: %s", response.status_code, response.content.decode("utf-8"))
			return json.loads(response.content.decode("utf-8"))

	def replaceOpsiHostKey(self, new_key: str | None = None) -> None:
		if not new_key:
			new_key = generate_opsi_host_key()
		secret_filter.add_secrets(new_key)
		config = self.opsiclientd.config

		logger.info("Replacing opsi host key on service")
		with self._config_service_connection() as service_connection:
			configService = service_connection.getConfigService()
			host = configService.host_getObjects(id=config.get("global", "host_id"))[0]
			host.setOpsiHostKey(new_key)
			configService.host_updateObject(host)

		logger.info("Replacing opsi host key in config")
		config.set("global", "opsi_host_key", new_key)
		config.updateConfigFile(force=True)

		logger.info("Removing config cache")
		try:
			cache_service = self.opsiclientd.getCacheService()
			cache_service.setConfigCacheFaulty()
			assert cache_service._configCacheService
			cache_service._configCacheService.delete_cache_dir()
		except Exception as err:
			logger.warning(err, exc_info=True)

		self.opsiclientd.restart(2)

	def getProcessInfo(self, interval: float = 5.0) -> dict[str, Any]:
		info: dict[str, Any] = {"threads": []}
		proc = psutil.Process()
		proc.cpu_percent()
		cpu_times_start = proc.cpu_times()._asdict()
		p_thread_cpu_times_start = {t.id: {"user": t.user_time, "system": t.system_time} for t in proc.threads()}
		time.sleep(interval)
		cpu_percent = proc.cpu_percent()
		cpu_times_end = proc.cpu_times()._asdict()
		cpu_times = {k: v - cpu_times_start[k] for k, v in cpu_times_end.items()}
		info["cpu_times"] = cpu_times
		info["cpu_percent"] = cpu_percent
		cpu_times_proc = cpu_times["system"] + cpu_times["user"]
		thread_by_id = {t.native_id: t for t in threading.enumerate()}
		for p_thread in proc.threads():
			thread = thread_by_id.get(p_thread.id)
			if not thread:
				continue
			cts = p_thread_cpu_times_start.get(p_thread.id)
			if not cts:
				continue
			user_time = p_thread.user_time - cts["user"]
			system_time = p_thread.system_time - cts["system"]
			info["threads"].append(
				{
					"id": p_thread.id,
					"name": thread.name,
					"run_func": str(thread.run),
					"cpu_times": {"user": user_time, "system": system_time},
					"cpu_percent": (cpu_percent * ((system_time + user_time) / cpu_times_proc)) if cpu_times_proc else 0.0,
				}
			)
		return info

	def getLocalizationInfo(self) -> dict[str, Any]:
		return get_translation_info()

	def translateMessage(self, message: str) -> str:
		return _(message)


@lru_cache
def get_pipe_control_interface(opsiclientd: Opsiclientd) -> PipeControlInterface:
	return PipeControlInterface(opsiclientd)


@lru_cache
def get_kiosk_control_interface(opsiclientd: Opsiclientd) -> KioskControlInterface:
	return KioskControlInterface(opsiclientd)


@lru_cache
def get_control_interface(opsiclientd: Opsiclientd) -> ControlInterface:
	return ControlInterface(opsiclientd)


@lru_cache
def get_cache_service_interface(opsiclientd: Opsiclientd) -> ControlInterface:
	cache_service = opsiclientd.getCacheService()
	if not cache_service:
		raise RuntimeError("Cache service not running")

	backend = cache_service.getConfigBackend()
	setattr(backend, "_interface", {})
	setattr(backend, "_interface_list", [])
	setattr(backend, "_create_interface", MethodType(Interface._create_interface, backend))
	setattr(backend, "get_interface", MethodType(Interface.get_interface, backend))
	setattr(backend, "get_method_interface", MethodType(Interface.get_method_interface, backend))
	backend._create_interface()
	return backend
