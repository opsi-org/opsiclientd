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
   
   Timeline event attributes:
      * icon - url. This image will appear next to the title text in the timeline if (no end date) or (durationEvent = false). If a start and end date are supplied, and durationEvent is true, the icon is not shown. If icon attribute is not set, a default icon from the theme is used.
      * image - url to an image that will be displayed in the bubble
      * link - url. The bubble's title text be a hyper-link to this address.
      * color - color of the text and tape (duration events) to display in the timeline. If the event has durationEvent = false, then the bar's opacity will be applied (default 20%). See durationEvent, above.
      * textColor - color of the label text on the timeline. If not set, then the color attribute will be used.
      * tapeImage and tapeRepeat Sets the background image and repeat style for the event's tape (or 'bar') on the Timeline. Overrides the color setting for the tape. Repeat style should be one of {repeat | repeat-x | repeat-y}, repeat is the default. See the Cubism example for a demonstration. Only applies to duration events.
      * caption - additional event information shown when mouse is hovered over the Timeline tape or label. Uses the html title property. Looks like a tooltip. Plain text only. See the cubism example.
      * classname - added to the HTML classnames for the event's label and tape divs. Eg classname attribute 'hot_event' will result in div classes of 'timeline-event-label hot_event' and 'timeline-event-tape hot_event' for the event's Timeline label and tape, respectively.
      * description - will be displayed inside the bubble with the event's title and image.
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
<style type="text/css">
.timeline-default {
	font-family: Trebuchet MS, Helvetica, Arial, sans serif;
	font-size: 8pt;
	border: 1px solid #aaa;
}
.timeline-event-bubble-title {
	font-weight: bold;
	border-bottom: 1px solid #888;
	margin-bottom: 0.5em;
	font-family: Trebuchet MS, Helvetica, Arial, sans serif;
	font-size: 8pt;
}
.timeline-event-bubble-body {
	font-family: Trebuchet MS, Helvetica, Arial, sans serif;
	font-size: 8pt;
}
.timeline-event-bubble-time {
	font-family: Trebuchet MS, Helvetica, Arial, sans serif;
	font-size: 8pt;
	margin-top: 10px;
}
</style>
<script>
Timeline_ajax_url   = "/timeline/timeline_ajax/simile-ajax-api.js";
Timeline_urlPrefix  = "/timeline/timeline_js/";
Timeline_parameters = "bundle=true";
</script>
<script src="/timeline/timeline_js/timeline-api.js" type="text/javascript"></script>
<script>
var timeline_data = %(data)s;
var tl;
function onLoad() {
	var eventSource = new Timeline.DefaultEventSource();
	var bandInfos = [
		Timeline.createBandInfo({
			width:          "70%%",
			intervalUnit:   Timeline.DateTime.MINUTE,
			intervalPixels: 100,
			eventSource:    eventSource,
			date:           Date(%(date1)s),
		}),
		Timeline.createBandInfo({
			width:          "30%%",
			intervalUnit:   Timeline.DateTime.HOUR,
			intervalPixels: 300,
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
		events = []
		for event in self.getEvents():
			event['icon'] = u"gray-circle.png"
			event['start'] = event['start'].replace(u' ', u'T') + '+00:00'
			if event['end']:
				event['durationEvent'] = True
				event['end'] = event['end'].replace(u' ', u'T') + '+00:00'
			else:
				event['durationEvent'] = False
				del event['end']
			if event['isError']:
				#event['classname'] = u"error-event"
				event['textColor'] = u"#660000"
				event['icon'] = u"dark-red-circle.png"
			del event['isError']
			del event['category']
			del event['id']
			events.append(event)
		return htmlHead % {
			'data': json.dumps({'dateTimeFormat': 'iso8601', 'events': events}),
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
					`isError` bool,
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
	
	def addEvent(self, title, description=u'', isError=False, category=None, start=None, end=None):
		if category:
			category = forceUnicode(category)
		if not start:
			start = timestamp()
		start = forceOpsiTimestamp(start)
		if end:
			end = forceOpsiTimestamp(start)
		return self._sql.insert('EVENT', {
			'title':       forceUnicode(title),
			'category':    category,
			'description': forceUnicode(description),
			'isError':     forceBool(isError),
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
		return self._sql.getSet('select * from EVENT')
	
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


