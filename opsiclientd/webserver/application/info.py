# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from opsicommon.logging import get_logger

from opsiclientd.Config import Config
from opsiclientd.Timeline import Timeline

INFO_PAGE = """<!DOCTYPE html>
<html>
<head>
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<title>%(hostname)s opsi client daemon info</title>
	<link rel="stylesheet" type="text/css" href="/static/opsiclientd.css" />
	%(head)s
	<script type="text/javascript">
	function onPageLoad(){
		onLoad();
	}
	</script>
</head>
<body onload="onPageLoad();" onresize="onResize();">
	<p id="title">opsi client daemon info</p>
	<div id="infopage-timeline-box">
		<p id="infopage-timeline-title">Timeline</p>
		<div class="timeline-default" id="opsiclientd-timeline" style="height: 400px; border: 1px solid #aaaaaa"></div>
	</div>
</body>
</html>
"""

logger = get_logger()
config = Config()
info_router = APIRouter()


@info_router.get("/")
def index_page() -> HTMLResponse:
	timeline = Timeline()
	return HTMLResponse(
		INFO_PAGE
		% {
			"head": timeline.getHtmlHead(),
			"hostname": config.get("global", "host_id"),
		}
	)


@info_router.get("/timeline_event_data")
def event_data() -> JSONResponse:
	return JSONResponse(Timeline().getEventData())


def setup(app: FastAPI) -> None:
	app.include_router(info_router, prefix="/info")
