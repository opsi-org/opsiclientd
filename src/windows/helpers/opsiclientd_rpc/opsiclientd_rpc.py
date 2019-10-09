# -*- coding: utf-8 -*-

# opsiclientd_rpc is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2008-2018 uib GmbH <info@uib.de>

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
Helper to make RPC-calls against opsiclientd from the commandline.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:license: GNU Affero General Public License version 3
"""

import locale
import os
import sys

from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Logger import Logger, LOG_DEBUG

# Do not remove this import, it's needed by using this module from CLI
from OPSI import System

__version__ = '4.1.1.2'

logger = Logger()

encoding = locale.getpreferredencoding()


def main():
	argv = [unicode(arg, encoding) for arg in sys.argv]

	if len(argv) < 5:
		print u"Usage: %s <username> <password> <port> <rpc> [debug_logfile]" % os.path.basename(argv[0])
		sys.exit(1)

	(username, password, port, rpc) = argv[1:5]
	logFile = None
	if len(argv) > 5:
		logFile = argv[5]
		logger.setLogFile(logFile)
		logger.setFileLevel(LOG_DEBUG)

	address = u'https://localhost:%s/opsiclientd' % port

	try:
		with JSONRPCBackend(username=username, password=password, address=address) as backend:
			logger.notice(u"Executing: %s" % rpc)
			exec 'backend.%s' % rpc
	except Exception as error:
		logger.logException(error)
		sys.exit(1)


if __name__ == '__main__':
	main()
