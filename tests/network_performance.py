# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
The opsiclientd itself.
This is where all the parts come together.
"""

from __future__ import print_function

import sys
import time

from OPSI.System import getDefaultNetworkInterfaceName, NetworkPerformanceCounter

try:
	networkPerformanceCounter = NetworkPerformanceCounter(getDefaultNetworkInterfaceName())
	try:
		while True:
			inrate = networkPerformanceCounter.getBytesInPerSecond()
			outrate = networkPerformanceCounter.getBytesOutPerSecond()
			print(f"in: {(inrate/1024):0.2f} kByte/s, out: {(outrate/1024):0.2f} kByte/s")
			time.sleep(1)
	finally:
		networkPerformanceCounter.stop()
except Exception as err:
	print(f"Error: {err}", file=sys.stderr)
