# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Basic opsiclientd implementation. This is abstract in some parts that
should be overridden in the concrete implementation for an OS.
"""


import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Generator

import psutil  # type: ignore[import]
from OPSI import System  # type: ignore[import]
from OPSI import __version__ as python_opsi_version  # type: ignore[import]
from OPSI.Util import randomString  # type: ignore[import]
from OPSI.Util.Message import (  # type: ignore[import]
	ChoiceSubject,
	MessageSubject,
	NotificationServer,
)
from opsicommon import __version__ as opsicommon_version
from opsicommon.logging import get_logger, log_context, secret_filter
from opsicommon.system import ensure_not_already_running
from opsicommon.system.subprocess import patch_popen
from opsicommon.types import forceBool, forceInt, forceUnicode

from opsiclientd import __version__, check_signature, config, notify_posix_terminals
from opsiclientd.ControlPipe import ControlPipe, ControlPipeFactory
from opsiclientd.ControlServer import ControlServer
from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.EventProcessing import EventProcessingThread
from opsiclientd.Events.Basic import CannotCancelEventError, Event, EventListener
from opsiclientd.Events.DaemonShutdown import DaemonShutdownEventGenerator
from opsiclientd.Events.DaemonStartup import DaemonStartupEventGenerator
from opsiclientd.Events.GUIStartup import (
	GUIStartupEventConfig,
	GUIStartupEventGenerator,
)
from opsiclientd.Events.Panic import PanicEvent
from opsiclientd.Events.Utilities.Factories import EventGeneratorFactory
from opsiclientd.Events.Utilities.Generators import (
	createEventGenerators,
	getEventGenerators,
)
from opsiclientd.Localization import _
from opsiclientd.OpsiService import PermanentServiceConnection
from opsiclientd.setup import setup
from opsiclientd.State import State
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline

if RUNNING_ON_WINDOWS:
	from opsiclientd.Events.Windows.UserLogin import LoginDetector
	from opsiclientd.windows import runCommandInSession
else:
	from OPSI.System import runCommandInSession  # type: ignore

patch_popen()

timeline = Timeline()
state = State()

logger = get_logger("opsiclientd")


def sha256string(input_string: str) -> str:
	return sha256(input_string.encode("utf-8")).digest().hex()


class Opsiclientd(EventListener, threading.Thread):
	def __init__(self) -> None:
		logger.debug("Opsiclient initiating")

		EventListener.__init__(self)
		threading.Thread.__init__(self)

		self._startupTime = time.time()
		self._running = False
		self._eventProcessingThreads: list[EventProcessingThread] = []
		self.eventLock = threading.Lock()
		self._eptListLock = threading.Lock()
		self._blockLogin = True
		self._currentActiveDesktopName: dict[str, str] = {}
		self._gui_waiter: WaitForGUI | None = None

		self._isRebootTriggered = False
		self._isShutdownTriggered = False

		self._actionProcessorUserName = ""
		self._actionProcessorUserPassword = ""

		self._statusApplicationProcess = None
		self._blockLoginNotifierPid = None

		self._popupNotificationServer = None
		self._popupNotificationLock = threading.Lock()
		self._popupClosingThread = None

		self._blockLoginEventId = None
		self._opsiclientdRunningEventId = None

		self._stopEvent = threading.Event()
		self._stopEvent.clear()

		self._cacheService = None
		self._controlPipe: ControlPipe | None = None
		self._controlServer: ControlServer | None = None
		self._permanent_service_connection: PermanentServiceConnection | None = None
		self._selfUpdating = False
		self.login_detector: LoginDetector | None = None

		self._argv = list(sys.argv)
		self._argv[0] = os.path.abspath(self._argv[0])

	def start_permanent_service_connection(self) -> None:
		if self._permanent_service_connection and self._permanent_service_connection.running:
			return

		if not self._controlServer:
			raise RuntimeError("Control server not started - cannot start permanent service connection")
		logger.info("Starting permanent service connection")
		self._permanent_service_connection = PermanentServiceConnection(self._controlServer._opsiclientdRpcInterface)
		self._permanent_service_connection.start()

	def stop_permanent_service_connection(self) -> None:
		if self._permanent_service_connection and self._permanent_service_connection.running:
			logger.info("Stopping permanent service connection")
			self._permanent_service_connection.stop()
			time.sleep(1)
			self._permanent_service_connection = None

	def self_update_from_url(self, url: str) -> None:
		logger.notice("Self-update from url: %s", url)

		epts = self.getEventProcessingThreads()
		if not epts:
			logger.notice("No event processing threads running")
		for ept in epts:
			logger.notice("Canceling event processing thread %s", ept)
			ept.cancel()

		filename = url.split("/")[-1]
		with tempfile.TemporaryDirectory() as tmpdir:
			filename = os.path.join(tmpdir, filename)
			if url.startswith("file://"):
				src = url[7:]
				if RUNNING_ON_WINDOWS:
					src = src.lstrip("/").replace("/", "\\")
				shutil.copy(src, filename)
			else:
				with urllib.request.urlopen(url) as response:
					with open(filename, "wb") as file:
						file.write(response.read())
			self.self_update_from_file(filename)

	def self_update_from_file(self, filename: str) -> None:
		logger.notice("Self-update from file %s", filename)

		test_file = "base_library.zip"
		inst_dir = Path(__file__).resolve().parent.parent
		if not (inst_dir / test_file).exists():
			raise RuntimeError(f"File not found: {inst_dir / test_file}")

		if self._selfUpdating:
			raise RuntimeError("Self-update already running")

		self._selfUpdating = True
		try:
			with tempfile.TemporaryDirectory() as tmpdir_name:
				tmpdir = Path(tmpdir_name)
				destination = tmpdir / "content"
				shutil.unpack_archive(filename=filename, extract_dir=destination)

				bin_dir: Path | None = destination
				if not (destination / test_file).exists():
					bin_dir = None
					for entry in destination.iterdir():
						if (entry / test_file).exists():
							bin_dir = entry
							break
				if not bin_dir:
					raise RuntimeError("Invalid archive")

				try:
					check_signature(str(bin_dir))
				except Exception as err:
					logger.error("Could not verify signature!\n%s", err, exc_info=True)
					logger.error("Not performing self_update.")
					raise RuntimeError("Invalid signature") from err

				binary = bin_dir / os.path.basename(self._argv[0])

				logger.info("Testing new binary: %s", binary)
				# need to direct stderr to stdout to avoid error in cleanup due to 32 bit python performance warning (code 120)
				out = subprocess.check_output([str(binary), "--version"], stderr=subprocess.STDOUT)
				logger.info(out)

				if RUNNING_ON_WINDOWS:
					inst1 = inst_dir.with_name("opsiclientd_bin1")
					inst2 = inst_dir.with_name("opsiclientd_bin2")
					link = inst_dir.with_name("opsiclientd_bin")
					process_stdout = subprocess.run(
						f"powershell.exe -ExecutionPolicy Bypass -Command \"Get-Item '{link}' | Select-Object -ExpandProperty Target\"",
						text=True,
						capture_output=True,
						shell=False,
						check=False,
					).stdout.strip()
					if link.exists() and not process_stdout:
						raise RuntimeError(f"{link} is not a link")

					logger.info("Link '%s' is pointing to '%s'", link, process_stdout)

					target = Path(process_stdout)
					logger.info("Names: inst1=%r, inst2=%r, target=%r", inst1.name, inst2.name, target.name)
					new_dir = inst2 if target.name == inst1.name else inst1

					if new_dir.exists():
						logger.info("Deleting dir '%s'", new_dir)
						shutil.rmtree(new_dir)

					logger.info("Moving '%s' to '%s'", bin_dir, new_dir)
					bin_dir.rename(new_dir)

					logger.info("Creating link '%s' pointing to '%s'", link, new_dir)
					process_stdout = subprocess.run(
						f'rmdir "{link}" & mklink /j "{link}" "{new_dir}"', text=True, capture_output=True, check=False, shell=True
					).stdout
					logger.debug(process_stdout)
				else:
					old_dir = inst_dir.with_name(f"{inst_dir.name}_old")
					logger.info("Moving current installation dir '%s' to '%s'", inst_dir, old_dir)
					if old_dir.exists():
						shutil.rmtree(old_dir)
					inst_dir.rename(old_dir)

					logger.info("Installing '%s' into '%s'", bin_dir, inst_dir)
					bin_dir.rename(inst_dir)

				self.restart(3)
		finally:
			self._selfUpdating = False

	def restart(self, waitSeconds: int = 0, disabled_event_types: list[str] | None = None) -> None:
		if disabled_event_types is None:
			disabled_event_types = ["gui startup", "daemon startup"]

		def _restart(waitSeconds: int = 0) -> None:
			time.sleep(waitSeconds)
			timeline.addEvent(title="opsiclientd restart", category="system")
			try:
				if not os.path.exists(config.restart_marker):
					logger.notice("Writing restart marker %r (disabled_event_types=%r)", config.restart_marker, disabled_event_types)
					with open(config.restart_marker, "w", encoding="utf-8") as file:
						file.write(f"disabled_event_types={','.join(disabled_event_types)}\nrestart_service=false\nremove_marker=true\n")
			except Exception as err:
				logger.error(err)

			if RUNNING_ON_WINDOWS:
				subprocess.Popen(
					"net stop opsiclientd & net start opsiclientd",
					shell=True,
					creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,  # type: ignore[attr-defined]  # only windows
				)
			else:
				logger.notice("Executing: %s", self._argv)
				os.chdir(os.path.dirname(self._argv[0]))
				os.execvp(self._argv[0], self._argv)

		logger.notice("Will restart in %d seconds", waitSeconds)
		threading.Thread(target=_restart, args=(waitSeconds,)).start()

	def setBlockLogin(self, blockLogin: bool, handleNotifier: bool = True) -> None:
		blockLogin = forceBool(blockLogin)
		changed = self._blockLogin != blockLogin
		self._blockLogin = blockLogin
		logger.notice("Block login now set to '%s'", self._blockLogin)

		if self._blockLogin:
			if not self._blockLoginEventId:
				self._blockLoginEventId = timeline.addEvent(
					title="Blocking login", description="User login blocked", category="block_login", durationEvent=True
				)

			if not self._blockLoginNotifierPid and config.get("global", "block_login_notifier"):
				if handleNotifier and RUNNING_ON_WINDOWS:
					logger.info("Starting block login notifier app")
					# Start block login notifier on physical console
					sessionId = System.getActiveConsoleSessionId()
					while True:
						try:
							self._blockLoginNotifierPid = System.runCommandInSession(
								command=config.get("global", "block_login_notifier"),
								sessionId=sessionId,
								desktop="winlogon",
								waitForProcessEnding=False,
							)[2]
							break
						except Exception as err:
							logger.error("Failed to start block login notifier app: %s", err)
							break
		else:
			if self._blockLoginEventId:
				timeline.setEventEnd(eventId=self._blockLoginEventId)
				self._blockLoginEventId = None

			if handleNotifier and self._blockLoginNotifierPid:
				try:
					logger.info("Terminating block login notifier app (pid %s)", self._blockLoginNotifierPid)
					System.terminateProcess(processId=self._blockLoginNotifierPid)
				except Exception as err:
					log = logger.warning
					if isinstance(err, OSError) and getattr(err, "errno", None) == 87:
						# Process already terminated
						log = logger.debug
					log("Failed to terminate block login notifier app: %s", err)
				self._blockLoginNotifierPid = None

		if changed and self._controlPipe:
			try:
				self._controlPipe.executeRpc("blockLogin", self._blockLogin)
			except Exception as rpc_error:
				logger.debug(rpc_error)

	def loginUser(self, username: str, password: str) -> None:
		raise NotImplementedError(f"Not implemented on {platform.system()}")

	def isRunning(self) -> bool:
		return self._running

	def is_stopping(self) -> bool:
		return self._stopEvent.is_set()

	def waitForGUI(self, timeout: float | None = None) -> None:
		self._gui_waiter = WaitForGUI(self)
		self._gui_waiter.wait(timeout)
		self._gui_waiter = None

	def createActionProcessorUser(self, recreate: bool = True) -> None:
		if not config.get("action_processor", "create_user"):
			return

		run_as_user = config.get("action_processor", "run_as_user")
		if run_as_user.lower() == "system":
			self._actionProcessorUserName = ""
			self._actionProcessorUserPassword = ""
			return

		if "\\" in run_as_user:
			logger.warning("Ignoring domain part of user to run action processor '%s'", run_as_user)
			run_as_user = run_as_user.split("\\", -1)

		if not recreate and self._actionProcessorUserName and self._actionProcessorUserPassword and System.existsUser(username=run_as_user):
			return

		self._actionProcessorUserName = run_as_user
		logger.notice(f"Creating local user '{run_as_user}'")

		self._actionProcessorUserPassword = "$!?" + str(randomString(16)) + "!/%"
		secret_filter.add_secrets(self._actionProcessorUserPassword)

		if System.existsUser(username=run_as_user):
			System.deleteUser(username=run_as_user)
		System.createUser(username=run_as_user, password=self._actionProcessorUserPassword, groups=[System.getAdminGroupName()])

	def deleteActionProcessorUser(self) -> None:
		if not config.get("action_processor", "delete_user"):
			return

		if not self._actionProcessorUserName:
			return

		if not System.existsUser(username=self._actionProcessorUserName):
			return

		logger.notice("Deleting local user '%s'", self._actionProcessorUserName)
		System.deleteUser(username=self._actionProcessorUserName)
		self._actionProcessorUserName = ""
		self._actionProcessorUserPassword = ""

	def run(self) -> None:
		with log_context({"instance": "opsiclientd"}):
			try:
				self._run()
			except Exception as err:
				logger.error(err, exc_info=True)

	def _run(self) -> None:
		ensure_not_already_running("opsiclientd")
		self._running = True
		self._opsiclientdRunningEventId = None

		try:
			state.start()
		except Exception as err:
			logger.error("Failed to start state: %s", err, exc_info=True)
		try:
			timeline.start()
		except Exception as err:
			logger.error("Failed to start timeline: %s", err, exc_info=True)

		config.readConfigFile()
		try:
			restart_marker_config = config.check_restart_marker()
		except Exception as err:
			logger.error(err, exc_info=True)

		setup(full=False)

		@contextmanager
		def getControlPipe() -> Generator[None, None, None]:
			logger.notice("Starting control pipe")
			try:
				self._controlPipe = ControlPipeFactory(self)
				assert self._controlPipe
				self._controlPipe.daemon = True
				self._controlPipe.start()
				logger.notice("Control pipe started")
				yield
			except Exception as err:
				logger.error("Failed to start control pipe: %s", err, exc_info=True)
				raise
			finally:
				logger.info("Stopping control pipe")
				try:
					if self._controlPipe:
						self._controlPipe.stop()
						self._controlPipe.join(2)
						logger.info("Control pipe stopped")
				except (NameError, RuntimeError) as stopError:
					logger.debug("Stopping controlPipe failed: %s", stopError)

		@contextmanager
		def getControlServer() -> Generator[None, None, None]:
			logger.notice("Starting control server")
			self._controlServer = None
			try:
				self._controlServer = ControlServer(
					opsiclientd=self,
					httpsPort=config.get("control_server", "port"),
					sslServerKeyFile=config.get("control_server", "ssl_server_key_file"),
					sslServerCertFile=config.get("control_server", "ssl_server_cert_file"),
					staticDir=config.get("control_server", "static_dir"),
				)
				logger.debug("Current control server: %s", self._controlServer)
				self._controlServer.start()
				logger.notice("Control server started")

				self._stopEvent.wait(1)
				if self._stopEvent.is_set():
					# Probably a failure during binding to port.
					raise RuntimeError("Received stop signal.")

				yield
			except Exception as err:
				logger.error("Failed to start control server: %s", err, exc_info=True)
				raise err
			finally:
				if self._controlServer:
					logger.info("Stopping control server")
					try:
						self._controlServer.stop()
						self._controlServer.join(2)
						logger.info("Control server stopped")
					except (NameError, RuntimeError) as stopError:
						logger.debug("Stopping controlServer failed: %s", stopError)

		@contextmanager
		def getCacheService() -> Generator[Any | None, None, None]:  # not typing here for speedup (costly import)
			cache_service = None
			try:
				logger.notice("Starting cache service")
				from opsiclientd.nonfree.CacheService import CacheService

				cache_service = CacheService(opsiclientd=self)
				cache_service.start()
				logger.notice("Cache service started")
				yield cache_service
			except Exception as err:
				logger.error("Failed to start cache service: %s", err, exc_info=True)
				yield None
			finally:
				if cache_service:
					logger.info("Stopping cache service")
					try:
						cache_service.stop()
						cache_service.join(2)
						logger.info("Cache service stopped")
					except (NameError, RuntimeError) as stop_err:
						logger.debug("Failed to stop cache service: %s", stop_err)

		@contextmanager
		def getEventGeneratorContext() -> Generator[None, None, None]:
			logger.debug("Creating event generators")
			createEventGenerators(self)

			for eventGenerator in getEventGenerators():
				eventGenerator.addEventListener(self)
				eventGenerator.start()
				logger.info("Event generator '%s' started", eventGenerator)

			if RUNNING_ON_WINDOWS:
				try:
					logger.info("Starting LoginDetector for message of the day.")
					self.login_detector = LoginDetector(self, EventConfig("login_detector"))
					self.login_detector.start()
				except Exception as error:
					logger.error("Failed to start LoginDetector: %s", error, exc_info=True)
			try:
				yield
			finally:
				if RUNNING_ON_WINDOWS and isinstance(self.login_detector, LoginDetector):
					logger.info("Stopping LoginDetector for message of the day.")
					self.login_detector.stop()
					self.login_detector.join(2)
				for eventGenerator in getEventGenerators():
					logger.info("Stopping event generator %s", eventGenerator)
					eventGenerator.stop()
					eventGenerator.join(2)
					logger.info("Event generator %s stopped", eventGenerator)

		@contextmanager
		def getDaemonLoopingContext() -> Generator[None, None, None]:
			with getEventGeneratorContext():
				for event_generator in getEventGenerators(generatorClass=DaemonStartupEventGenerator):
					try:
						event_generator.createAndFireEvent()
					except (ValueError, CannotCancelEventError) as err:
						logger.error("Unable to fire DaemonStartupEvent from %s: %s", event_generator, err, exc_info=True)

				if getEventGenerators(generatorClass=GUIStartupEventGenerator):
					# Wait until gui starts up
					logger.notice("Waiting for gui startup (timeout: %d seconds)", config.get("global", "wait_for_gui_timeout"))
					self.waitForGUI(timeout=config.get("global", "wait_for_gui_timeout"))
					if not self.is_stopping():
						logger.notice("Done waiting for GUI")
						# Wait some more seconds for events to fire
						time.sleep(5)
				try:
					yield
				finally:
					for event_generator in getEventGenerators(generatorClass=DaemonShutdownEventGenerator):
						logger.info("Create and fire shutdown event generator %s", event_generator)
						try:
							event_generator.createAndFireEvent()
						except (ValueError, CannotCancelEventError) as err:
							logger.error("Unable to fire DaemonStartupEvent from %s: %s", event_generator, err, exc_info=True)

		try:
			parent = psutil.Process(os.getpid()).parent()
			parent_name = parent.name() if parent else None
			event_title = (
				f"Opsiclientd {__version__} [python-opsi={python_opsi_version},python-opsi-common={opsicommon_version}] "
				f"running on {platform.platform()!r}"
			)
			logger.essential(event_title)
			event_description = f"Parent process: {parent_name}\n"
			logger.essential(f"Parent process: {parent_name}")
			event_description += f"Commandline: {' '.join(sys.argv)}\n"
			logger.essential(f"Commandline: {' '.join(sys.argv)}")
			event_description += f"Working directory: {os.getcwd()}\n"
			logger.essential(f"Working directory: {os.getcwd()}")
			event_description += f"Using host id '{config.get('global', 'host_id')}'"
			logger.notice(f"Using host id '{config.get('global', 'host_id')}'")

			logger.debug("Environment: %s", os.environ)

			# Do not show block login notifier yet!
			self.setBlockLogin(True, handleNotifier=False)

			self._opsiclientdRunningEventId = timeline.addEvent(
				title=event_title, description=event_description, category="opsiclientd_running", durationEvent=True
			)

			with getControlPipe():
				with getControlServer():
					if config.get("config_service", "permanent_connection"):
						self.start_permanent_service_connection()

					if restart_marker_config and restart_marker_config.run_opsi_script:
						log_dir = config.get("global", "log_dir")
						action_processor = os.path.join(
							config.get("action_processor", "local_dir"), config.get("action_processor", "filename")
						)
						param_char = "/" if RUNNING_ON_WINDOWS else "-"
						cmd = [
							action_processor,
							restart_marker_config.run_opsi_script,
							os.path.join(log_dir, "start_opsi_script.log"),
							f"{param_char}servicebatch",
						]
						if restart_marker_config.product_id:
							cmd += [
								f"{param_char}productid",
								restart_marker_config.product_id,
							]
						cmd += [
							f"{param_char}opsiservice",
							config.getConfigServiceUrls(allowTemporaryConfigServiceUrls=False)[0],
							f"{param_char}clientid",
							config.get("global", "host_id"),
							f"{param_char}username",
							config.get("global", "host_id"),
							f"{param_char}password",
							config.get("global", "opsi_host_key"),
							f"{param_char}parameter",
							f"opsiclientd_restart_marker={config.restart_marker}",
						]
						logger.notice("Running startup script: %s", cmd)
						System.execute(cmd, shell=False, waitForEnding=True, timeout=3600)

						restart_marker_config = config.check_restart_marker()
						if restart_marker_config and restart_marker_config.restart_service:
							logger.notice("Restart marker found, restarting")
							self.restart(disabled_event_types=restart_marker_config.disabled_event_types)
							return

					with getCacheService() as cacheService:
						self._cacheService = cacheService

						with getDaemonLoopingContext():
							with self._eptListLock:
								if not self._eventProcessingThreads:
									logger.notice("No events processing, unblocking login")
									self.setBlockLogin(False)

							try:
								self.updateMOTD()  # daemon startup is done, gui is up
							except Exception as error:
								logger.error("Failed to update message of the day: %s", error, exc_info=True)

							try:
								while not self._stopEvent.is_set():
									self._stopEvent.wait(1)
							finally:
								logger.notice("opsiclientd is going down")
								with self._eptListLock:
									for ept in self._eventProcessingThreads:
										ept.stop()
									for ept in self._eventProcessingThreads:
										logger.info("Waiting for event processing thread %s", ept)
										ept.join(5)

								if self._opsiclientdRunningEventId:
									timeline.setEventEnd(self._opsiclientdRunningEventId)
								logger.info("Stopping timeline")
								timeline.stop()
		except Exception as err:
			if not self._stopEvent.is_set():
				logger.error(err, exc_info=True)
			self.setBlockLogin(False)
		finally:
			self.stop_permanent_service_connection()
			self._running = False
			for thread in threading.enumerate():
				logger.info("Runnning thread on main thread exit: %s", thread)

			logger.info("Exiting opsiclientd thread")

	def stop(self) -> None:
		logger.notice("Stopping %s", self)
		if self._gui_waiter:
			self._gui_waiter.stop()
		self._stopEvent.set()

	def getCacheService(self) -> Any:  # Not typing here for speedup (costly import)
		if not self._cacheService:
			raise RuntimeError("Cache service not started")
		return self._cacheService

	def canProcessEvent(self, event: Event, can_cancel: bool = False) -> bool:
		# Always process panic events
		if isinstance(event, PanicEvent):
			return True
		with self._eptListLock:
			for ept in self._eventProcessingThreads:
				if not ept.is_cancelable():
					logger.notice("Already processing a non-cancelable event: %s", ept.event.eventConfig.getId())
					raise CannotCancelEventError(f"Already processing a non-cancelable event: {ept.event.eventConfig.getId()}")
				if not can_cancel:
					logger.notice(
						"Currently running event can only be canceled by manual action (ControlServer/Kiosk): %s",
						ept.event.eventConfig.getId(),
					)
					raise CannotCancelEventError(
						"Currently running event can only be canceled by manual action (ControlServer/Kiosk): "
						f"{ept.event.eventConfig.getId()}"
					)
		return True

	def cancelOthersAndWaitUntilReady(self) -> None:
		WAIT_SECONDS = 30
		with self._eptListLock:
			eptListCopy = self._eventProcessingThreads.copy()
			for ept in self._eventProcessingThreads:
				if ept.event.eventConfig.actionType != "login":
					# trying to cancel all non-login events - RuntimeError if impossible
					logger.notice("Canceling event processing thread %s (ocd)", ept)
					ept.cancel(no_lock=True)
			logger.trace("Waiting for cancellation to conclude")

		# Use copy to allow for epts to be removed from eptList
		for ept in eptListCopy:
			if ept.event.eventConfig.actionType != "login":
				logger.trace("Waiting for ending of ept %s (ocd)", ept)
				for _unused in range(WAIT_SECONDS):
					if not ept or not ept.running:
						break
					time.sleep(1)
				if ept and ept.running:
					raise ValueError(f"Event {ept.event.eventConfig.name} didn't stop after {WAIT_SECONDS} seconds - aborting")
				logger.debug("Successfully canceled event '%s' of type %s", ept.event.eventConfig.name, ept.event.eventConfig.actionType)

				try:
					cache_service = self.getCacheService()
					logger.debug("Got config_service with state: %s - marking dirty", cache_service.getConfigCacheState())
					# mark cache as dirty when bypassing cache mechanism for installation
					cache_service.setConfigCacheFaulty()
				except RuntimeError as err:
					logger.info("Could not mark config service cache dirty: %s", err, exc_info=True)

	def processEvent(self, event: Event) -> None:
		logger.notice("Processing event %s", event)

		description = f"Event {event.eventConfig.getId()} occurred\n"
		description += "Config:\n"
		_config = event.eventConfig.getConfig()
		configKeys = list(_config.keys())
		configKeys.sort()
		for configKey in configKeys:
			description += f"{configKey}: {_config[configKey]}\n"

		logger.trace("check lock (ocd), currently %s -> locking if not True", self.eventLock.locked())
		# if triggered by Basic.py fire_event, lock is already acquired
		if not self.eventLock.locked():
			self.eventLock.acquire()

		try:
			timeline.addEvent(title=f"Event {event.eventConfig.getName()}", description=description, category="event_occurrence")
			# if processEvent is called through Event.fireEvent(), this check is already done
			# self.canProcessEvent(event)
			# A user login event should not cancel running non-login Event
			if event.eventConfig.actionType != "login":
				self.cancelOthersAndWaitUntilReady()
		except (ValueError, RuntimeError) as err:
			# skipping execution if event cannot be created
			logger.warning("Could not start event: %s", err, exc_info=True)
			logger.trace("release lock (ocd cannot process event)")
			self.eventLock.release()
			return
		try:
			logger.debug("Creating new ept (ocd)")
			eventProcessingThread = EventProcessingThread(self, event)

			self.createActionProcessorUser(recreate=False)
			with self._eptListLock:
				self._eventProcessingThreads.append(eventProcessingThread)
		finally:
			logger.trace("release lock (ocd)")
			self.eventLock.release()

		try:
			eventProcessingThread.start()
			eventProcessingThread.join()
			logger.notice("Done processing event %s", event)
		finally:
			with self._eptListLock:
				self._eventProcessingThreads.remove(eventProcessingThread)

				if not self._eventProcessingThreads:
					try:
						self.deleteActionProcessorUser()
					except Exception as err:
						logger.warning(err)

	def getEventProcessingThreads(self) -> list[EventProcessingThread]:
		with self._eptListLock:
			return self._eventProcessingThreads

	def getEventProcessingThread(self, sessionId: str) -> EventProcessingThread:
		with self._eptListLock:
			for ept in self._eventProcessingThreads:
				if int(ept.getSessionId()) == int(sessionId):
					return ept
		raise LookupError(f"Event processing thread for session {sessionId} not found")

	def processProductActionRequests(self, event: Event) -> None:
		logger.error("processProductActionRequests not implemented")

	def getCurrentActiveDesktopName(self, sessionId: str | None = None) -> str | None:
		if not RUNNING_ON_WINDOWS:
			return None

		if not ("opsiclientd_rpc" in config.getDict() and "command" in config.getDict()["opsiclientd_rpc"]):
			raise RuntimeError("opsiclientd_rpc command not defined")

		if sessionId is None:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()

		rpc = f'setCurrentActiveDesktopName("{sessionId}", System.getActiveDesktopName())'
		cmd = config.get("opsiclientd_rpc", "command") + ' "' + rpc.replace('"', '\\"') + '"'
		try:
			runCommandInSession(
				command=cmd, sessionId=sessionId, desktop="winlogon", waitForProcessEnding=True, timeoutSeconds=60, noWindow=True
			)
		except Exception as err:
			logger.error(err)

		desktop = self._currentActiveDesktopName.get(sessionId)
		if not desktop:
			logger.warning("Failed to get current active desktop name for session %s, using 'default'", sessionId)
			desktop = "default"
			self._currentActiveDesktopName[sessionId] = desktop
		logger.debug("Returning current active dektop name '%s' for session %s", desktop, sessionId)
		return desktop

	def switchDesktop(self, desktop: str, sessionId: int | None = None) -> None:
		if not ("opsiclientd_rpc" in config.getDict() and "command" in config.getDict()["opsiclientd_rpc"]):
			raise RuntimeError("opsiclientd_rpc command not defined")

		desktop = forceUnicode(desktop)
		if sessionId is None:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()
		sessionId = forceInt(sessionId)

		rpc = f"noop(System.switchDesktop('{desktop}'))"
		cmd = f'{config.get("opsiclientd_rpc", "command")} "{rpc}"'

		try:
			runCommandInSession(
				command=cmd, sessionId=sessionId, desktop=desktop, waitForProcessEnding=True, timeoutSeconds=60, noWindow=True
			)
		except Exception as err:
			logger.error(err)

	def systemShutdownInitiated(self) -> None:
		if not self.isRebootTriggered() and not self.isShutdownTriggered():
			# This shutdown was triggered by someone else
			# Reset shutdown/reboot requests to avoid reboot/shutdown on next boot
			logger.notice("Someone triggered a reboot or a shutdown => clearing reboot request")
			self.clearRebootRequest()

	def rebootMachine(self, waitSeconds: int = 3) -> None:
		self._isRebootTriggered = True
		if self._controlPipe:
			try:
				self._controlPipe.executeRpc("rebootTriggered", True)
			except Exception as err:
				logger.debug(err)
		self.clearRebootRequest()
		notify_posix_terminals(f"Rebooting in {waitSeconds} seconds")
		System.reboot(wait=waitSeconds)

	def shutdownMachine(self, waitSeconds: int = 3) -> None:
		self._isShutdownTriggered = True
		if self._controlPipe:
			try:
				self._controlPipe.executeRpc("shutdownTriggered", True)
			except Exception as err:
				logger.debug(err)
		self.clearShutdownRequest()
		notify_posix_terminals(f"Shutdown in {waitSeconds} seconds")
		System.shutdown(wait=waitSeconds)

	def isRebootTriggered(self) -> bool:
		if self._isRebootTriggered:
			return True
		return False

	def isShutdownTriggered(self) -> bool:
		if self._isShutdownTriggered:
			return True
		return False

	def clearRebootRequest(self) -> None:
		pass

	def clearShutdownRequest(self) -> None:
		pass

	def isRebootRequested(self) -> bool:
		return False

	def isShutdownRequested(self) -> bool:
		return False

	def isInstallationPending(self) -> bool:
		return state.get("installation_pending", False)

	def getNotifierCommand(self, skin_file: str | None = None, link_handling: str = "no") -> str:
		notifierCommand = config.get("opsiclientd_notifier", "command")
		if Path(config.get("opsiclientd_notifier", "motd_notifier")).exists():
			notifierCommand = config.get("opsiclientd_notifier", "motd_notifier") + " -l 6 -p %port% -i %id%"
		if not notifierCommand:
			raise RuntimeError("opsiclientd_notifier.command not defined")
		if skin_file:
			notifierCommand = f"{notifierCommand} -s {skin_file}"
		if link_handling != "no":  # cannot set --link-handling with lazarus notifier
			notifierCommand = f"{notifierCommand} --link-handling {link_handling}"
		return notifierCommand

	def getPopupPort(self) -> int:
		port = config.get("notification_server", "popup_port")
		if not port:
			raise RuntimeError("notification_server.popup_port not defined")
		return port

	def updateMOTD(
		self,
		device_message: str | None = None,
		device_message_valid_until: str | None = None,
		user_message: str | None = None,
		user_message_valid_until: str | None = None,
	) -> list[str]:
		sessions = System.getActiveSessionInformation()
		logger.debug("Found sessions: %s", sessions)
		host_id = config.get("global", "host_id")
		messages_shown: list[str] = []

		message_of_the_day_state: dict[str, Any] = state.get("message_of_the_day", {})
		if "last_user_message_hash" not in message_of_the_day_state:
			message_of_the_day_state["last_user_message_hash"] = {}

		if not device_message and not user_message:
			if not self._permanent_service_connection:
				logger.info("No permanent service connection available, cannot get message of the day")
				return []
			logger.info("Updating message of the day from service information")
			motd_configs = [
				"message_of_the_day.user.message",
				"message_of_the_day.user.message_valid_until",
				"message_of_the_day.device.message",
				"message_of_the_day.device.message_valid_until",
			]
			data = self._permanent_service_connection.service_client.jsonrpc("configState_getValues", [motd_configs, host_id])
			user_message = data[host_id].get(motd_configs[0], [""])[0]
			user_message_valid_until = data[host_id].get(motd_configs[1], [""])[0]
			user_message = data[host_id].get(motd_configs[2], [""])[0]
			user_message_valid_until = data[host_id].get(motd_configs[3], [""])[0]
		if not user_message_valid_until:
			user_message_valid_until = (datetime.now() + timedelta(days=1)).isoformat()
		if not device_message_valid_until:
			device_message_valid_until = (datetime.now() + timedelta(days=1)).isoformat()

		if sessions:  # show user message
			if not user_message:
				logger.info("Not showing user-specific message of the day, because it is empty")
			elif datetime.now() > datetime.fromisoformat(user_message_valid_until):  # Note: Assuming iso format!
				logger.info("Not showing user-specific message of the day, because it is not valid anymore")
			else:
				relevant_sessions = []
				for entry in sessions:
					if sha256string(user_message) == message_of_the_day_state.get("last_user_message_hash", {}).get(entry.get("UserName")):
						logger.info("Not showing user-specific message of the day, because it was already shown")
						continue
					relevant_sessions.append(entry)
				if relevant_sessions:
					logger.notice("Showing user-specific message of the day")
					self.showPopup(
						user_message,
						mode="replace",
						addTimestamp=False,
						link_handling="browser",
						sessions=[entry.get("SessionId") for entry in relevant_sessions],
					)
					messages_shown.append("user")
					for entry in relevant_sessions:
						message_of_the_day_state["last_user_message_hash"][entry.get("UserName")] = sha256string(user_message)

		# show device message
		if not device_message:
			logger.info("Not showing device-specific message of the day, because it is empty")
		elif datetime.now() > datetime.fromisoformat(device_message_valid_until):  # Note: Assuming iso format!
			logger.info("Not showing device-specific message of the day, because it is not valid anymore")
		elif sha256string(device_message) == message_of_the_day_state.get("last_device_message_hash"):
			logger.info("Not showing device-specific message of the day, because it was already shown")
		else:
			logger.notice("Showing device-specific message of the day")
			self.showPopup(device_message, mode="replace", addTimestamp=False, link_handling="no", sessions=sessions)
			message_of_the_day_state["last_device_message_hash"] = sha256string(device_message)
			messages_shown.append("device")
		state.set("message_of_the_day", message_of_the_day_state)
		return messages_shown

	def showPopup(
		self,
		message: str,
		mode: str = "prepend",
		addTimestamp: bool = True,
		displaySeconds: int = 0,
		link_handling: str = "no",
		sessions: list[str] | None = None,
	) -> None:
		if mode not in ("prepend", "append", "replace"):
			mode = "prepend"
		port = self.getPopupPort()
		notifierCommand = self.getNotifierCommand(skin_file=os.path.join("notifier", "popup.ini"), link_handling=link_handling)

		if addTimestamp:
			message = "=== " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n" + message

		with self._popupNotificationLock:
			if mode in ("prepend", "append") and self._popupNotificationServer and self._popupNotificationServer.isListening():
				# Already runnning
				try:
					for subject in self._popupNotificationServer.getSubjects():
						if subject.getId() == "message":
							if mode == "prepend":
								message = message + "\n\n" + subject.getMessage()
							elif mode == "append":
								message = subject.getMessage() + "\n\n" + message
							break
				except Exception as err:
					logger.warning(err, exc_info=True)

			self.hidePopup()

			popupSubject = MessageSubject(id="message")
			choiceSubject = ChoiceSubject(id="choice")
			popupSubject.setMessage(message)

			logger.notice("Starting popup message notification server on port %d", port)
			try:
				self._popupNotificationServer = NotificationServer(
					address="127.0.0.1", start_port=port, subjects=[popupSubject, choiceSubject]
				)
				assert self._popupNotificationServer, "Failed to create popup notification server"
				self._popupNotificationServer.daemon = True
				with log_context({"instance": "popup notification server"}):
					if not self._popupNotificationServer.start_and_wait(timeout=30):
						raise RuntimeError("Timed out while waiting for notification server")
			except Exception as err:
				logger.error("Failed to start notification server: %s", err)
				raise

			notifierCommand = notifierCommand.replace("%port%", str(self._popupNotificationServer.port)).replace("%id%", "popup")

			choiceSubject.setChoices([_("Close")])
			choiceSubject.setCallbacks([self.popupCloseCallback])

			sessions = sessions or System.getActiveSessionIds()
			desktops = ("default", "winlogon")
			if not sessions:
				sessions = [System.getActiveConsoleSessionId()]
				desktops = ("winlogon",)
			for sessionId in sessions:
				try:
					if RUNNING_ON_WINDOWS:
						for desktop in desktops:
							subprocess.Popen(
								notifierCommand,
								session_id=sessionId,
								session_env=(desktop == "default"),
								session_elevated=(desktop == "winlogon"),
								session_desktop=desktop,
							)
					else:
						runCommandInSession(command=notifierCommand, sessionId=sessionId, waitForProcessEnding=False)
				except Exception as err:
					logger.error("Failed to start popup message notifier app in session %s on desktop %s: %s", sessionId, desktop, err)

			# last popup decides end time (even if unlimited)
			if self._popupClosingThread and self._popupClosingThread.is_alive():
				self._popupClosingThread.stop()
			if displaySeconds > 0:
				logger.debug("displaying popup for %s seconds", displaySeconds)
				self._popupClosingThread = PopupClosingThread(self, time.time() + displaySeconds)
				self._popupClosingThread.start()

	def hidePopup(self) -> None:
		if self._popupNotificationServer:
			try:
				logger.info("Stopping popup message notification server")

				self._popupNotificationServer.stop(stopReactor=False)
			except Exception as err:
				logger.error("Failed to stop popup notification server: %s", err)

	def popupCloseCallback(self, choiceSubject: ChoiceSubject) -> None:
		self.hidePopup()

	def collectLogfiles(self, types: list[str] | None = None, max_age_days: int | None = None, timeline_db: bool = True) -> Path:
		now = datetime.now().timestamp()
		type_patterns = []
		types = types or []
		if not types:
			type_patterns.append(re.compile(r".*\.log"))
		for stem_type in types:
			type_patterns.append(re.compile(rf"{stem_type}[_0-9]*\.log"))

		def collect_matching_files(path: Path, result_path: Path, patterns: list[re.Pattern], max_age_days: int | None) -> None:
			for content in path.iterdir():
				if content.is_file() and any((re.match(pattern, content.name) for pattern in patterns)):
					if not max_age_days or now - content.lstat().st_mtime < int(max_age_days) * 3600 * 24:
						if not result_path.is_dir():
							result_path.mkdir()
						shutil.copy2(content, result_path)  # preserve metadata

				if content.is_dir():
					collect_matching_files(content, result_path / content.name, patterns, max_age_days)

		filename = f"logs-{config.get('global', 'host_id')}-{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}"
		outfile = Path(config.get("control_server", "files_dir")) / filename
		compression = "zip"
		with tempfile.TemporaryDirectory() as tempdir:
			tempdir_path = Path(tempdir) / filename
			tempdir_path.mkdir()
			logger.info("Collecting log files to %s", tempdir_path)
			collect_matching_files(Path(config.get("global", "log_dir")), tempdir_path, type_patterns, max_age_days)
			if timeline_db:
				db_path = Path(config.get("global", "timeline_db"))
				if db_path.exists():
					shutil.copy2(db_path, tempdir_path)
			logger.info("Writing zip archive %s", outfile)
			shutil.make_archive(str(outfile), compression, root_dir=str(tempdir_path.parent), base_dir=tempdir_path.name)
		return outfile.parent / (outfile.name + f".{compression}")


class PopupClosingThread(threading.Thread):
	def __init__(self, opsiclientd: Opsiclientd, seconds: float) -> None:
		super().__init__()
		self.opsiclientd = opsiclientd
		self.seconds = seconds
		self.stopped = False

	def stop(self) -> None:
		self.stopped = True

	def run(self) -> None:
		while not self.stopped:
			time.sleep(1)
			if time.time() > self.seconds:
				break
		if not self.stopped:
			logger.debug("hiding popup window")
			self.opsiclientd.hidePopup()


class WaitForGUI(EventListener):
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		self._opsiclientd = opsiclientd
		self._guiStarted = threading.Event()
		self._should_stop = False
		ec = GUIStartupEventConfig("wait_for_gui")
		eventGenerator = EventGeneratorFactory(self._opsiclientd, ec)
		eventGenerator.addEventConfig(ec)
		eventGenerator.addEventListener(self)
		eventGenerator.start()

	def stop(self) -> None:
		self._should_stop = True
		self._guiStarted.set()

	def processEvent(self, event: Event) -> None:
		logger.trace("check lock (ocd), currently %s -> locking if not True", self._opsiclientd.eventLock.locked())
		# if triggered by Basic.py fire_event, lock is already acquired
		if not self._opsiclientd.eventLock.locked():
			self._opsiclientd.eventLock.acquire()
		try:
			logger.info("GUI started")
			self._guiStarted.set()
		finally:
			logger.trace("release lock (WaitForGUI)")
			self._opsiclientd.eventLock.release()

	def wait(self, timeout: float | None = None) -> None:
		self._guiStarted.wait(timeout)
		if self._should_stop:
			return
		if not self._guiStarted.is_set():
			logger.warning("Timed out after %d seconds while waiting for GUI", timeout)

	def canProcessEvent(self, event: Event, can_cancel: bool = False) -> bool:
		# WaitForGUI should handle all Events
		return True
