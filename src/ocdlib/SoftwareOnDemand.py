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
Self-service functionality.

.. versionadded:: 4.0.4

:copyright: uib GmbH <info@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import os

from twisted.internet import defer

from OPSI.Exceptions import OpsiAuthenticationError
from OPSI.Logger import Logger
from OPSI.Types import forceUnicode
from OPSI.Service.Worker import WorkerOpsiJsonRpc
from OPSI.Service.Resource import ResourceOpsi

from ocdlib.OpsiService import ServiceConnection
from ocdlib.Config import getLogFormat, Config
from ocdlib.Events import SwOnDemandEventGenerator, getEventGenerators

logger = Logger()
config = Config()


class WorkerKioskJsonRpc(WorkerOpsiJsonRpc, ServiceConnection):
	def __init__(self, service, request, resource):
		logger.setLogFormat(getLogFormat(u'software on demand'), object=self)
		self._allowedMethods = self._getAllowedMethods()
		self._fireEvent = False
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)
		ServiceConnection.__init__(self)

	def _getAllowedMethods(self):
		return [
			"backend_setOptions",
			"configState_getObjects",
			"fireEvent_software_on_demand",
			"getDepotId",
			"getGeneralConfigValue",
			"getKioskProductInfosForClient",
			"hostControlSafe_fireEvent",
			"objectToGroup_getObjects",
			"product_getObjects",
			"productDependency_getObjects",
			"productOnClient_getObjects",
			"productOnDepot_getObjects",
			"setProductActionRequestWithDependencies",
		]

	def _getCallInstance(self, result):
		self._callInstance = self._configService
		self._callInterface = self._configService.getInterface()

	def _getCredentials(self):
		user, password = self._getAuthorization()
		if not user:
			user = config.get('global', 'host_id')

		return (user, password)

	def _authenticate(self, result):
		if self.request.remoteAddr.host == '127.0.0.1':
			self.session.authenticated = False
			return result

		try:
			self.session.user, self.session.password = self._getCredentials()

			logger.notice(u"Authorization request from %s@%s (application: %s)" % (self.session.user, self.session.ip, self.session.userAgent))

			if not self.session.password:
				raise Exception(u"No password from %s (application: %s)" % (self.session.ip, self.session.userAgent))

			if (self.session.user.lower() == config.get('global', 'host_id').lower()) and (self.session.password == config.get('global', 'opsi_host_key')):
				return result

			if os.name == 'nt':
				if self.session.user.lower() == 'administrator':
					import win32security
					# The LogonUser function will raise an Exception on logon failure
					win32security.LogonUser(self.session.user, 'None', self.session.password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
					# No exception raised => user authenticated
					return result

			raise Exception(u"Invalid credentials")
		except Exception as e:
			raise OpsiAuthenticationError(u"Forbidden: %s" % forceUnicode(e))

		return result

	def _checkRpcs(self, result):
		if not self._rpcs:
			raise Exception("No rpcs to check")

		for rpc in self._rpcs:
			if rpc.method not in self._allowedMethods:
				raise Exception("You are not allowed to execute the method: '%s'" % rpc.method)
			elif rpc.method == "fireEvent_software_on_demand":
				self._fireEvent = True
				self._rpcs.remove(rpc)

		return result

	def _processQuery(self, result):
		deferred = defer.Deferred()
		deferred.addCallback(self._openConnection)
		deferred.addCallback(self._decodeQuery)
		deferred.addCallback(self._getCallInstance)
		deferred.addCallback(self._getRpcs)
		deferred.addCallback(self._checkRpcs)
		deferred.addCallback(self._executeRpcs)
		# TODO: Let the connection open and let it expire on server
		# deferred.addCallback(self._closeConnection)
		deferred.addCallback(self._checkFireEvent)
		deferred.addErrback(self._errback)
		deferred.callback(None)
		return deferred

	def _openConnection(self, result):
		ServiceConnection.connectConfigService(self)
		return result

	def _closeConnection(self, result):
		self.disconnectConfigService()
		return result

	def _checkFireEvent(self, result):
		if self._fireEvent:
			for eventGenerator in getEventGenerators(generatorClass=SwOnDemandEventGenerator):
				eventGenerator.createAndFireEvent()
			self._fireEvent = False

		return result


class ResourceKioskJsonRpc(ResourceOpsi):
	WorkerClass = WorkerKioskJsonRpc
