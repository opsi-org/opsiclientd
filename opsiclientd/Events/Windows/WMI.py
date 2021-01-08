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
Handling of WMI queries with events

:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import threading
import time

from OPSI.Logger import Logger

from opsiclientd.Events.Basic import EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = ['WMIEventConfig', 'WMIEventGenerator']

logger = Logger()


class WMIEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.wql = str(conf.get('wql', ''))


class WMIEventGenerator(EventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		EventGenerator.__init__(self, opsiclientd, eventConfig)
		self._wql = self._generatorConfig.wql
		self._watcher = None

	def initialize(self):
		if self._opsiclientd.is_stopping():
			return

		if not self._wql:
			return

		from opsiclientd.windows.opsiclientd import importWmiAndPythoncom # pylint: disable=import-outside-toplevel
		(wmi, pythoncom) = importWmiAndPythoncom()
		pythoncom.CoInitialize()
		max_attempts = 10
		for attempt in range(1, 100):
			try:
				logger.debug("Creating wmi object")
				con = wmi.WMI(privileges=["Security"])
				logger.info("Watching for wql: %s", self._wql)
				self._watcher = con.watch_for(raw_wql=self._wql, wmi_class='')
				break
			except Exception as err: # pylint: disable=broad-except
				if self._stopped:
					return
				logger.warning("Failed to create wmi watcher (wql=%s): %s", self._wql, err, exc_info=True)
				if attempt >= max_attempts:
					raise
				for i in range(3):  # pylint: disable=unused-variable
					if self._stopped:
						return
					time.sleep(1)
		logger.debug("Initialized")

	def getNextEvent(self):
		if self._opsiclientd.is_stopping():
			return None

		if not self._watcher:
			logger.info("Nothing to watch for")
			self._event = threading.Event()
			self._event.wait()
			return None

		wqlResult = None
		from opsiclientd.windows.opsiclientd import importWmiAndPythoncom # pylint: disable=import-outside-toplevel
		(wmi, _pythoncom) = importWmiAndPythoncom()
		while not self._stopped:
			try:
				wqlResult = self._watcher(timeout_ms=500)
				break
			except wmi.x_wmi_timed_out:
				continue

		if wqlResult:
			eventInfo = {}
			for prop in wqlResult.properties:
				value = getattr(wqlResult, prop)
				if isinstance(value, tuple):
					eventInfo[prop] = []
					for val in value:
						eventInfo[prop].append(val)
				else:
					eventInfo[prop] = value

			return self.createEvent(eventInfo)

	def cleanup(self):
		if self._opsiclientd.is_stopping():
			return

		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info("Event generator '%s' cleaning up in %d seconds", self, waitTime)
			time.sleep(waitTime)

		try:
			from opsiclientd.windows.opsiclientd import importWmiAndPythoncom # pylint: disable=import-outside-toplevel
			(_wmi, pythoncom) = importWmiAndPythoncom()
			pythoncom.CoUninitialize()
		except ImportError:
			# Probably not running on Windows.
			pass
