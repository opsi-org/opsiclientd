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
   @author: Jan Schneider <j.schneider@uib.de>
"""


import base64
from hashlib import md5
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI import System

# Get logger instance
logger = Logger()

def selectDepotserver(config, configService, productIds=[], cifsOnly=True):
	productIds = forceProductIdList(productIds)
	
	logger.notice(u"Selecting depot for products %s" % productIds)
	if not configService:
		raise Exception(u"Not connected to config service")
	
	if configService.isLegacyOpsi():
		return
	
	selectedDepot = None
	
	configService.backend_setOptions({"addConfigStateDefaults": True})
	
	depotIds = []
	dynamicDepot = False
	depotProtocol = 'cifs'
	for configState in configService.configState_getObjects(
				configId = ['clientconfig.depot.dynamic', 'clientconfig.depot.protocol', 'opsiclientd.depot_server.depot_id', 'opsiclientd.depot_server.url'],
				objectId = config.get('global', 'host_id')):
		if not configState.values or not configState.values[0]:
			continue
		if   (configState.configId == 'opsiclientd.depot_server.url') and configState.values:
			try:
				depotUrl = forceUrl(configState.values[0])
				config.set('depot_server', 'depot_id', u'')
				config.set('depot_server', 'url', depotUrl)
				logger.notice(u"Depot url was set to '%s' from configState %s" % (depotUrl, configState))
				return
			except Exception, e:
				logger.error(u"Failed to set depot url from values %s in configState %s: %s" % (configState.values, configState, e))
		elif (configState.configId == 'opsiclientd.depot_server.depot_id') and configState.values:
			try:
				depotId = forceHostId(configState.values[0])
				depotIds.append(depotId)
				logger.notice(u"Depot was set to '%s' from configState %s" % (depotId, configState))
			except Exception, e:
				logger.error(u"Failed to set depot id from values %s in configState %s: %s" % (configState.values, configState, e))
		elif (configState.configId == 'clientconfig.depot.dynamic') and configState.values:
			dynamicDepot = forceBool(configState.values[0])
		elif (configState.configId == 'clientconfig.depot.protocol') and configState.values and configState.values[0] and (configState.values[0] == 'webdav'):
			depotProtocol = 'webdav'
	
	if dynamicDepot:
		if not depotIds:
			logger.info(u"Dynamic depot selection enabled")
		else:
			logger.info(u"Dynamic depot selection enabled, but depot is already selected")
	else:
		logger.info(u"Dynamic depot selection disabled")
	
	if not depotIds:
		clientToDepotservers = configService.configState_getClientToDepotserver(
				clientIds  = [ config.get('global', 'host_id') ],
				masterOnly = (not dynamicDepot),
				productIds = productIds)
		if not clientToDepotservers:
			raise Exception(u"Failed to get depot config from service")
		
		depotIds = [ clientToDepotservers[0]['depotId'] ]
		if dynamicDepot:
			depotIds.extend(clientToDepotservers[0].get('alternativeDepotIds', []))
		
	masterDepot = None
	alternativeDepots = []
	for depot in configService.host_getObjects(type = 'OpsiDepotserver', id = depotIds):
		if (depot.id == depotIds[0]):
			masterDepot = depot
		else:
			alternativeDepots.append(depot)
	if not masterDepot:
		raise Exception(u"Failed to get info for master depot '%s'" % depotIds[0])
	
	logger.info(u"Master depot for products %s is %s" % (productIds, masterDepot.id))
	selectedDepot = masterDepot
	if dynamicDepot:
		if alternativeDepots:
			logger.info(u"Got alternative depots for products: %s" % productIds)
			for i in range(len(alternativeDepots)):
				logger.info(u"%d. alternative depot is %s" % ((i+1), depot.id))
			
			try:
				modules = configService.backend_info()['modules']
			
				if not modules.get('dynamic_depot'):
					raise Exception(u"Dynamic depot module currently disabled")
				
				if not modules.get('customer'):
					raise Exception(u"No customer in modules file")
					
				if not modules.get('valid'):
					raise Exception(u"Modules file invalid")
				
				if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
					raise Exception(u"Modules file expired")
				
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
					raise Exception(u"Modules file invalid")
				logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
				
				defaultInterface = None
				networkInterfaces = System.getNetworkInterfaces()
				if not networkInterfaces:
					raise Exception(u"No network interfaces found")
				defaultInterface = networkInterfaces[0]
				for networkInterface in networkInterfaces:
					if networkInterface.gatewayList.ipAddress:
						defaultInterface = networkInterface
						break
				clientConfig = {
					"clientId":       config.get('global', 'host_id'),
					"ipAddress":      forceUnicode(defaultInterface.ipAddressList.ipAddress),
					"netmask":        forceUnicode(defaultInterface.ipAddressList.ipMask),
					"defaultGateway": forceUnicode(defaultInterface.gatewayList.ipAddress)
				}
				
				depotSelectionAlgorithm = configService.getDepotSelectionAlgorithm()
				logger.debug2(u"depotSelectionAlgorithm:\n%s" % depotSelectionAlgorithm)
				exec(depotSelectionAlgorithm)
				selectedDepot = selectDepot(clientConfig = clientConfig, masterDepot = masterDepot, alternativeDepots = alternativeDepots)
				if not selectedDepot:
					selectedDepot = masterDepot
			except Exception, e:
				logger.logException(e)
				logger.error(u"Failed to select depot: %s" % e)
		else:
			logger.info(u"No alternative depot for products: %s" % productIds)
	logger.notice(u"Selected depot is: %s" % selectedDepot)
	config.set('depot_server', 'depot_id', selectedDepot.id)
	if (depotProtocol == 'webdav') and not cifsOnly:
		config.set('depot_server', 'url', selectedDepot.depotWebdavUrl)
	else:
		config.set('depot_server', 'url', selectedDepot.depotRemoteUrl)



