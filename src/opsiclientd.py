#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   opsi client daemon (opsiclientd)    =
   = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
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
import os

# OPSI imports
from OPSI.Logger import *


if (os.name == 'nt'):
	from ocdlib.Windows import *
if (os.name == 'posix'):
	from ocdlib.Posix import *

# Create logger instance
logger = Logger()
logger.setLogFormat(u'[%l] [%D]   %M     (%F|%N)')

if (__name__ == "__main__"):
	logger.setConsoleLevel(LOG_WARNING)
	exception = None
	
	debugLogFile = "c:\\tmp\\opsiclientd.log"
	f = open(debugLogFile, "w")
	f.write(u"--- Debug log started ---\r\n")
	f.close()
	try:
		logger.setLogFile(debugLogFile)
		logger.setFileLevel(LOG_CONFIDENTIAL)
		logger.log(1, u"Logger initialized", raiseException = True)
	except Exception, e:
		error = 'unkown error'
		try:
			error = str(e)
		except:
			pass
		f = open(debugLogFile, "a+")
		f.write("Failed to initialize logger: %s\r\n" % error)
		f.close()
	
	try:
		OpsiclientdInit()
		
	except SystemExit, e:
		pass
		
	except Exception, e:
		exception = e
	
	if exception:
		logger.logException(exception)
		print >> sys.stderr, u"ERROR:", unicode(exception)
		sys.exit(1)
	sys.exit(0)








