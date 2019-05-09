# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2006-2019 uib GmbH <info@uib.de>
# All rights reserved.

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
Connecting to a opsi service.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
@author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import base64
import os
import random
import time
from hashlib import md5
from httplib import HTTPConnection, HTTPSConnection
from twisted.conch.ssh import keys

from OPSI.Exceptions import OpsiAuthenticationError, OpsiServiceVerificationError
from OPSI.Logger import Logger
from OPSI.Util.Thread import KillableThread
from OPSI.Util.HTTP import urlsplit, non_blocking_connect_http, non_blocking_connect_https
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Types import forceBool, forceFqdn, forceInt, forceUnicode
from OPSI import System

from ocdlib.Localization import _
from ocdlib import __version__
from ocdlib.Config import getLogFormat, Config
from ocdlib.Exceptions import CanceledByUserError

logger = Logger()
config = Config()


def isConfigServiceReachable(timeout=5):
	for url in config.getConfigServiceUrls():
		try:
			logger.info(u"Trying connection to config service '%s'" % url)
			(scheme, host, port, baseurl, username, password) = urlsplit(url)
			conn = None
			if scheme.endswith('s'):
				conn = HTTPSConnection(host=host, port=port)
				non_blocking_connect_https(conn, timeout)
			else:
				conn = HTTPConnection(host=host, port=port)
				non_blocking_connect_http(conn, timeout)
			if not conn:
				continue
			try:
				conn.sock.close()
				conn.close()
			except Exception:
				pass
			return True
		except Exception, e:
			logger.info(e)
	return False


class ServiceConnection(object):
	def __init__(self, loadBalance=False):
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
		return isConfigServiceReachable(timeout=timeout)

	def stop(self):
		logger.debug(u"Stopping thread")
		self.cancelled = True
		self.running = False
		for i in range(10):
			if not self.is_alive():
				break
			self.terminate()
			time.sleep(0.5)

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True):
		try:
			configServiceUrls = config.getConfigServiceUrls(allowTemporaryConfigServiceUrls=allowTemporaryConfigServiceUrls)
			if not configServiceUrls:
				raise Exception(u"No service url defined")

			if self._loadBalance and (len(configServiceUrls) > 1):
				random.shuffle(configServiceUrls)

			for urlIndex, url in enumerate(configServiceUrls):
				self._configServiceUrl = url

				kwargs = self.connectionThreadOptions()
				logger.debug(u"Creating ServiceConnectionThread (url: %s)" % self._configServiceUrl)
				serviceConnectionThread = ServiceConnectionThread(
					configServiceUrl=self._configServiceUrl,
					username=config.get('global', 'host_id'),
					password=config.get('global', 'opsi_host_key'),
					**kwargs
				)

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
						% (timeout, serviceConnectionThread.is_alive(), cancellableAfter))
					self.connectionTimeoutChanged(timeout)
					if cancellableAfter > 0:
						cancellableAfter -= 1
					if cancellableAfter == 0:
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

				if serviceConnectionThread.connected and forceBool(config.get('config_service', 'sync_time_from_service')):
					logger.info(u"Syncing local system time from service")
					try:
						System.setLocalSystemTime(serviceConnectionThread.configService.getServiceTime(utctime=True))
					except Exception as e:
						logger.error(u"Failed to sync time: {0!r}", e)

				if urlIndex > 0:
					backendinfo = serviceConnectionThread.configService.backend_info()
					modules = backendinfo['modules']
					helpermodules = backendinfo['realmodules']

					if not modules.get('high_availability'):
						self.connectionFailed(u"High availability module currently disabled")

					if not modules.get('customer'):
						self.connectionFailed(u"No customer in modules file")

					if not modules.get('valid'):
						self.connectionFailed(u"Modules file invalid")

					if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
						self.connectionFailed(u"Modules file expired")

					logger.info(u"Verifying modules file signature")
					publicKey = keys.Key.fromString(data=base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
					data = u''
					mks = modules.keys()
					mks.sort()
					for module in mks:
						if module in ('valid', 'signature'):
							continue

						if module in helpermodules:
							val = helpermodules[module]
							if int(val) > 0:
								modules[module] = True
						else:
							val = modules[module]
							if val == False:
								val = 'no'
							elif val == True:
								val = 'yes'

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
				self._configService.backend_exit()
			except Exception as exitError:
				logger.error(u"Failed to disconnect config service: %s" % forceUnicode(exitError))
		self._configService = None
		self._configServiceUrl = None


class ServiceConnectionThread(KillableThread):
	def __init__(self, configServiceUrl, username, password, statusSubject=None):
		logger.setLogFormat(getLogFormat(u'service connection'), object=self)
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

			certDir = config.get('global', 'server_cert_dir')
			verifyServerCert = config.get('global', 'verify_server_cert')

			proxyMode = config.get('global', 'proxy_mode')
			proxyURL = config.get('global', 'proxy_url')
			if proxyMode == 'system':
				logger.notice(u'not implemented yet')
				proxyURL = System.getSystemProxySetting()
			elif proxyMode == 'static':
				proxyURL = config.get('global', 'proxy_url')

			(scheme, host, port, baseurl, username, password) = urlsplit(self._configServiceUrl)
			serverCertFile = os.path.join(certDir, host + '.pem')
			if verifyServerCert:
				logger.info(u"Server verification enabled, using cert file '%s'" % serverCertFile)

			caCertFile = os.path.join(certDir, 'cacert.pem')
			verifyServerCertByCa = config.get('global', 'verify_server_cert_by_ca')
			if verifyServerCertByCa:
				logger.info(u"Server verification by CA enabled, using CA cert file '%s'" % caCertFile)

			tryNum = 0
			while not self.cancelled and not self.connected:
				tryNum += 1
				try:
					logger.notice(u"Connecting to config server '%s' #%d" % (self._configServiceUrl, tryNum))
					self.setStatusMessage(_(u"Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
					if len(self._username.split('.')) < 3:
						raise Exception(u"Domain missing in username '%s'" % self._username)
					if "localhost" in self._configServiceUrl or "127.0.0.1" in self._configServiceUrl:
						if proxyURL:
							logger.debug("Connecting to localhost, connecting directly without proxy")
							proxyURL = None

					self.configService = JSONRPCBackend(
						address=self._configServiceUrl,
						username=self._username,
						password=self._password,
						serverCertFile=serverCertFile,
						verifyServerCert=verifyServerCert,
						caCertFile=caCertFile,
						verifyServerCertByCa=verifyServerCertByCa,
						proxyURL=proxyURL,
						application='opsiclientd version %s' % __version__
					)

					self.configService.accessControl_authenticated()
					self.configService.setDeflate(True)
					self.connected = True
					self.connectionError = None
					self.setStatusMessage(_(u"Connected to config server '%s'") % self._configServiceUrl)
					logger.notice(u"Connected to config server '%s'" % self._configServiceUrl)
				except OpsiServiceVerificationError as verificationError:
					self.connectionError = forceUnicode(verificationError)
					self.setStatusMessage(_(u"Failed to connect to config server '%s': Service verification failure") % self._configServiceUrl)
					logger.error(u"Failed to connect to config server '%s': %s" % (self._configServiceUrl, forceUnicode(verificationError)))
					break
				except Exception as error:
					self.connectionError = forceUnicode(error)
					self.setStatusMessage(_(u"Failed to connect to config server '%s': %s") % (self._configServiceUrl, forceUnicode(error)))
					logger.error(u"Failed to connect to config server '%s': %s" % (self._configServiceUrl, forceUnicode(error)))
					if isinstance(error, OpsiAuthenticationError):
						fqdn = System.getFQDN()
						try:
							fqdn = forceFqdn(fqdn)
						except Exception as fqdnError:
							logger.warning(u"Failed to get fqdn from os, got '%s': %s" % (fqdn, fqdnError))
							break

						if self._username != fqdn:
							logger.notice(u"Connect failed with username '%s', got fqdn '%s' from os, trying fqdn" % (self._username, fqdn))
							self._username = fqdn
						else:
							break
					time.sleep(3)

		except Exception as error:
			logger.logException(error)

		self.running = False

	def stopConnectionCallback(self, choiceSubject):
		logger.notice(u"Connection cancelled by user")
		self.stop()

	def stop(self):
		logger.debug(u"Stopping thread")
		self.cancelled = True
		self.running = False
		for i in range(10):
			if not self.is_alive():
				break
			self.terminate()
			time.sleep(0.5)
