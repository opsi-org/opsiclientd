# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2011-2016 uib GmbH <info@uib.de>

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
The opsiclientd itself.
This is where all the parts come together.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:license: GNU Affero General Public License version 3
"""

import time, sys
from OPSI.System import getDefaultNetworkInterfaceName, NetworkPerformanceCounter

try:
	networkPerformanceCounter = NetworkPerformanceCounter(getDefaultNetworkInterfaceName())
	try:
		while True:
			inrate  = networkPerformanceCounter.getBytesInPerSecond()
			outrate = networkPerformanceCounter.getBytesOutPerSecond()
			print u"in: %0.2f kByte/s, out: %0.2f kByte/s" % ((inrate/1024), (outrate/1024))
			time.sleep(1)
	finally:
		networkPerformanceCounter.stop()
except Exception, e:
	print >> sys.stderr, u"Error: %s" % e

