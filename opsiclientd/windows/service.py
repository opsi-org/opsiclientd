# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

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

import time
import socket
import threading
import win32event
import servicemanager
import win32service
import win32serviceutil

import opsicommon.logging
from opsicommon.logging import logger, logging_config, LOG_NONE

class OpsiclientdService(win32serviceutil.ServiceFramework):
	_svc_name_ = "opsiclientd"
	_svc_display_name_ = "opsiclientd"
	_svc_description_ = "opsi client daemon"

	def __init__(self, args):
		"""
		Initialize service and create stop event
		"""
		self.opsiclientd = None
		try:
			logger.debug("OpsiclientdService initiating")
			win32serviceutil.ServiceFramework.__init__(self, args)
			self._stopEvent = win32event.CreateEvent(None, 0, 0, None)
			socket.setdefaulttimeout(60)
			logger.debug("OpsiclientdService initiated")
		except Exception as e:
			logger.error(e, exc_info=True)
			raise
	
	def ReportServiceStatus(self, serviceStatus, waitHint=5000, win32ExitCode=0, svcExitCode=0):
		# Wrapping because ReportServiceStatus sometimes lets windows
		# report a crash of opsiclientd (python 2.6.5) invalid handle
		try:
			logger.debug("Reporting service status: %s", serviceStatus)
			win32serviceutil.ServiceFramework.ReportServiceStatus(
				self,
				serviceStatus,
				waitHint=waitHint,
				win32ExitCode=win32ExitCode,
				svcExitCode=svcExitCode
			)
		except Exception as e:
			logger.error("Failed to report service status %s: %s", serviceStatus, e)

	def SvcInterrogate(self):
		logger.notice("Handling interrogate request")
		# Assume we are running, and everyone is happy.
		self.ReportServiceStatus(win32service.SERVICE_RUNNING)

	def SvcStop(self):
		"""
		Gets called from windows to stop service
		"""
		logger.notice("Handling stop request")
		self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
		win32event.SetEvent(self._stopEvent)
		
	def SvcShutdown(self):
		"""
		Gets called from windows on system shutdown
		"""
		logger.notice("Handling shutdown request")
		self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
		if self.opsiclientd:
			self.opsiclientd.systemShutdownInitiated()
		win32event.SetEvent(self._stopEvent)

	def SvcRun(self):
		"""
		Gets called from windows to start service
		"""
		try:
			logger.notice("Handling start request")
			startTime = time.time()
			
			# Write to event log
			servicemanager.LogMsg(
				servicemanager.EVENTLOG_INFORMATION_TYPE,
				servicemanager.PYS_SERVICE_STARTED,
				(self._svc_name_, '')
			)
			
			self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
			self.ReportServiceStatus(win32service.SERVICE_RUNNING)
			logger.debug("Took %0.2f seconds to report service running status", (time.time() - startTime))

			from .opsiclientd import opsiclientd_factory
			self.opsiclientd = opsiclientd_factory()
			self.opsiclientd.start()

			# Wait for stop event
			win32event.WaitForSingleObject(self._stopEvent, win32event.INFINITE)
			
			# Shutdown opsiclientd
			self.opsiclientd.stop()
			self.opsiclientd.join(15)

			logger.notice("opsiclientd stopped")
			servicemanager.LogMsg(
				servicemanager.EVENTLOG_INFORMATION_TYPE,
				servicemanager.PYS_SERVICE_STOPPED,
				(self._svc_name_, '')
			)
			for thread in threading.enumerate():
				logger.notice("Running thread after stop: %s", thread)
		except Exception as e:
			logger.critical("opsiclientd crash", exc_info=True)


def start_service():
	with opsicommon.logging.log_context({'instance', 'opsiclientd'}):
		logger.essential("opsiclientd service start")
		#logger.debug(os.environ)
		servicemanager.Initialize()
		servicemanager.PrepareToHostSingle(OpsiclientdService)
		servicemanager.StartServiceCtrlDispatcher()

def handle_commandline():
	win32serviceutil.HandleCommandLine(OpsiclientdService)
