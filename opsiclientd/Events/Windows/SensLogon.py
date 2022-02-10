# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
ISensLogon generator.
"""

import time

from opsicommon.logging import logger

from opsiclientd.Events.Basic import EventGenerator

__all__ = ['SensLogonEventGenerator']

class SensLogonEventGenerator(EventGenerator):

	def initialize(self):
		EventGenerator.initialize(self)

		logger.notice("Registring ISensLogon")

		from opsiclientd.windows import importWmiAndPythoncom, SensLogon # pylint: disable=import-outside-toplevel

		(_wmi, pythoncom) = importWmiAndPythoncom(
			importWmi=False,
			importPythoncom=True
		)
		pythoncom.CoInitialize()

		sl = SensLogon(self.callback)
		sl.subscribe()

	def getNextEvent(self):
		from opsiclientd.windows import importWmiAndPythoncom # pylint: disable=import-outside-toplevel
		(_wmi, pythoncom) = importWmiAndPythoncom(
			importWmi=False,
			importPythoncom=True
		)
		pythoncom.PumpMessages()
		logger.info("Event generator '%s' now deactivated after %d event occurrences", self, self._eventsOccured)
		self.cleanup()

	def callback(self, eventType, *args): # pylint: disable=no-self-use
		logger.debug("SensLogonEventGenerator event callback: eventType '%s', args: %s", eventType, args)

	def stop(self):
		EventGenerator.stop(self)

	def cleanup(self):
		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing
			# exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info("Event generator '%s' cleaning up in %d seconds", self, waitTime)
			time.sleep(waitTime)

		from opsiclientd.windows import importWmiAndPythoncom # pylint: disable=import-outside-toplevel
		(_wmi, pythoncom) = importWmiAndPythoncom(
			importWmi=False,
			importPythoncom=True
		)
		pythoncom.CoUninitialize()
