# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =            opsiclientd_rpc            =
   = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd_rpc is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
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

__version__ = '4.0'

# Imports
import sys, os, locale

from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend

encoding = locale.getpreferredencoding()
argv = [ unicode(arg, encoding) for arg in sys.argv ]

if (len(argv) != 5):
	print u"Usage: %s <username> <password> <port> <rpc>" % os.path.basename(argv[0])
	sys.exit(1)

(username, password, port, rpc) = argv[1:]
try:
	be = JSONRPCBackend(username = username, password = password, address = u'https://localhost:%s/opsiclientd' % port)
	exec 'be.%s' % rpc
	be.backend_exit()
except:
	pass
sys.exit(0)

