# -*- coding: utf-8 -*-

# action_processor_starter is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2008-2019 uib GmbH <info@uib.de>

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
Helper to start the action processor.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:license: GNU Affero General Public License version 3
"""

import gettext
import locale
import os
import sys

from OPSI.Logger import LOG_NONE, Logger
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI import System

from ocdlib.Config import getLogFormat

__version__ = '4.1'

encoding = locale.getpreferredencoding()

argv = [unicode(arg, encoding) for arg in sys.argv]

if len(argv) != 17:
	print u"Usage: %s <hostId> <hostKey> <controlServerPort> <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword> <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout> <runAsUser> <runAsPassword> <createEnvironment>" % os.path.basename(argv[0])
	sys.exit(1)

(hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, depotServerUsername, depotServerPassword, sessionId, actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout, runAsUser, runAsPassword, createEnvironment) = argv[1:]

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
logger.setLogFormat(getLogFormat(os.path.basename(argv[0])))

logger.debug(u"Called with arguments: %s" % u', '.join((hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl, depotDrive, depotServerUsername, depotServerPassword, sessionId, actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout, runAsUser, runAsPassword, createEnvironment)) )

try:
	lang = locale.getdefaultlocale()[0].split('_')[0]
	localeDir = os.path.join(os.path.dirname(sys.argv[0]), 'locale')
	translation = gettext.translation('opsiclientd', localeDir, [lang])
	_ = translation.ugettext
except Exception as e:
	logger.error(u"Locale not found: %s" % e)

	def _(string):
		return string

if runAsUser and createEnvironment.lower() in ('yes', 'true', '1'):
	createEnvironment = True
else:
	createEnvironment = False
actionProcessorTimeout = int(actionProcessorTimeout)
imp = None
depotShareMounted = False
be = None

try:
	be = JSONRPCBackend(username=hostId, password=hostKey, address=u'https://localhost:%s/opsiclientd' % controlServerPort)

	if runAsUser:
		logger.info(u"Impersonating user '%s'" % runAsUser)
		imp = System.Impersonate(username=runAsUser, password=runAsPassword, desktop=actionProcessorDesktop)
		imp.start(logonType=u'INTERACTIVE', newDesktop=True, createEnvironment=createEnvironment)
	else:
		logger.info(u"Impersonating network account '%s'" % depotServerUsername)
		imp = System.Impersonate(username=depotServerUsername, password=depotServerPassword, desktop=actionProcessorDesktop)
		imp.start(logonType=u'NEW_CREDENTIALS')

	if depotRemoteUrl.split('/')[2] not in ('127.0.0.1', 'localhost'):
		logger.notice(u"Mounting depot share %s" % depotRemoteUrl)
		be.setStatusMessage(sessionId, _(u"Mounting depot share %s") % depotRemoteUrl)

		if runAsUser:
			System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)
		else:
			System.mount(depotRemoteUrl, depotDrive)
		depotShareMounted = True

	logger.notice(u"Starting action processor")
	be.setStatusMessage(sessionId, _(u"Action processor is running"))

	imp.runCommand(actionProcessorCommand, timeoutSeconds=actionProcessorTimeout)

	logger.notice(u"Action processor ended")
	be.setStatusMessage(sessionId, _(u"Action processor ended"))
except Exception as e:
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
