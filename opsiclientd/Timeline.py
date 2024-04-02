# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Event-Timeline.

Timeline event attributes:
* icon - url. This image will appear next to the title text in the timeline if (no end date) or (durationEvent = false).
	If a start and end date are supplied, and durationEvent is true, the icon is not shown.
	If icon attribute is not set, a default icon from the theme is used.
* image - url to an image that will be displayed in the bubble
* link - url. The bubble's title text be a hyper-link to this address.
* color - color of the text and tape (duration events) to display in the timeline.
	If the event has durationEvent = false, then the bar's opacity will be applied (default 20%). See durationEvent, above.
* textColor - color of the label text on the timeline. If not set, then the color attribute will be used.
* tapeImage and tapeRepeat Sets the background image and repeat style for the event's tape (or 'bar') on the Timeline.
	Overrides the color setting for the tape. Repeat style should be one of {repeat | repeat-x | repeat-y}, repeat is the default.
	See the Cubism example for a demonstration. Only applies to duration events.
* caption - additional event information shown when mouse is hovered over the Timeline tape or label. Uses the html title property.
	Looks like a tooltip. Plain text only. See the cubism example.
* classname - added to the HTML classnames for the event's label and tape divs.
	Eg classname attribute 'hot_event' will result in div classes of 'timeline-event-label hot_event' and 'timeline-event-tape hot_event'
	for the event's Timeline label and tape, respectively.
* description - will be displayed inside the bubble with the event's title and image.
"""

import os
import sqlite3
import threading
import time
from typing import Any

from OPSI.Backend.SQLite import SQLite  # type: ignore[import]
from OPSI.Util import timestamp  # type: ignore[import]
from opsicommon.logging import get_logger
from opsicommon.types import forceBool, forceInt, forceOpsiTimestamp, forceUnicode
from opsicommon.utils import Singleton

from opsiclientd.Config import Config

config = Config()

logger = get_logger("opsiclientd")

TIMELINE_IMAGE_URL = "/static/timeline/timeline_js/images/"
HTML_HEAD = """
<script type="text/javascript">
Timeline_ajax_url   = "/static/timeline/timeline_ajax/simile-ajax-api.js";
Timeline_urlPrefix  = "/static/timeline/timeline_js/";
Timeline_parameters = "bundle=true";
</script>
<script src="/static/timeline/timeline_js/timeline-api.js" type="text/javascript">
</script>
<script type="text/javascript">
var timeline_data;
var timeline;
var eventSource;

function updateEventData() {
	var req = new XMLHttpRequest();
	req.addEventListener("load", function() {
		timeline_data = JSON.parse(this.responseText);
		eventSource.clear();
		eventSource.loadJSON(timeline_data, '.');
		//timeline.layout();
		setTimeout(updateEventData, 5000);
	});
	req.open("GET", "/info/timeline_event_data");
	req.send();
}

function onLoad() {
	eventSource = new Timeline.DefaultEventSource();
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
	timeline = Timeline.create(document.getElementById("opsiclientd-timeline"), bandInfos);
	updateEventData();
}

var resizeTimerID = null;
function onResize() {
	if (resizeTimerID == null) {
		resizeTimerID = window.setTimeout(function() {
			resizeTimerID = null;
			timeline.layout();
		}, 500);
	}
}
</script>
"""


class Timeline(metaclass=Singleton):
	"""Timeline"""

	_initialized = False

	def __init__(self) -> None:
		if self._initialized:
			return
		self._initialized = True

		self._sql: SQLite | None = None
		self._db_lock = threading.Lock()
		self._stopped = False

	def start(self) -> None:
		db_file = config.get("global", "timeline_db")
		logger.notice("Starting timeline (database location: %s)", db_file)
		try:
			self._createDatabase()
		except sqlite3.DatabaseError as err:
			logger.error("Failed to connect to database %s: %s, recreating database", db_file, err)
			self._createDatabase(delete_existing=True)
		self._cleanupDatabase()

	def stop(self) -> None:
		self._stopped = True
		end = forceOpsiTimestamp(timestamp())

		if self._sql:
			with self._db_lock, self._sql.session() as session:
				self._sql.update(session, "EVENT", "`durationEvent` = 1 AND `end` is NULL", {"end": end})

	def getEventData(self) -> dict[str, Any]:
		events = []
		now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.localtime())
		for event in self.getEvents():
			event["icon"] = TIMELINE_IMAGE_URL + "gray-circle.png"
			event["start"] = event["start"].replace(" ", "T") + "+00:00"
			if event["end"]:
				event["end"] = event["end"].replace(" ", "T") + "+00:00"
			else:
				if event["durationEvent"]:
					event["end"] = now
			if event["description"]:
				event["description"] = event["description"].replace("\n", "<br />")
			if event["isError"]:
				event["color"] = "#A74141"
				event["textColor"] = "#A74141"
				event["icon"] = TIMELINE_IMAGE_URL + "dark-red-circle.png"
			elif event["category"] in ("event_processing", "event_occurrence"):
				event["color"] = "#D7CB1E"
				event["textColor"] = "#D7CB1E"
			elif event["category"] in ("opsiclientd_running",):
				event["color"] = "#80A63D"
				event["textColor"] = "#80A63D"
				event["icon"] = TIMELINE_IMAGE_URL + "dull-green-circle.png"
			elif event["category"] in ("block_login", "system"):
				event["color"] = "#A74141"
				event["textColor"] = "#A74141"
				event["icon"] = TIMELINE_IMAGE_URL + "dark-red-circle.png"
			elif event["category"] in ("product_caching",):
				event["color"] = "#6BABDF"
				event["textColor"] = "#6BABDF"
			elif event["category"] in ("config_sync",):
				event["color"] = "#69DFD0"
				event["textColor"] = "#69DFD0"
			elif event["category"] in ("user_interaction",):
				event["color"] = "#B46ADF"
				event["textColor"] = "#B46ADF"
				event["icon"] = TIMELINE_IMAGE_URL + "dull-blue-circle.png"
			elif event["category"] in ("wait",):
				event["color"] = "#DFA86C"
				event["textColor"] = "#DFA86C"
			del event["isError"]
			del event["category"]
			del event["id"]
			events.append(event)
		return {"dateTimeFormat": "iso8601", "events": events}

	def getHtmlHead(self) -> str:
		now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.localtime())
		return HTML_HEAD % {"date": now}

	def _cleanupDatabase(self) -> None:
		assert self._sql
		with self._db_lock, self._sql.session() as session:
			try:
				self._sql.execute(session, f'delete from EVENT where `start` < "{timestamp(time.time() - 7*24*3600)}"')
				self._sql.update(session, "EVENT", "`durationEvent` = 1 AND `end` is NULL", {"durationEvent": False})
			except Exception as cleanup_error:
				logger.error(cleanup_error)

	def _createDatabase(self, delete_existing: bool = False) -> None:
		timelineDB = config.get("global", "timeline_db")
		timelineFolder = os.path.dirname(timelineDB)
		if not os.path.exists(timelineFolder):
			logger.debug("Creating missing directory '%s'", timelineFolder)
			os.makedirs(timelineFolder)

		if delete_existing and os.path.exists(timelineDB):
			logger.notice("Deleting an recreating timeline database: %s", timelineDB)
			os.remove(timelineDB)

		self._sql = SQLite(database=timelineDB, databaseCharset="utf-8")
		with self._db_lock, self._sql.session() as session:
			tables = self._sql.getTables(session)
			if "EVENT" not in tables:
				logger.debug("Creating table EVENT")
				table = f"""CREATE TABLE `EVENT` (
						`id` integer NOT NULL {self._sql.AUTOINCREMENT},
						`title` varchar(255) NOT NULL,
						`category` varchar(64),
						`isError` bool,
						`durationEvent` bool,
						`description` varchar(1024),
						`start` TIMESTAMP,
						`end` TIMESTAMP,
						PRIMARY KEY (`id`)
					) {self._sql.getTableCreationOptions('EVENT')};
					"""
				logger.debug(table)
				self._sql.execute(session, table)
				self._sql.execute(session, "CREATE INDEX `category` on `EVENT` (`category`);")
				self._sql.execute(session, "CREATE INDEX `start` on `EVENT` (`start`);")

	def addEvent(
		self,
		title: str,
		description: str = "",
		isError: bool = False,
		category: str | None = None,
		durationEvent: bool = False,
		start: str | None = None,
		end: str | None = None,
	) -> int:
		if self._stopped or not self._sql:
			return -1

		with self._db_lock, self._sql.session() as session:
			try:
				if category:
					category = forceUnicode(category)
				if not start:
					start = timestamp()
				start = forceOpsiTimestamp(start)

				if end:
					end = forceOpsiTimestamp(end)
					durationEvent = True

				event = {
					"title": forceUnicode(title),
					"category": category,
					"description": forceUnicode(description),
					"isError": forceBool(isError),
					"durationEvent": forceBool(durationEvent),
					"start": start,
					"end": end,
				}
				try:
					return self._sql.insert(session, "EVENT", event)
				except sqlite3.DatabaseError as db_error:
					logger.error("Failed to add event '%s': %s, recreating database", title, db_error)
					self._sql.delete_db()
					self._createDatabase(delete_existing=True)
					return self._sql.insert(session, "EVENT", event)
			except Exception as add_error:
				logger.error("Failed to add event '%s': %s", title, add_error)
		return -1

	def setEventEnd(self, eventId: int, end: str | None = None) -> int:
		if self._stopped or not self._sql:
			return -1

		with self._db_lock, self._sql.session() as session:
			try:
				eventId = forceInt(eventId)
				if not end:
					end = timestamp()
				end = forceOpsiTimestamp(end)
				return self._sql.update(session, "EVENT", f"`id` = {eventId}", {"end": end, "durationEvent": True})
			except Exception as end_error:
				logger.error("Failed to set end of event '%s': %s", eventId, end_error)
		return -1

	def getEvents(self) -> list[dict[str, Any]]:
		if self._stopped or not self._sql:
			return []

		with self._db_lock, self._sql.session() as session:
			return self._sql.getSet(session, "select * from EVENT")
