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
:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import sys

from OPSI.Logger import LOG_DEBUG, Logger
from OPSI.Backend.JSONRPC import JSONRPCBackend
# Do not remove this import, it's needed by using this module from CLI
from OPSI import System

logger = Logger()

def main():
	logger.setLogFormat("[%l] [%D] [opsiclientd_rpc] %M   (%F|%N)")
	if len(sys.argv) < 5:
		print(f"Usage: {os.path.basename(sys.argv[0])} <username> <password> <port> <rpc> [debug_logfile]")
		sys.exit(1)

	(username, password, port, rpc) = sys.argv[1:5]
	if len(sys.argv) > 5:
		logger.setLogFile(sys.argv[5])
		logger.setFileLevel(LOG_DEBUG)

	address = f"https://localhost:{port}/opsiclientd"

	try:
		with JSONRPCBackend(username=username, password=password, address=address) as backend:
			logger.notice(f"Executing: {rpc}")
			exec(f"backend.{rpc}")
	except Exception as error:
		logger.logException(error)
		sys.exit(1)
