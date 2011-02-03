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

import time
from sys import version_info
if (version_info >= (2,6)):
	import json
else:
	import simplejson as json

from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Util import timestamp
from OPSI.Backend.SQLite import SQLite

from ocdlib.Config import Config

logger = Logger()
config = Config()

htmlHead = u'''
<script src="/timeline/timeline_js/timeline-api.js" type="text/javascript"></script>
<script>
Timeline_ajax_url   = "/timeline/timeline_ajax/simile-ajax-api.js";
Timeline_urlPrefix  = "/timeline/timeline_js/";
Timeline_parameters = "bundle=true";
var timeline_data   = %(data)s;
var tl;
function onLoad() {
	var eventSource = new Timeline.DefaultEventSource();
	var bandInfos = [
		Timeline.createBandInfo({
			width:          "70%%",
			intervalUnit:   Timeline.DateTime.DAY,
			intervalPixels: 100,
			eventSource:    eventSource,
			date:           Date(%(date1)s),
		}),
		Timeline.createBandInfo({
			width:          "30%%",
			intervalUnit:   Timeline.DateTime.WEEK,
			intervalPixels: 200,
			eventSource:    eventSource,
			date:           Date(%(date2)s),
		})
	];
	bandInfos[1].syncWith = 0;
	bandInfos[1].highlight = true;
	tl = Timeline.create(document.getElementById("opsiclientd-timeline"), bandInfos);
	eventSource.loadJSON(timeline_data, '.');
}

var resizeTimerID = null;
function onResize() {
	if (resizeTimerID == null) {
		resizeTimerID = window.setTimeout(function() {
			resizeTimerID = null;
			tl.layout();
		}, 500);
	}
}
</script>
'''

class TimelineImplementation(object):
	def __init__(self):
		self._sql = SQLite(
			database        = config.get('global', 'timeline_db'),
			synchronous     = False,
			databaseCharset = 'utf-8'
		)
		self._createDatabase()
	
	def getHtmlHead(self):
		return htmlHead % {
			#'data': json.dumps({'dateTimeFormat': 'Gregorian', 'events': self.getEvents()}),
			'data': '''{
			'dateTimeFormat': 'iso8601',
			'wikiURL': "http://simile.mit.edu/shelf/",
			'wikiSection': "Simile Cubism Timeline",
			
			'events' : [
				{'start': '1924',
				'title': 'Barfusserkirche',
				'description': 'by Lyonel Feininger, American/German Painter, 1871-1956',
				'image': 'http://images.allposters.com/images/AWI/NR096_b.jpg',
				'link': 'http://www.allposters.com/-sp/Barfusserkirche-1924-Posters_i1116895_.htm'
				},
				{'start': '2013',
				'end': '2029',
				'title': 'Three Figures',
				'description': 'by Kasimir Malevich, Ukrainian Painter, 1878-1935',
				'image': 'http://images.allposters.com/images/BRGPOD/75857_b.jpg',
				'link': 'http://www.allposters.com/-sp/Three-Figures-1913-28-Posters_i1349989_.htm'
				}
			]
			};
			''',
			'date1': time.strftime('%Y,%m-1,%d,%H,%M,%S', time.localtime()),
			'date2': time.strftime('%Y,%m-1,%d,%H,%M,%S', time.localtime())
		}
	
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
		events = []
		for res in self._sql.getSet('select * from EVENT'):
			if res['end']:
				res['durationEvent'] = True
			else:
				res['durationEvent'] = False
			events.append(res)
		return events
	
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


