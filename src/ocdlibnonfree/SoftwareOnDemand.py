# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = =
   =   ocdlibnonfree                   =
   = = = = = = = = = = = = = = = = = = =
   
   This module is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Erol Ülükmen <e.ueluekmen@uib.de>
"""
# Import
import base64
from hashlib import md5
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.web2 import responsecode, http, stream
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Service.Worker import WorkerOpsi
from OPSI.Service.Resource import ResourceOpsi

from ocdlib.OpsiService import ServiceConnection
from ocdlib.Config import Config

logger = Logger()
config = Config()

kioskPage = u'''
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<title>opsi Software On Demand</title>
	<style>
	a:link 	      { color: #555555; text-decoration: none; }
	a:visited     { color: #555555; text-decoration: none; }
	a:hover	      { color: #46547f; text-decoration: none; }
	a:active      { color: #555555; text-decoration: none; }
	body          { font-family: verdana, arial; font-size: 12px; }
	#title        { padding: 10px; color: #6276a0; font-size: 20px; letter-spacing: 5px; }
	input, select { background-color: #fafafa; border: 1px #abb1ef solid; width: 430px; font-family: verdana, arial; }
	.json         { color: #555555; width: 95%%; float: left; clear: both; margin: 30px; padding: 20px; background-color: #fafafa; border: 1px #abb1ef dashed; font-size: 11px; }
	.json_key     { color: #9e445a; }
	.json_label   { color: #abb1ef; margin-top: 20px; margin-bottom: 5px; font-size: 11px; }
	.title        { color: #555555; font-size: 20px; font-weight: bolder; letter-spacing: 5px; }
	.button       { color: #9e445a; background-color: #fafafa; border: none; margin-top: 20px; font-weight: bolder; }
	.box          { background-color: #fafafa; border: 1px #555555 solid; padding: 20px; margin-left: 30px; margin-top: 50px;}
	</style>
	
	
</head>
<body>
	<span id="title">
		<img src="/opsi_logo.png" />
		<span sytle="padding: 1px; top: 5px;">opsi Software On Demand</span>
	</span>
	<table border="1">
  <tr>
    <th>Anfordern</th>
    <th>Produkt</th>
    <th>Installationsstatus</th>
    <th>Version</th>
  </tr>
  
  <tr>
    <td>Buletten</td>
    <td>Frikadellen</td>
    <td>Fleischpflanzerl</td>
  </tr>


%result%

</table>
</body>
'''

class WorkerSoftwareOnDemand(WorkerOpsi, ServiceConnection):
	def __init__(self, service, request, resource):
		moduleName = u' %-30s' % (u'software on demand')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		WorkerOpsi.__init__(self, service, request, resource)
		ServiceConnection.__init__(self)
		
	def _getCredentials(self):
		(user, password) = self._getAuthorization()
		if not user:
			user = config.get('global', 'host_id')
		return (user, password)
		
	def _authenticate(self, result):
		if (self.request.remoteAddr.host == '127.0.0.1'):
			self.session.authenticated = False
			return result
		try:
			(self.session.user, self.session.password) = self._getCredentials()
			
			logger.notice(u"Authorization request from %s@%s (application: %s)" % (self.session.user, self.session.ip, self.session.userAgent))
			
			if not self.session.password:
				raise Exception(u"No password from %s (application: %s)" % (self.session.ip, self.session.userAgent))
			
			if (self.session.user.lower() == config.get('global', 'host_id').lower()) and (self.session.password == config.get('global', 'opsi_host_key')):
				return result
			if (os.name == 'nt'):
				if (self.session.user.lower() == 'administrator'):
					import win32security
					# The LogonUser function will raise an Exception on logon failure
					win32security.LogonUser(self.session.user, 'None', self.session.password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
					# No exception raised => user authenticated
					return result
			
			raise Exception(u"Invalid credentials")
		except Exception, e:
			raise OpsiAuthenticationError(u"Forbidden: %s" % forceUnicode(e))
		return result
	
	def _processQuery(self, result):
		self._decodeQuery(result)
		
	def _generateResponse(self, result):
		self.connectConfigService()
		
		self._configService
		
		modules = None
		if self._configService.isOpsi35():
			modules = self._configService.backend_info()['modules']
		else:
			modules = self._configService.getOpsiInformation_hash()['modules']
		
		if not modules.get('swondemand'):
			raise Exception(u"SoftwareOnDemand not available: swondemand module currently disabled")
		
		if not modules.get('customer'):
			raise Exception(u"SoftwareOnDemand not available: No customer in modules file")
			
		if not modules.get('valid'):
			raise Exception(u"SoftwareOnDemand not available: modules file invalid")
		
		if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
			raise Exception(u": modules file expired")
		
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
			raise Exception(u"SoftwareOnDemand not available: modules file invalid")
		logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
		# @TODO: modules
		
		
		myClientId = config.get('global', 'host_id')
		
		productIds = []
		tablerows = []
		productOnClients = {}
		for objectToGroup in self._configService.objectToGroup_getObjects(groupType = "ProductGroup", groupId = "kiosk"):
			productIds.append(objectToGroup.objectId)
		#for product in productIds:
		#	 = self._configService.productOnClient_getObjects(clientId = myClientId, productId = product)[0]
		for productOnClient in self._configService.productOnClient_getObjects(clientId = myClientId, productId = productIds):
			if productOnClients.has_key(productOnClient.productId):
				continue
			tablerows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
							"Platzhalter f. Combo",
							productOnClient.productId,
							productOnClient.installationStatus,
							productOnClient.productVersion))
			productOnClients[productOnClient.productId] =  productOnClient
		self.disconnectConfigService()
		
		html = kioskPage
		html = html.replace('%result%', tablerows)
		#html = html.replace('%result%', myClientId)
		
		if not isinstance(result, http.Response):
			result = http.Response()
		
		result.code = responsecode.OK
		#result.stream = stream.IByteStream((u'Kiosk ' + self.query).encode('utf-8'))
		result.stream = stream.IByteStream(html.encode('utf-8'))
		return result
	

class ResourceSoftwareOnDemand(ResourceOpsi):
	WorkerClass = WorkerSoftwareOnDemand

	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
