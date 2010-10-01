# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.OpsiService                  =
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

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI.Backend.JSONRPC import JSONRPCBackend

from ocdlib.Localization import _, setLocaleDir, getLanguage
from ocdlib.OpsiCLientd import __version__

logger = Logger()


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     SERVICE CONNECTION THREAD                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ServiceConnectionThread(KillableThread):
	def __init__(self, configServiceUrl, username, password, statusObject):
		moduleName = u' %-30s' % (u'service connection')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._statusSubject = statusObject
		self.configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		if not self._configServiceUrl:
			raise Exception(u"No config service url given")
	
	def setStatusMessage(self, message):
		self._statusSubject.setMessage(message)
	
	def getUsername(self):
		return self._username
	
	def run(self):
		try:
			logger.debug(u"ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False
			
			tryNum = 0
			while not self.cancelled and not self.connected:
				try:
					tryNum += 1
					logger.notice(u"Connecting to config server '%s' #%d" % (self._configServiceUrl, tryNum))
					self.setStatusMessage( _(u"Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
					if (len(self._username.split('.')) < 3):
						raise Exception(u"Domain missing in username '%s'" % self._username)
					self.configService = JSONRPCBackend(address = self._configServiceUrl, username = self._username, password = self._password, application = 'opsiclientd version %s' % __version__)
					if self.configService.isLegacyOpsi():
						self.configService.authenticated()
					else:
						self.configService.accessControl_authenticated()
						self.configService.setDeflate(True)
					self.connected = True
					self.setStatusMessage(_(u"Connected to config server '%s'") % self._configServiceUrl)
					logger.notice(u"Connected to config server '%s'" % self._configServiceUrl)
				except Exception, e:
					self.setStatusMessage(_(u"Failed to connect to config server '%s': %s") % (self._configServiceUrl, forceUnicode(e)))
					logger.error(u"Failed to connect to config server '%s': %s" % (self._configServiceUrl, forceUnicode(e)))
					fqdn = System.getFQDN().lower()
					if (self._username != fqdn) and (fqdn.count('.') >= 2):
						logger.notice(u"Connect failed with username '%s', got fqdn '%s' from os, trying fqdn" \
								% (self._username, fqdn))
						self._username = fqdn
					time.sleep(1)
					time.sleep(1)
					time.sleep(1)
			
		except Exception, e:
			logger.logException(e)
		self.running = False
	
	def stopConnectionCallback(self, choiceSubject):
		logger.notice(u"Connection cancelled by user")
		self.stop()
	
	def stop(self):
		logger.debug(u"Stopping thread")
		self.cancelled = True
		self.running = False
		for i in range(10):
			if not self.isAlive():
				break
			self.terminate()
			time.sleep(0.5)

