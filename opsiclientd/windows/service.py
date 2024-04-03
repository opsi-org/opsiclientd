# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.windows.service
"""

from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING, Any, Iterable, Sequence

import servicemanager

# pyright: reportMissingImports=false
import win32event
import win32service
import win32serviceutil
from opsicommon.logging import get_logger, log_context

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

PBT_APMSUSPEND = 0x4  # https://learn.microsoft.com/en-us/windows/win32/power/pbt-apmsuspend
PBT_APMRESUMEAUTOMATIC = 0x12  # https://learn.microsoft.com/en-us/windows/win32/power/pbt-apmresumeautomatic
PBT_APMRESUMESUSPEND = 0x7  # https://learn.microsoft.com/en-us/windows/win32/power/pbt-apmresumesuspend

logger = get_logger()


class OpsiclientdService(win32serviceutil.ServiceFramework):
	_svc_name_ = "opsiclientd"
	_svc_display_name_ = "opsiclientd"
	_svc_description_ = "opsi client daemon"

	def __init__(self, args: Iterable[str]) -> None:
		"""
		Initialize service and create stop event
		"""
		self.opsiclientd: Opsiclientd | None = None
		try:
			logger.debug("OpsiclientdService initiating")
			win32serviceutil.ServiceFramework.__init__(self, args)
			self._stopEvent = win32event.CreateEvent(None, 0, 0, None)
			socket.setdefaulttimeout(60)
			logger.debug("OpsiclientdService initiated")
		except Exception as err:
			logger.error(err, exc_info=True)
			raise

	def GetAcceptedControls(self) -> int:
		rc = win32serviceutil.ServiceFramework.GetAcceptedControls(self)  # type: ignore[no-untyped-call]
		rc |= win32service.SERVICE_ACCEPT_POWEREVENT
		return rc  # additionally accept SERVICE_ACCEPT_POWEREVENT

	def ReportServiceStatus(self, serviceStatus: int, waitHint: int = 5000, win32ExitCode: int = 0, svcExitCode: int = 0) -> None:
		# Wrapping because ReportServiceStatus sometimes lets windows
		# report a crash of opsiclientd (python 2.6.5) invalid handle
		try:
			logger.debug("Reporting service status: %s", serviceStatus)
			win32serviceutil.ServiceFramework.ReportServiceStatus(
				self, serviceStatus, waitHint=waitHint, win32ExitCode=win32ExitCode, svcExitCode=svcExitCode
			)
		except Exception as err:
			logger.error("Failed to report service status %s: %s", serviceStatus, err)

	# All extra events are sent via SvcOtherEx (SvcOther remains as a function taking only the first args for backwards compat)
	def SvcOtherEx(self, control: int, event_type: str, data: list[Any]) -> None:
		logger.debug("Got Ex event: %s (%s - %s)", control, event_type, data)
		# https://stackoverflow.com/questions/47942716/how-to-detect-wake-up-from-sleep-mode-in-windows-service
		# https://github.com/mhammond/pywin32/blob/main/win32/Demos/service/serviceEvents.py
		if control == win32service.SERVICE_CONTROL_POWEREVENT:
			if event_type == PBT_APMSUSPEND:
				logger.info("Caught Event for sleep")
			elif event_type == PBT_APMRESUMEAUTOMATIC:
				logger.info("Caught Event for wakeup")

	def SvcInterrogate(self) -> None:
		logger.notice("Handling interrogate request")
		# Assume we are running, and everyone is happy.
		self.ReportServiceStatus(win32service.SERVICE_RUNNING)

	def SvcStop(self) -> None:
		"""
		Gets called from windows to stop service
		"""
		logger.notice("Handling stop request")
		self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
		win32event.SetEvent(self._stopEvent)

	def SvcShutdown(self) -> None:
		"""
		Gets called from windows on system shutdown
		"""
		logger.notice("Handling shutdown request")
		self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
		if self.opsiclientd:
			self.opsiclientd.systemShutdownInitiated()
		win32event.SetEvent(self._stopEvent)

	def SvcRun(self) -> None:
		"""
		Gets called from windows to start service
		"""
		try:
			logger.notice("Handling start request")
			assert self.opsiclientd
			startTime = time.time()

			self.ReportServiceStatus(win32service.SERVICE_RUNNING)
			logger.debug("Took %0.2f seconds to report service running status", (time.time() - startTime))

			# Write to event log
			servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ""))

			from .opsiclientd import opsiclientd_factory

			self.opsiclientd = opsiclientd_factory()
			self.opsiclientd.start()

			# Wait for stop event
			win32event.WaitForSingleObject(self._stopEvent, win32event.INFINITE)

			# Shutdown opsiclientd
			self.opsiclientd.stop()
			self.opsiclientd.join(15)

			logger.notice("opsiclientd stopped")
			try:
				self.ReportServiceStatus(win32service.SERVICE_STOPPED)
				servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STOPPED, (self._svc_name_, ""))
			except Exception as err:
				# Errors can occur if windows is shutting down
				logger.info(err, exc_info=True)
			for thread in threading.enumerate():
				logger.notice("Running thread after stop: %s", thread)
		except Exception as err:
			logger.critical("opsiclientd crash %s", err, exc_info=True)


def start_service() -> None:
	with log_context({"instance": "opsiclientd"}):
		logger.essential("opsiclientd service start")
		servicemanager.Initialize()
		servicemanager.PrepareToHostSingle(OpsiclientdService)
		servicemanager.StartServiceCtrlDispatcher()  # type: ignore[no-untyped-call]


def handle_commandline(argv: Sequence[str] | None = None) -> None:
	win32serviceutil.HandleCommandLine(OpsiclientdService, argv=argv)
