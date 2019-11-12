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
Events that get active once a system shuts down or restarts.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

from ..Basic import Event, EventGenerator
from .WMI import WMIEventConfig

__all__ = [
	'EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN', 'SystemShutdownEvent',
	'SystemShutdownEventConfig', 'SystemShutdownEventGenerator'
]

EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN = u'system shutdown'


class SystemShutdownEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.maxRepetitions = 0


class SystemShutdownEventGenerator(EventGenerator):
	pass


class SystemShutdownEvent(Event):
	pass
