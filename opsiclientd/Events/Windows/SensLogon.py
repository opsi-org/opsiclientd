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
ISensLogon generator.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import time

from OPSI.Logger import Logger

from ..Basic import EventGenerator

__all__ = ['SensLogonEventGenerator']

logger = Logger()


class SensLogonEventGenerator(EventGenerator):

	def initialize(self):
		EventGenerator.initialize(self)

		logger.notice(u'Registring ISensLogon')

		from opsiclientd.Windows import importWmiAndPythoncom, SensLogon

		(wmi, pythoncom) = importWmiAndPythoncom(
			importWmi=False,
			importPythoncom=True
		)
		pythoncom.CoInitialize()

		sl = SensLogon(self.callback)
		sl.subscribe()

	def getNextEvent(self):
		from opsiclientd.Windows import importWmiAndPythoncom
		(wmi, pythoncom) = importWmiAndPythoncom(
			importWmi=False,
			importPythoncom=True
		)
		pythoncom.PumpMessages()
		logger.info(u"Event generator '%s' now deactivated after %d event occurrences" % (self, self._eventsOccured))
		self.cleanup()

	def callback(self, eventType, *args):
		logger.debug(u"SensLogonEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))

	def stop(self):
		EventGenerator.stop(self)
		# Post WM_QUIT
		import win32api
		win32api.PostThreadMessage(self._threadId, 18, 0, 0)

	def cleanup(self):
		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing
			# exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info(u"Event generator '%s' cleaning up in %d seconds" % (self, waitTime))
			time.sleep(waitTime)

		from opsiclientd.Windows import importWmiAndPythoncom
		(wmi, pythoncom) = importWmiAndPythoncom(
			importWmi=False,
			importPythoncom=True
		)
		pythoncom.CoUninitialize()
