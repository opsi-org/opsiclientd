# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.CacheService                 =
   = = = = = = = = = = = = = = = = = = = = =
   
   This module is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2011 uib GmbH
   
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

# Import
import threading, time

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            CACHE SERVICE                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		self._stopped = False
		
	def initialize(self):
		pass
	
	def setCurrentProductSyncProgressObserver(self, currentProductSyncProgressObserver):
		pass
	
	def setOverallProductSyncProgressObserver(self, overallProductSyncProgressObserver):
		pass
	
	def getProductCacheDir(self):
		return None
		
	def getProductSyncCompleted(self):
		return False
	
	def getConfigSyncCompleted(self):
		return False
	
	def cacheProducts(self, configService, productIds, waitForEnding=False):
		pass
	
	def freeProductCacheSpace(self, neededSpace = 0, neededProducts = []):
		pass
		
	def stop(self):
		self._stopped = True
		
	def run(self):
		while not self._stopped:
			time.sleep(1)
	

