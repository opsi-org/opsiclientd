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
Timer events get active after a specified time.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import threading

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = ['TimerEvent', 'TimerEventConfig', 'TimerEventGenerator']


class TimerEventConfig(EventConfig):
	pass


class TimerEventGenerator(EventGenerator):

	def getNextEvent(self):
		self._event = threading.Event()
		if self._generatorConfig.interval > 0:
			self._event.wait(self._generatorConfig.interval)
			if self._stopped:
				return None
			return self.createEvent()
		self._event.wait()
		return None

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return TimerEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class TimerEvent(Event): # pylint: disable=too-few-public-methods
	pass
