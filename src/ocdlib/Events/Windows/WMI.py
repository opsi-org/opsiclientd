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
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import threading
import time

from OPSI.Logger import Logger
from OPSI.Types import forceUnicode

from ..Basic import EventGenerator
from ocdlib.EventConfiguration import EventConfig

__all__ = ['WMIEventConfig', 'WMIEventGenerator']

logger = Logger()


class WMIEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.wql = unicode(conf.get('wql', ''))


class WMIEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
		self._wql = self._generatorConfig.wql
		self._watcher = None

	def initialize(self):
		if not self._wql:
			return

		from ocdlib.Windows import importWmiAndPythoncom
		(wmi, pythoncom) = importWmiAndPythoncom()
		pythoncom.CoInitialize()
		while not self._watcher:
			try:
				logger.debug(u"Creating wmi object")
				c = wmi.WMI(privileges=["Security"])
				logger.info(u"Watching for wql: %s" % self._wql)
				self._watcher = c.watch_for(raw_wql=self._wql, wmi_class='')
			except Exception as e:
				try:
					logger.warning(u"Failed to create wmi watcher: %s" % forceUnicode(e))
				except Exception:
					logger.warning(u"Failed to create wmi watcher, failed to log exception")
				time.sleep(1)
		logger.debug(u"Initialized")

	def getNextEvent(self):
		if not self._watcher:
			logger.info(u"Nothing to watch for")
			self._event = threading.Event()
			self._event.wait()
			return None

		wqlResult = None
		from ocdlib.Windows import importWmiAndPythoncom
		(wmi, pythoncom) = importWmiAndPythoncom()
		while not self._stopped:
			try:
				wqlResult = self._watcher(timeout_ms=500)
				break
			except wmi.x_wmi_timed_out:
				continue

		if wqlResult:
			eventInfo = {}
			for p in wqlResult.properties:
				value = getattr(wqlResult, p)
				if isinstance(value, tuple):
					eventInfo[p] = []
					for v in value:
						eventInfo[p].append(v)
				else:
					eventInfo[p] = value

			return self.createEvent(eventInfo)

	def cleanup(self):
		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info(u"Event generator '%s' cleaning up in %d seconds" % (self, waitTime))
			time.sleep(waitTime)

		try:
			from ocdlib.Windows import importWmiAndPythoncom
			(wmi, pythoncom) = importWmiAndPythoncom()
			pythoncom.CoUninitialize()
		except ImportError:
			# Probably not running on Windows.
			pass
