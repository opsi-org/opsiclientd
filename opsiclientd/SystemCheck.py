# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Platform check
"""

import platform

RUNNING_ON_WINDOWS = platform.system().lower() == "windows"
RUNNING_ON_LINUX = platform.system().lower() == "linux"
RUNNING_ON_DARWIN = RUNNING_ON_MACOS = platform.system().lower() == "darwin"
