# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = = = = = =
   =   ocdlibnonfree.CacheBackend                  =
   = = = = = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Jan Schneider <j.schneider@uib.de>
"""

import inspect

from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Object import *
from OPSI.Backend.Backend import *
from OPSI.Backend.Replicator import BackendReplicator

logger = Logger()

class CacheBackend(ConfigDataBackend):
	
	def __init__(self, **kwargs):
		
		self._workBackend = None
		self._serviceBackend = None
		self._clientId = None
		self._depotId = None
		
		for (option, value) in kwargs.items():
			option = option.lower()
			if option in ('workbackend',):
				self._workBackend = value
			if option in ('servicebackend',):
				self._serviceBackend = value
			if option in ('clientid',):
				self._clientId = forceHostId(value)
			if option in ('depotid',):
				self._depotId = forceHostId(value)
			
		if not self._workBackend:
			raise Exception(u"Work backend undefined")
		if not self._clientId:
			raise Exception(u"Client id undefined")
		if not self._depotId:
			raise Exception(u"Depot id undefined")
		
		self._createInstanceMethods()
	
	def _replicateServiceToWorkBackend(self):
		if not self._serviceBackend:
			raise Exception(u"Service backend undefined")
		br = BackendReplicator(readBackend = self._serviceBackend, writeBackend = self._workBackend)
		br.replicate(
			serverIds  = [ ],
			depotIds   = [ self._depotId ],
			clientIds  = [ self._clientId ],
			groupIds   = [ ],
			productIds = [ ],
			audit = False)
		
	def _createInstanceMethods(self):
		for member in inspect.getmembers(ConfigDataBackend, inspect.ismethod):
			methodName = member[0]
			if methodName.startswith('_'):
				continue
			
			(argString, callString) = getArgAndCallString(member[1])
			
			logger.debug2(u"Adding method '%s' to execute on work backend" % methodName)
			exec(u'def %s(self, %s): return self._executeOnWorkBackend("%s", %s)' % (methodName, argString, methodName, callString))
			setattr(self, methodName, new.instancemethod(eval(methodName), self, self.__class__))
	
	def _executeOnWorkBackend(self, methodName, **kwargs):
		logger.info(u"Executing method '%s' on work backend" % methodName)
		meth = getattr(self._workBackend, methodName)
		return meth(**kwargs)


if (__name__ == '__main__'):
	logger.setConsoleColor(True)
	logger.setConsoleLevel(LOG_NOTICE)
	serviceBackend = JSONRPCBackend(
		address  = 'https://bonifax.uib.local:4447/rpc',
		username = 'cachetest.uib.local',
		password = '12c1e40a6d3038d3eb2b4d489e978973')
	cb = CacheBackend(
		workDatabase   = ':memory:',
		serviceBackend = serviceBackend,
		depotId        = 'bonifax.uib.local',
		clientId       = 'cachetest.uib.local'
	)
	cb._replicateServiceToWorkBackend()
	
	#cb.host_insertObject( OpsiClient(id = 'test1.uib.local', description = 'description') )
	print cb.host_getObjects()
	#print cb._workBackend._sql.getSet('select * from HOST')
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
