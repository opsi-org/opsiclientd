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
Daemon Shutdown Events

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

from .Basic import Event, EventGenerator
from ocdlib.EventConfiguration import EventConfig

__all__ = [
    'EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN', 'DaemonShutdownEvent',
    'DaemonShutdownEventConfig', 'DaemonShutdownEventGenerator'
]

EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN = u'daemon shutdown'


class DaemonShutdownEventConfig(EventConfig):
    def setConfig(self, conf):
        EventConfig.setConfig(self, conf)
        self.maxRepetitions = 0


class DaemonShutdownEventGenerator(EventGenerator):
    def __init__(self, eventConfig):
        EventGenerator.__init__(self, eventConfig)

    def createEvent(self, eventInfo={}):
        eventConfig = self.getEventConfig()
        if not eventConfig:
            return None

        return DaemonShutdownEvent(
            eventConfig=eventConfig,
            eventInfo=eventInfo
        )


class DaemonShutdownEvent(Event):
    def __init__(self, eventConfig, eventInfo={}):
        Event.__init__(self, eventConfig, eventInfo)
