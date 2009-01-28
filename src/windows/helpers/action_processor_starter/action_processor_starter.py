# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =       action_processor_starter        =
   = = = = = = = = = = = = = = = = = = = = =
   
   action_processor_starter is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2008 uib GmbH
   
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

__version__ = '0.1'

# Imports
import sys, os

from OPSI.Logger import *
from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend

#for i in range(len(sys.argv)):
#	print "%d: %s" % (i, sys.argv[i])

if (len(sys.argv) != 12):
	print "Usage: %s <hostId> <hostKey> <controlServerPort> <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <username> <password> <actionProcessorDesktop> <actionProcessorCommand>" % os.path.basename(sys.argv[0])
	sys.exit(1)
(hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, username, password, actionProcessorDesktop, actionProcessorCommand) = sys.argv[1:]

logger = Logger()
logger.setConsoleLevel(LOG_NONE)
logger.setLogFile(logFile)
logger.setFileLevel(int(logLevel))
logger.setFileFormat('[%l] [%D] [' + os.path.basename(sys.argv[0]) + ']  %M  (%F|%N)')

logger.confidential("Called with arguments: %s" % ', '.join((hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, username, password, actionProcessorCommand)) )

be = JSONRPCBackend(username = hostId, password = hostKey, address = 'https://localhost:%s/rpc' % controlServerPort)

imp = None
depotShareMounted = False
try:
	imp = System.Impersonate(username, password, desktop=actionProcessorDesktop)
	imp.start(logonType = 'NEW_CREDENTIALS')
	
	logger.notice("Mounting depot share %s" % depotRemoteUrl)
	be.setStatusMessage("Mounting depot share %s" % depotRemoteUrl)
	
	System.mount(depotRemoteUrl, depotDrive, username=username, password=password)
	depotShareMounted = True
	
	logger.notice("Starting action processor")
	be.setStatusMessage("Starting action processor")
	
	imp.runCommand(actionProcessorCommand)
	
	logger.notice("Action processor ended")
	be.setStatusMessage("Action processor ended")
	
except Exception, e:
	logger.logException(e)
	error = "Failed to process action requests: %s" % e
	be.setStatusMessage(error)
	logger.error(error)
	
if depotShareMounted:
	try:
		logger.notice("Unmounting depot share")
		System.umount(depotDrive)
	except:
		pass
if imp:
	try:
		imp.end()
	except:
		pass











