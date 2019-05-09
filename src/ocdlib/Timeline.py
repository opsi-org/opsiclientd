# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2011-2019 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Event-Timeline.

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


:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import json
import os
import time
import threading

from OPSI.Logger import Logger
from OPSI.Types import forceBool, forceInt, forceOpsiTimestamp, forceUnicode
from OPSI.Util import timestamp
from OPSI.Backend.SQLite import SQLite

from ocdlib.Config import Config

logger = Logger()
config = Config()

TIMELINE_IMAGE_URL = u'/timeline/timeline_js/images/'
htmlHead = u'''
<script type="text/javascript">
// <![CDATA[
Timeline_ajax_url   = "/timeline/timeline_ajax/simile-ajax-api.js";
Timeline_urlPrefix  = "/timeline/timeline_js/";
Timeline_parameters = "bundle=true";
// ]]>
</script>
<script src="/timeline/timeline_js/timeline-api.js" type="text/javascript">
</script>
<script type="text/javascript">
// <![CDATA[
var timeline_data = %(data)s;
var tl;
function onLoad() {
	var eventSource = new Timeline.DefaultEventSource();
	var bandInfos = [
		Timeline.createBandInfo({
			width:          "80%%",
			intervalUnit:   Timeline.DateTime.MINUTE,
			intervalPixels: 200,
			eventSource:    eventSource,
			date:           "%(date)s",
			layout:         'original'  // original, overview, detailed
		}),
		Timeline.createBandInfo({
			width:          "10%%",
			intervalUnit:   Timeline.DateTime.HOUR,
			intervalPixels: 300,
			eventSource:    eventSource,
			date:           "%(date)s",
			layout:         'overview'  // original, overview, detailed
		}),
		Timeline.createBandInfo({
			width:          "10%%",
			intervalUnit:   Timeline.DateTime.DAY,
			intervalPixels: 600,
			eventSource:    eventSource,
			date:           "%(date)s",
			layout:         'overview'  // original, overview, detailed
		})
	];
	bandInfos[1].syncWith = 0;
	bandInfos[1].highlight = true;
	bandInfos[2].syncWith = 0;
	bandInfos[2].highlight = true;
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
// ]]>
</script>
'''


class TimelineImplementation(object):
	def __init__(self):
		if not os.path.exists(os.path.dirname(config.get('global', 'timeline_db'))):
			os.makedirs(os.path.dirname(config.get('global', 'timeline_db')))
		self._sql = SQLite(
			database=config.get('global', 'timeline_db'),
			synchronous=False,
			databaseCharset='utf-8'
		)
		self._dbLock = threading.Lock()
		self._createDatabase()
		self._cleanupDatabase()
		self._stopped = False

	def stop(self):
		self._stopped = True
		end = forceOpsiTimestamp(timestamp())

		with self._dbLock:
			self._sql.update('EVENT', '`durationEvent` = 1 AND `end` is NULL', {'end': end})

	def getHtmlHead(self):
		events = []
		now = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.localtime())
		for event in self.getEvents():
			event['icon'] = TIMELINE_IMAGE_URL + u"gray-circle.png"
			event['start'] = event['start'].replace(u' ', u'T') + '+00:00'
			if event['end']:
				event['end'] = event['end'].replace(u' ', u'T') + '+00:00'
			else:
				if event['durationEvent']:
					event['end'] = now
			if event['description']:
				event['description'] = event['description'].replace(u'\n', u'<br />')
			if event['isError']:
				event['color'] = u"#A74141"
				event['textColor'] = u"#A74141"
				event['icon'] = TIMELINE_IMAGE_URL + u"dark-red-circle.png"
			elif event['category'] in ('event_processing', 'event_occurrence'):
				event['color'] = u"#D7CB1E"
				event['textColor'] = u"#D7CB1E"
			elif event['category'] in ('opsiclientd_running',):
				event['color'] = u"#80A63D"
				event['textColor'] = u"#80A63D"
				event['icon'] = TIMELINE_IMAGE_URL + u"dull-green-circle.png"
			elif event['category'] in ('block_login', 'system'):
				event['color'] = u"#A74141"
				event['textColor'] = u"#A74141"
				event['icon'] = TIMELINE_IMAGE_URL + u"dark-red-circle.png"
			elif event['category'] in ('product_caching',):
				event['color'] = u"#6BABDF"
				event['textColor'] = u"#6BABDF"
			elif event['category'] in ('config_sync',):
				event['color'] = u"#69DFD0"
				event['textColor'] = u"#69DFD0"
			elif event['category'] in ('user_interaction',):
				event['color'] = u"#B46ADF"
				event['textColor'] = u"#B46ADF"
				event['icon'] = TIMELINE_IMAGE_URL + u"dull-blue-circle.png"
			elif event['category'] in ('wait',):
				event['color'] = u"#DFA86C"
				event['textColor'] = u"#DFA86C"
			del event['isError']
			del event['category']
			del event['id']
			events.append(event)
		return htmlHead % {
			'data': json.dumps({'dateTimeFormat': 'iso8601', 'events': events}),
			'date': now
		}

	def _cleanupDatabase(self):
		with self._dbLock:
			try:
				self._sql.execute('delete from EVENT where `start` < "%s"' % timestamp((time.time() - 7*24*3600)))
				self._sql.update('EVENT', '`durationEvent` = 1 AND `end` is NULL', {'durationEvent': False})
			except Exception as cleanupError:
				logger.error(cleanupError)

	def _createDatabase(self):
		with self._dbLock:
			tables = self._sql.getTables()
			if 'EVENT' not in tables:
				logger.debug(u'Creating table EVENT')
				table = u'''CREATE TABLE `EVENT` (
						`id` integer NOT NULL ''' + self._sql.AUTOINCREMENT + ''',
						`title` varchar(255) NOT NULL,
						`category` varchar(64),
						`isError` bool,
						`durationEvent` bool,
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

	def addEvent(self, title, description=u'', isError=False, category=None, durationEvent=False, start=None, end=None):
		if self._stopped:
			return -1

		with self._dbLock:
			try:
				if category:
					category = forceUnicode(category)
				if not start:
					start = timestamp()
				start = forceOpsiTimestamp(start)
				if end:
					end = forceOpsiTimestamp(start)
					durationEvent = True
				return self._sql.insert('EVENT', {
					'title':         forceUnicode(title),
					'category':      category,
					'description':   forceUnicode(description),
					'isError':       forceBool(isError),
					'durationEvent': forceBool(durationEvent),
					'start':         start,
					'end':           end,
				})
			except Exception as addError:
				logger.error(u"Failed to add event '%s': %s" % (title, addError))

	def setEventEnd(self, eventId, end=None):
		if self._stopped:
			return -1

		with self._dbLock:
			try:
				eventId = forceInt(eventId)
				if not end:
					end = timestamp()
				end = forceOpsiTimestamp(end)
				return self._sql.update('EVENT', '`id` = %d' % eventId, {'end': end, 'durationEvent': True})
			except Exception as endError:
				logger.error(u"Failed to set end of event '%s': %s" % (eventId, endError))

	def getEvents(self):
		if self._stopped:
			return {}

		with self._dbLock:
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
