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
   @author: Jan Schneider <j.schneider@uib.de>
   @license: GNU General Public License version 2
"""

__version__ = '4.0.2'

# Imports
import sys, os, locale

from OPSI import System
from OPSI.Logger import *
from OPSI.Backend.JSONRPC import JSONRPCBackend

logger = Logger()

try:
	#reading the opsiclientd.conf for the machine-account
	basedir = os.getcwd()
	pathToConf = os.path.join(basedir, "opsicliend\opsiclientd.conf")
	username = None
	password = None
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
	
	# Trying to fire Event gui_startup
	be.fireEvent("gui_startup")
	
	while True:
		if be.isEventRunning("gui_startup"):
			time.sleep(2)
		else:
			break
	sys.exit(0)
				
except:
	sys.exit(1)



