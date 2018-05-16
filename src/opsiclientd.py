#! /usr/bin/env python
# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

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
Opsiclientd.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import print_function

import os
import sys

from OPSI.Logger import LOG_WARNING, Logger

if os.name == 'nt':
	from ocdlib.Windows import OpsiclientdInit
elif os.name == 'posix':
	from ocdlib.Posix import OpsiclientdInit

logger = Logger()

if __name__ == "__main__":
	moduleName = u' %-30s' % (u'opsiclientd')
	logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)')
	logger.setConsoleLevel(LOG_WARNING)

	try:
		OpsiclientdInit()
	except Exception as exception:
		logger.logException(exception)
		print(u"ERROR: {}".format(unicode(exception)), file=sys.stderr)
		sys.exit(1)
