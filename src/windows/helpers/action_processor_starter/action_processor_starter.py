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

__version__ = '3.5'

# Imports
import sys, os, locale

from OPSI.Logger import *
from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend

encoding = locale.getpreferredencoding()
argv = [ unicode(arg, encoding) for arg in sys.argv ]

if (len(argv) != 16):
	print u"Usage: %s <hostId> <hostKey> <controlServerPort> <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword> <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout> <runAsUser> <runAsPassword>" % os.path.basename(argv[0])
	sys.exit(1)

(hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, depotServerUsername, depotServerPassword, sessionId, actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout, runAsUser, runAsPassword) = argv[1:]

logger = Logger()
if hostKey:
	logger.addConfidentialString(hostKey)
if depotServerPassword:
	logger.addConfidentialString(depotServerPassword)
if runAsPassword:
	logger.addConfidentialString(runAsPassword)

logger.setConsoleLevel(LOG_NONE)
logger.setLogFile(logFile)
logger.setFileLevel(int(logLevel))
logger.setFileFormat(u'[%l] [%D] [' + os.path.basename(argv[0]) + u']   %M  (%F|%N)')

logger.debug(u"Called with arguments: %s" % u', '.join((hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, depotServerUsername, depotServerPassword, sessionId, actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout, runAsUser, runAsPassword)) )

actionProcessorTimeout = int(actionProcessorTimeout)

imp = None
depotShareMounted = False
be = None

try:
	be = JSONRPCBackend(username = hostId, password = hostKey, address = u'https://localhost:%s/opsiclientd' % controlServerPort)
	
	if runAsUser:
		logger.info(u"Impersonating user '%s'" % runAsUser)
		imp = System.Impersonate(username = runAsUser, password = runAsPassword, desktop = actionProcessorDesktop)
		imp.start(logonType = u'INTERACTIVE', newDesktop = True)
	
	else:
		logger.info(u"Impersonating network account '%s'" % depotServerUsername)
		imp = System.Impersonate(username = depotServerUsername, password = depotServerPassword, desktop = actionProcessorDesktop)
		imp.start(logonType = u'NEW_CREDENTIALS')
		
	if (depotRemoteUrl.split(u'/')[2] != u'localhost'):
		logger.notice(u"Mounting depot share %s" % depotRemoteUrl)
		be.setStatusMessage(sessionId, u"Mounting depot share %s" % depotRemoteUrl)
		
		if runAsUser:
			System.mount(depotRemoteUrl, depotDrive, username = depotServerUsername, password = depotServerPassword)
		else:
			System.mount(depotRemoteUrl, depotDrive)
		depotShareMounted = True
	
	logger.notice(u"Starting action processor")
	be.setStatusMessage(sessionId, u"Starting action processor")
	
	imp.runCommand(actionProcessorCommand, timeoutSeconds = actionProcessorTimeout)
	
	logger.notice(u"Action processor ended")
	be.setStatusMessage(sessionId, u"Action processor ended")
	
except Exception, e:
	logger.logException(e)
	error = u"Failed to process action requests: %s" % e
	if be:
		try:
			be.setStatusMessage(sessionId, error)
		except:
			pass
	logger.error(error)
	
if depotShareMounted:
	try:
		logger.notice(u"Unmounting depot share")
		System.umount(depotDrive)
	except:
		pass
if imp:
	try:
		imp.end()
	except:
		pass

if be:
	try:
		be.backend_exit()
	except:
		pass








