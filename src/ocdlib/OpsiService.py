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

import time, base64
from hashlib import md5
from twisted.conch.ssh import keys
import random
from httplib import HTTPConnection, HTTPSConnection

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI.Util.HTTP import urlsplit, non_blocking_connect_http, non_blocking_connect_https
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Types import *
from OPSI import System

from ocdlib.Localization import _, setLocaleDir, getLanguage
from ocdlib.Opsiclientd import __version__
from ocdlib.Config import Config
from ocdlib.Exceptions import *

logger = Logger()
config = Config()

def isConfigServiceReachable(timeout=15):
	for url in config.getConfigServiceUrls():
		try:
			logger.info(u"Trying connection to config service '%s'" % url)
			(scheme, host, port, baseurl, username, password) = urlsplit(url)
			conn = None
			if scheme.endswith('s'):
				conn = HTTPSConnection(host = host, port = port)
				non_blocking_connect_https(conn, timeout)
			else:
				conn = HTTPConnection(host = host, port = port)
				non_blocking_connect_http(conn, timeout)
			if not conn:
				continue
			try:
				conn.sock.close()
				conn.close()
			except:
				pass
			return True
		except Exception, e:
			logger.info(e)
	return False

class ServiceConnection(object):
	def __init__(self, loadBalance = False):
		self._loadBalance = forceBool(loadBalance)
		self._configServiceUrl = None
		self._configService = None
	
	def connectionThreadOptions(self):
		return {}
	
	def connectionStart(self, configServiceUrl):
		pass
	
	def connectionCancelable(self, stopConnectionCallback):
		pass
	
	def connectionTimeoutChanged(self, timeout):
		pass
	
	def connectionCanceled(self):
		error = u"Failed to connect to config service '%s': cancelled by user" % self._configServiceUrl
		logger.error(error)
		raise CanceledByUserError(error)
		
	def connectionTimedOut(self):
		error = u"Failed to connect to config service '%s': timed out after %d seconds" % (self._configServiceUrl, config.get('config_service', 'connection_timeout'))
		logger.error(error)
		raise Exception(error)
	
	def connectionFailed(self, error):
		error = u"Failed to connect to config service '%s': %s" % (self._configServiceUrl, error)
		logger.error(error)
		raise Exception(error)
	
	def connectionEstablished(self):
		pass
	
	def getConfigService(self):
		return self._configService
	
	def getConfigServiceUrl(self):
		return self._configServiceUrl
	
	def isConfigServiceConnected(self):
		return bool(self._configService)
	
	def isConfigServiceReachable(self, timeout=15):
		return isConfigServiceReachable(timeout = timeout)
	
	def stop(self):
		logger.debug(u"Stopping thread")
		self.cancelled = True
		self.running = False
		for i in range(10):
			if not self.isAlive():
				break
			self.terminate()
			time.sleep(0.5)
			
	def connectConfigService(self, allowTemporaryConfigServiceUrls = True):
		try:
			configServiceUrls = config.getConfigServiceUrls(allowTemporaryConfigServiceUrls = allowTemporaryConfigServiceUrls)
			if not configServiceUrls:
				raise Exception(u"No service url defined")
			
			if self._loadBalance and (len(configServiceUrls) > 1):
				random.shuffle(configServiceUrls)
			
			for urlIndex in range(len(configServiceUrls)):
				self._configServiceUrl = configServiceUrls[urlIndex]
				
				kwargs = self.connectionThreadOptions()
				logger.debug(u"Creating ServiceConnectionThread (url: %s)" % self._configServiceUrl)
				serviceConnectionThread = ServiceConnectionThread(
							configServiceUrl = self._configServiceUrl,
							username         = config.get('global', 'host_id'),
							password         = config.get('global', 'opsi_host_key'),
							**kwargs)
				
				self.connectionStart(self._configServiceUrl)
				
				cancellableAfter = forceInt(config.get('config_service', 'user_cancelable_after'))
				timeout = forceInt(config.get('config_service', 'connection_timeout'))
				logger.info(u"Starting ServiceConnectionThread, timeout is %d seconds" % timeout)
				serviceConnectionThread.start()
				for i in range(5):
					if serviceConnectionThread.running:
						break
					time.sleep(1)
				
				logger.debug(u"ServiceConnectionThread started")
				while serviceConnectionThread.running and (timeout > 0):
					logger.debug(u"Waiting for ServiceConnectionThread (timeout: %d, alive: %s, cancellable in: %d) " \
						% (timeout, serviceConnectionThread.isAlive(), cancellableAfter))
					self.connectionTimeoutChanged(timeout)
					cancellableAfter -= 1
					if (cancellableAfter == 0):
						self.connectionCancelable(serviceConnectionThread.stopConnectionCallback)
					time.sleep(1)
					timeout -= 1
				
				if serviceConnectionThread.cancelled:
					self.connectionCanceled()
				
				if serviceConnectionThread.running:
					serviceConnectionThread.stop()
					self.connectionTimedOut()
				
				if not serviceConnectionThread.connected:
					self.connectionFailed(serviceConnectionThread.connectionError)
				
				if serviceConnectionThread.connected and (serviceConnectionThread.getUsername() != config.get('global', 'host_id')):
					config.set('global', 'host_id', serviceConnectionThread.getUsername().lower())
					logger.info(u"Updated host_id to '%s'" % config.get('global', 'host_id'))
					config.updateConfigFile()
				
				if (urlIndex > 0):
					modules = None
					if serviceConnectionThread.configService.isLegacyOpsi():
						modules = serviceConnectionThread.configService.getOpsiInformation_hash()['modules']
					else:
						modules = serviceConnectionThread.configService.backend_info()['modules']
					
					if not modules.get('high_availability'):
						self.connectionFailed(u"High availability module currently disabled")
					
					if not modules.get('customer'):
						self.connectionFailed(u"No customer in modules file")
						
					if not modules.get('valid'):
						self.connectionFailed(u"Modules file invalid")
					
					if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
						self.connectionFailed(u"Modules file expired")
					
					logger.info(u"Verifying modules file signature")
					publicKey = keys.Key.fromString(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
					data = u''
					mks = modules.keys()
					mks.sort()
					for module in mks:
						if module in ('valid', 'signature'):
							continue
						val = modules[module]
						if (val == False): val = 'no'
						if (val == True):  val = 'yes'
						data += u'%s = %s\r\n' % (module.lower().strip(), val)
					if not bool(publicKey.verify(md5(data).digest(), [ long(modules['signature']) ])):
						self.connectionFailed(u"Modules file invalid")
					logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
				
				self._configService = serviceConnectionThread.configService
				self.connectionEstablished()
		except:
			self.disconnectConfigService()
			raise
	
	def disconnectConfigService(self):
		if self._configService:
			try:
				if self._configService.isLegacyOpsi():
					self._configService.exit()
				else:
					self._configService.backend_exit()
			except Exception, e:
				logger.error(u"Failed to disconnect config service: %s" % forceUnicode(e))
		self._configService = None
		self._configServiceUrl = None
	
class ServiceConnectionThread(KillableThread):
	def __init__(self, configServiceUrl, username, password, statusSubject = None):
		moduleName = u' %-30s' % (u'service connection')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._statusSubject = statusSubject
		self.configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		self.connectionError = None
		if not self._configServiceUrl:
			raise Exception(u"No config service url given")
	
	def setStatusMessage(self, message):
		if not self._statusSubject:
			return
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
					self.connectionError = None
					self.setStatusMessage(_(u"Connected to config server '%s'") % self._configServiceUrl)
					logger.notice(u"Connected to config server '%s'" % self._configServiceUrl)
				except Exception, e:
					self.connectionError = forceUnicode(e)
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

