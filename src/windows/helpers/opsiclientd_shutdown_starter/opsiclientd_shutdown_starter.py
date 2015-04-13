# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =            opsiclientd_rpc            =
   = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd_rpc is part of the desktop management solution opsi
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
   @author: Erol Ueluekmen <e.ueluekmen@uib.de>
   @license: GNU General Public License version 2
"""

__version__ = '4.0.5'

# Imports
import sys, os, locale, time, base64, codecs

from OPSI import System
from OPSI.Logger import *
from OPSI.Backend.JSONRPC import JSONRPCBackend

from OPSI.Util import md5sum
from OPSI.Types import forceBool
from hashlib import md5
from twisted.conch.ssh import keys

mydebug = 1

logger = Logger()

try:
	#reading the opsiclientd.conf for the machine-account
	basedir = os.getcwd()
	pathToConf = os.path.join(basedir, "opsiclientd\opsiclientd.conf")
	username = None
	password = None
	
	myEvent = "gui_startup"
	# myEvent = "shutdown_install"
	if len(sys.argv) > 1: 
		myEvent = sys.argv[1] 
		
	if os.path.exists(pathToConf):
		f = open(pathToConf)
		lines = f.readlines()
		
		for line in lines:
			if line.lower().startswith(u"host_id"):
				username = line.split("=")[1].strip()
			elif line.lower().startswith(u"opsi_host_key"):
				password = line.split("=")[1].strip()
			if username and password:
				break
	

	# Connect local service
	be = JSONRPCBackend(username = username, password = password, address = u'https://localhost:4441/opsiclientd')
	if mydebug :
		print u"Backend connected."

	if forceBool(be.isInstallationPending()):
		if mydebug:
			print u"State installation pending detected, don't starting shutdown event."
		os.exit(0)
		
	# Check modules file
	try:
		modules = None
		helpermodules = {}
		## backendinfo = self._configService.backend_info()
		backendinfo = be.getBackendInfo()
		modules = backendinfo['modules']
		helpermodules = backendinfo['realmodules']
	
		if not modules.get('install_by_shutdown'):
			raise Exception(u"install_by_shutdown not available - module currently disabled")
		if not modules.get('customer'):
			raise Exception(u"install_by_shutdown not available - no customer set in modules file")
		if not modules.get('valid'):
			raise Exception(u"install_by_shutdown not available - modules file invalid")
		if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
			raise Exception(u"install_by_shutdown not available - modules file expired")

		if mydebug :
			print u"modules: passed first checkpoint."

		# logger.info(u"Verifying modules file signature")
		publicKey = keys.Key.fromString(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
		data = u''
		mks = modules.keys()
		mks.sort()
		for module in mks:
			if module in ('valid', 'signature'):
				continue
			if helpermodules.has_key(module):
				val = helpermodules[module]
				if int(val) > 0:
					modules[module] = True
			else:
				val = modules[module]
				if (val == False): val = 'no'
				if (val == True):  val = 'yes'
			data += u'%s = %s\r\n' % (module.lower().strip(), val)
		if not bool(publicKey.verify(md5(data).digest(), [ long(modules['signature']) ])):
			raise Exception(u"install_by_shutdown not available - modules file invalid")
		## logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
		if mydebug :
			print u"Modules file signature verified (customer: %s)" % modules.get('customer')

	except Exception, e:
		## self.disconnectConfigService()
		raise

	if mydebug :
		print u"Check completed."


	# Trying to fire myEvent
	be.fireEvent(myEvent)
	if mydebug :
		print u"Event fired"
	time.sleep(4)
	while True:
		if be.isEventRunning(myEvent):
			time.sleep(5)
		elif be.isEventRunning(myEvent+"{user_logged_in}"):
			time.sleep(5)
		else:
			break
	if mydebug :
		time.sleep(10)
		print u"Task completed."
	sys.exit(0)
				
except Exception, e:
	print e
	sys.exit(1)



