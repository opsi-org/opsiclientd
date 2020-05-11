# -*- coding: utf-8 -*-
"""
opsiclientd_rpc

opsiclientd_rpc is part of the desktop management solution opsi
(open pc server integration) http://www.opsi.org

Copyright (C) 2010-2013 uib GmbH

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

@copyright: uib GmbH <info@uib.de>
@author: Jan Schneider <j.schneider@uib.de>
@author: Erol Ueluekmen <e.ueluekmen@uib.de>
@license: GNU General Public License version 2
"""
import codecs
import locale
import os
import sys

from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Logger import Logger, LOG_DEBUG
from OPSI import System


__version__ = '4.0.4.4'

logger = Logger()

# Workarround from https://stackoverflow.com/questions/878972/windows-cmd-encoding-change-causes-python-crash
# Problem with UTF-8 Beta-Mode of win10
codecs.register(lambda name: codecs.lookup('utf-8') if name == "cp65001" else None)

encoding = locale.getpreferredencoding()
argv = [unicode(arg, encoding) for arg in sys.argv]

if (len(argv) < 5):
   print u"Usage: %s <username> <password> <port> <rpc> [debug_logfile]" % os.path.basename(argv[0])
   sys.exit(1)

(username, password, port, rpc) = argv[1:5]
logFile = None
if (len(argv) > 5):
   logFile = argv[5]
   logger.setLogFile(logFile)
   logger.setFileLevel(LOG_DEBUG)
try:
   be = JSONRPCBackend(username=username, password=password, address=u'https://localhost:%s/opsiclientd' % port)
   logger.notice(u"Executing: %s" % rpc)
   exec 'be.%s' % rpc
   be.backend_exit()
except Exception, e:
   logger.logException(e)
   sys.exit(1)

sys.exit(0)