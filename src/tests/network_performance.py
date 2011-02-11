# -*- coding: utf-8 -*-
"""
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2011 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as
   published by the Free Software Foundation.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   
   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Jan Schneider <j.schneider@uib.de>
   @license: GNU General Public License version 2
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

