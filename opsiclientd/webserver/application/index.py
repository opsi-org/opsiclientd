# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from opsiclientd.webserver.application import get_opsiclientd

INDEX_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">

<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<title>opsi client daemon</title>
	<link rel="stylesheet" type="text/css" href="/static/opsiclientd.css" />
</head>
<body>
	<p id="title">opsiclientd on host %(hostname)s</p>
	<div class="mainpage-link-box">
		<ul>
			<li><a target="_blank" href="info.html">opsiclientd info page</a></li>
			<li><a target="_blank" href="log_viewer.html">opsiclientd log viewer</a></li>
			<li><a target="_blank" href="interface">opsiclientd control interface</a></li>
		</ul>
	</div>

</body>
</html>
"""

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index_page() -> str:
	return INDEX_PAGE % {"hostname": get_opsiclientd().config.get("global", "host_id")}


def setup(app: FastAPI) -> None:
	app.mount("/static", StaticFiles(directory=get_opsiclientd().config.get("control_server", "static_dir")))
	app.include_router(router)
