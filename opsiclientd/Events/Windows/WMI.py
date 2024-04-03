# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Handling of WMI queries with events
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

from opsicommon.logging import logger

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

__all__ = ["WMIEventConfig", "WMIEventGenerator"]


class WMIEventConfig(EventConfig):
	def setConfig(self, conf: dict[str, Any]) -> None:
		EventConfig.setConfig(self, conf)
		self.wql = str(conf.get("wql", ""))


class WMIEventGenerator(EventGenerator):
	_generatorConfig: WMIEventConfig

	def __init__(self, opsiclientd: Opsiclientd, generatorConfig: WMIEventConfig) -> None:
		EventGenerator.__init__(self, opsiclientd, generatorConfig)
		self._wql = self._generatorConfig.wql
		self._watcher = None

	def initialize(self) -> None:
		if self._opsiclientd.is_stopping():
			return

		if not self._wql:
			return

		from opsiclientd.windows import importWmiAndPythoncom

		(wmi, pythoncom) = importWmiAndPythoncom()
		assert wmi
		assert pythoncom
		pythoncom.CoInitialize()
		max_attempts = 10
		for attempt in range(1, 100):
			try:
				logger.debug("Creating wmi object")
				con = wmi.WMI(privileges=["Security"])
				logger.info("Watching for wql: %s", self._wql)
				self._watcher = con.watch_for(raw_wql=self._wql, wmi_class="")
				break
			except Exception as err:
				if self._stopped:
					return
				logger.warning("Failed to create wmi watcher (wql=%s): %s", self._wql, err, exc_info=True)
				if attempt >= max_attempts:
					raise
				for i in range(3):
					if self._stopped:
						return
					time.sleep(1)
		logger.debug("Initialized")

	def getNextEvent(self) -> Event | None:
		if self._opsiclientd.is_stopping():
			return None

		if not self._watcher:
			logger.info("Nothing to watch for")
			self._event = threading.Event()
			self._event.wait()
			return None

		wqlResult = None
		from opsiclientd.windows import importWmiAndPythoncom

		(wmi, _pythoncom) = importWmiAndPythoncom()
		while not self._stopped:
			try:
				wqlResult = self._watcher(timeout_ms=500)
				break
			except wmi.x_wmi_timed_out:
				continue
			except Exception:
				if self._opsiclientd.is_stopping():
					return None
				raise

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

	def cleanup(self) -> None:
		if self._opsiclientd.is_stopping():
			return

		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info("Event generator '%s' cleaning up in %d seconds", self, waitTime)
			time.sleep(waitTime)

		try:
			from opsiclientd.windows import importWmiAndPythoncom

			(_wmi, pythoncom) = importWmiAndPythoncom()
			assert pythoncom
			pythoncom.CoUninitialize()
		except ImportError:
			# Probably not running on Windows.
			pass
