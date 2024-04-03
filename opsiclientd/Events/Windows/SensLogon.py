# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
ISensLogon generator.
"""

import time
from typing import Any

from opsicommon.logging import get_logger

from opsiclientd.Events.Basic import EventGenerator

__all__ = ["SensLogonEventGenerator"]

logger = get_logger()


class SensLogonEventGenerator(EventGenerator):
	def initialize(self) -> None:
		EventGenerator.initialize(self)

		logger.notice("Registring ISensLogon")

		from opsiclientd.windows import SensLogon, importWmiAndPythoncom

		(_wmi, pythoncom) = importWmiAndPythoncom(importWmi=False, importPythoncom=True)
		assert pythoncom
		pythoncom.CoInitialize()

		sl = SensLogon(self.callback)
		sl.subscribe()

	def getNextEvent(self) -> None:
		from opsiclientd.windows import importWmiAndPythoncom

		(_wmi, pythoncom) = importWmiAndPythoncom(importWmi=False, importPythoncom=True)
		assert pythoncom
		pythoncom.PumpMessages()
		logger.info("Event generator '%s' now deactivated after %d event occurrences", self, self._eventsOccured)
		self.cleanup()

	def callback(self, eventType: str, *args: Any) -> None:
		logger.debug("SensLogonEventGenerator event callback: eventType '%s', args: %s", eventType, args)

	def stop(self) -> None:
		EventGenerator.stop(self)

	def cleanup(self) -> None:
		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing
			# exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info("Event generator '%s' cleaning up in %d seconds", self, waitTime)
			time.sleep(waitTime)

		from opsiclientd.windows import importWmiAndPythoncom

		(_wmi, pythoncom) = importWmiAndPythoncom(importWmi=False, importPythoncom=True)
		assert pythoncom
		pythoncom.CoUninitialize()
