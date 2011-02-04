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
import base64, cgi
from hashlib import md5
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.web2 import responsecode, http, stream
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Object import *
from OPSI.Service.Worker import WorkerOpsi
from OPSI.Service.Resource import ResourceOpsi

from ocdlib.OpsiService import ServiceConnection
from ocdlib.Config import Config
from ocdlib.Events import SwOnDemandEventGenerator, getEventGenerators
from ocdlib.Localization import _

logger = Logger()
config = Config()

mainpage = u'''
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<title>opsi Software On Demand</title>
	<style>
	body          { font-family: verdana, arial; font-size: 12px; }
        #title        { padding: 10px; color: #6276a0; font-size: 20px; letter-spacing: 5px; }
        input, select { background-color: #fafafa; border: 1px #abb1ef solid; font-family: verdana, arial;}
        .title        { color: #555555; font-size: 20px; font-weight: bolder; letter-spacing: 5px; }
        .button       { color: #9e445a; background-color: #fafafa; border: 1px solid; font-weight: bolder; }

        table           { margin-top: 20px; margin-left: 20px; border-collapse:collapse;text-align: center; width: 700px;}
        thead           { background-color: #6495ed;}
        tbody tr:hover  {background-color: #87cefa; }
        tfoot           { margin-top: 50px; }
        th              { padding: 5px; padding-left: 10px; }

        td              { padding: 5px;}
        .checkbox       { width: 5px; }
        .product        { width: 100px; }
        .descr          { width: 150px; }
        .advice         { width: 150px; }
        .state          { width: 75px; }
        .version        { width: 75px; }
	</style>
	
</head>
<body>
	<span id="title">
		<img src="/opsi_logo.png" />
		<span sytle="padding: 1px; top: 5px;">opsi Software On Demand</span>
	</span>
	<form method="post">
		%result%
	</form>
	
</body>
'''


answerpage = u'''
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<title>opsi Software On Demand</title>
	<style>
	   .title        { color: #555555; font-size: 20px; font-weight: bolder; letter-spacing: 5px; }
	   #title        { padding: 10px; color: #6276a0; font-size: 20px; letter-spacing: 5px; }
	   .button       { color: #9e445a; background-color: #fafafa; border: 1px solid; font-weight: bolder; }
           table		{ margin-top: 10px; border-collapse:collapse;text-align: center; }
           thead		{ background-color: #6495ed;}
           tfoot		{text-align: right; }
        </style>
</head>
<body>
	<span id="title">
		<img src="/opsi_logo.png" />
		<span sytle="padding: 1px; top: 5px;">opsi Software On Demand</span>
	</span>
	<form method="post">
		%result%
	</form>
	
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
	
	def _executeQuery(self, param, clientId):
		#if param:
		productOnClients = self._configService.productOnClient_getObjects(clientId = clientId)
		productOnClientsWithDependencies = []
		try:
			logger.debug(u'Try to execute Query')
			#productOnClients = self._configService.productOnClient_getObjects(clientId = clientId)
			#product On Clients
			modified = False
			for productId in param.get('products', []):
				index = -1
				for i in range(len(productOnClients)):
					if productOnClients[i].productId == productId:
						index = i
						break
				#productOnClient = self._configService.productOnClient_getObjects(clientId = clientId, productId = productId)
				if (index == -1):
					productOnClient = ProductOnClient(
						productId          = productId,
						productType        = 'LocalbootProduct',
						clientId           = clientId,
						installationStatus = 'not_installed'
					)
					productOnClients.append(productOnClient)
					index = len(productOnClients) - 1
				if productOnClient.actionRequest == 'setup':
					logger.notice(u"Product: '%s' is already set on setup, nothing to do." % productId)
					continue
				#TODO Vorbedingung fuer Abhaengige Pakete mit einbauen.
				productOnClients[index].setActionRequest('setup')
				modified = True
			
			#Set Products
			if modified:
				logger.notice(u"Now try to fulfill ProductDependencies.")
				for poc in productOnClients:
					logger.info(u"BEFORE: %s" % poc)
				productOnClientsWithDependencies = self._configService.productOnClient_addDependencies(productOnClients)
				for poc in productOnClientsWithDependencies:
					logger.info(u"AFTER: %s" % poc)
				#self._configService.productOnClient_updateObjects(productOnClients_withDependencies)
			else:
				logger.notice(u'No Product to set.')
			
			if param.get('action') == 'Save':
				return productOnClientsWithDependencies
				
			if param.get('action') == 'ondemand':
				#erst setup setzen
				#sw on demand
				for eventGenerator in getEventGenerators(generatorClass = SwOnDemandEventGenerator):
					eventGenerator.fireEvent()
				
			elif param.get('action') == 'onrestart':
				pass
				#ausgabe
			else:
				logger.notice(u'No action set, nothing to do.')
			return 'Alles roger'
		except Exception, e:
			logger.logException(e)
		
		
	def _generateResponse(self, result):
		self.connectConfigService()
		
		self._configService
		
		#Modules Implementation
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
		# endof: Modules Implementation
		
		state = ''
		checked = ''
		productVersion = ''
		productDescription = ''
		productAdvice = ''
		tablerows = []
		#productOnDepots = {}
		productIds = []
		myClientId = config.get('global', 'host_id')
		mydepotServer = config.get('depot_server','depot_id')
		onDemandGroups = ["kiosk","kiosk1"]
		
		
		if not isinstance(result, http.Response):
			result = http.Response()
		
		for objectToGroup in self._configService.objectToGroup_getObjects(groupType = "ProductGroup", groupId = onDemandGroups):
			logger.debug(u"Product found: '%s'" % objectToGroup.objectId)
			if not objectToGroup.objectId in productIds:
				productIds.append(objectToGroup.objectId)
		
		#Query bearbeitung
		if self.query:
			logger.notice(u"QUERY: '%s'" % self.query)
			if 'action' in self.query and 'product' in self.query:
				params = {}
				for param in self.query.split(u'&'):
					if 'action' in param:
						params['action'] = param.split(u'=')[1]
						continue
					if not params.has_key('products'):
						params['products'] = []
					params['products'].append(param.split(u'=')[1])
				
				if params:
					logger.notice(u"Parameters from POST: '%s'" % params)
					productOnClients = self._executeQuery(params, myClientId)
				
				if productOnClients:
					logger.notice(u"Action Save was send.")
					if params['action'].lower() == "save":
						html = answerpage
						resulttable = '''
							<table>
								<thead>
									<tr>
										<th>Produkte die installiert werden</th>
										<th>Produkte die zus&auml;tzlich installiert werden</th>
									</tr>
								</thead>
								<tbody>

										%result%
								</tbody>
								<tfoot>
									<tr>
										<td align="center" colspan="2">
											<input name="action" value="ondemand" id="submit" class="button" type="submit" />
											<input name="action" value="onrestart" id="submit" class="button" type="submit" />
											<input name="back" value="Zurueck" id="submit" class="button" type="submit" />
										</td>
									<tr>
								</tfoot>
								</table>
								'''
						for productOnClient in productOnClients:
							if productOnClient.getActionRequest() not in ('none', None):
								if productOnClient.productId in prroductIds:
									tablerows.append('''<tr>
												<td>%s (%s)<input style="DISPLAY:none" type="checkbox" name="product" value="%s" checked></td>
												<td></td>
											    </tr>''' \
											% (productOnClient.productId, productOnClient.getActionRequest(), productOnClient.productId))
								else:
									tablerows.append('''<tr>
												<td></td>
												<td>%s (%s)</td>
											    </tr>''' \
											% (productOnClient.productId, productOnClient.getActionRequest() ))
						if tablerows:
							#Try to sort rows:
							for row in tablerows:
								
							
							
						table = ''
						for row in tablerows:
							table += row
						
						resulttable = resulttable.replace('%result%', forceUnicode(table))
						html = html.replace('%result%', forceUnicode(resulttable))
						result.stream = stream.IByteStream(html.encode('utf-8'))
						return result
		
		
		
		self._configService.setAsync(True)
		jsonrpc1 = self._configService.productOnClient_getObjects(clientId = myClientId)
		jsonrpc2 = self._configService.product_getObjects(id = productIds)
		jsonrpc3 = self._configService.productOnDepot_getObjects(depotId = mydepotServer, productId = productIds)
		productOnClients = jsonrpc1.waitForResult()
		products = jsonrpc2.waitForResult()
		productOnDepots = jsonrpc3.waitForResult()
		self._configService.setAsync(False)
		for poc in productOnClients:
			logger.info(u"FROM SERVICE: %s" % poc)
		
		for productId in productIds:
			productOnClient = None
			for clientobj in productOnClients:
				if clientobj.productId == productId:
					productOnClient = clientobj
					break
			for depotobj in productOnDepots:
				if depotobj.productId == productId:
					productOnDepot = depotobj
					break
			for productObj in products:
				if productObj.id == productId:
					product = productObj
					break
				
			#for obj in productOnClients:
			#	productOnClient = None
			#	if obj.productId in productIds:
			#		productOnClient = obj
			#		break
			
			productDescription = product.description
			productAdvice = product.advice
			if productOnClient:
				state = productOnClient.installationStatus
				productVersion = productOnClient.productVersion
				if productOnClient.actionRequest == 'setup':
					checked = u'checked="checked"'
				else:
					checked = ''
					state = 'nicht installiert'
			else:
				state = 'nicht installiert'
				productVersion = ''
				
			#if productOnDepots.has_key(productOnDepot.productId):
			#	logger.notice("!!!Produkt ist schon vorhanden: '%s'" % productOnDepot.productId)
			#	continue
			
			
			tablerows.append('''<tr>
								<td class="checkbox">%s</td>
								<td class="product">%s</td>
								<td class="descr">%s</td>
								<td class="advice">%s</td>
								<td class="state">%s</td>
								<td class="version">%s</td>
								<td class="version">%s</td>
							</tr>''' % (
									'<input type="checkbox" name="product" value="%s" %s>' % (productOnDepot.productId,checked),
									productId,
									productDescription,
									productAdvice,
									state,
									productVersion,
									productOnDepot.productVersion
									)
							)
			#productOnDepots[productOnDepot.productId] = productOnDepot
			checked = ''
		self.disconnectConfigService()
		
		table = ''
		html = mainpage
		for row in tablerows:
			table += row
		
		maintable = u'''
					<table>
						<thead>
							<tr>
								<th></th>
								<th>%s</th>
								<th>%s</th>
								<th>%s</th>
								<th>%s</th>
								<th>%s</th>
								<th>%s</th>
							</tr>
						</thead>
						<tbody>

							%s
						</tbody>
						<tfoot>
							<tr>
								<td align="center" colspan="7">
									<input name="action" value="Save" id="submit" class="button" type="submit" />
								</td>
							<tr>
						</tfoot>
					</table>
					''' % (_(u'product'),
						_(u'description'),
						_(u'advice'),
						_(u'state'),
						_(u'version'),
						_(u'available version'),
						table
						)
		
		html = html.replace('%result%', maintable)
		
		#html = html.replace('%result%', myClientId)
		
		result.code = responsecode.OK
		#result.stream = stream.IByteStream((u'Kiosk ' + self.query).encode('utf-8'))
		result.stream = stream.IByteStream(html.encode('utf-8'))
		return result
	

class ResourceSoftwareOnDemand(ResourceOpsi):
	WorkerClass = WorkerSoftwareOnDemand
