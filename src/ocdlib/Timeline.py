# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.Timeline                     =
   = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
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

from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Util import timestamp
from OPSI.Backend.SQLite import SQLite

from ocdlib.Config import Config

logger = Logger()
config = Config()

class TimelineImplementation(object):
	def __init__(self):
		self._sql = SQLite(
			database        = config.get('global', 'timeline_db'),
			synchronous     = False,
			databaseCharset = 'utf-8'
		)
		self._createDatabase()
		
	def _createDatabase(self):
		tables = self._sql.getTables()
		if not 'EVENT' in tables.keys():
			logger.debug(u'Creating table EVENT')
			table = u'''CREATE TABLE `EVENT` (
					`id` integer NOT NULL ''' + self._sql.AUTOINCREMENT + ''',
					`title` varchar(255) NOT NULL,
					`category` varchar(64),
					`description` varchar(1024),
					`start` TIMESTAMP,
					`end` TIMESTAMP,
					PRIMARY KEY (`id`)
				) %s;
				''' % self._sql.getTableCreationOptions('EVENT')
			logger.debug(table)
			self._sql.execute(table)
			self._sql.execute('CREATE INDEX `category` on `EVENT` (`category`);')
			self._sql.execute('CREATE INDEX `start` on `EVENT` (`start`);')
	
	def addEvent(self, title, description=u'', category=None, start=None, end=None):
		title = forceUnicode(title)
		description = forceUnicode(description)
		if category:
			category = forceUnicode(category)
		if not start:
			start = timestamp()
		start = forceOpsiTimestamp(start)
		if end:
			end = forceOpsiTimestamp(start)
		return self._sql.insert('EVENT', {
			'title':       title,
			'category':    category,
			'description': description,
			'start':       start,
			'end':         end,
		})
	
	def setEventEnd(self, eventId, end=None):
		eventId = forceInt(eventId)
		if not end:
			end = timestamp()
		end = forceOpsiTimestamp(start)
		return self._sql.update('EVENT', '`id` = %d' % eventId, { 'end': end })
	
	def getEvents(self):
		result = []
		for res in self._sql.getSet('select * from EVENT'):
			if res['end']:
				res['isDuration'] = True
			else:
				res['isDuration'] = False
			result.append(res)
		return result
	
class Timeline(TimelineImplementation):
	# Storage for the instance reference
	__instance = None
	
	def __init__(self):
		""" Create singleton instance """
		
		# Check whether we already have an instance
		if Timeline.__instance is None:
			# Create and remember instance
			Timeline.__instance = TimelineImplementation()
		
		# Store instance reference as the only member in the handle
		self.__dict__['_Timeline__instance'] = Timeline.__instance
	
	
	def __getattr__(self, attr):
		""" Delegate access to implementation """
		return getattr(self.__instance, attr)

	def __setattr__(self, attr, value):
		""" Delegate access to implementation """
		return setattr(self.__instance, attr, value)


