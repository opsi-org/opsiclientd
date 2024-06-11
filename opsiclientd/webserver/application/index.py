# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from opsicommon.logging import get_logger
from starlette.status import HTTP_308_PERMANENT_REDIRECT

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
	<a href="/"><p id="title">opsiclientd on host %(hostname)s</p></a>
	<div class="mainpage-link-box">
		<ul>
			<li><a target="_blank" href="/info">info page</a></li>
			<li><a target="_blank" href="/log_viewer">log viewer</a></li>
			<li><a target="_blank" href="/interface/opsiclientd">control interface</a></li>
			<li><a target="_blank" href="/interface/kiosk">kiosk interface</a></li>
			<li><a target="_blank" href="/interface/rpc">cache service interface</a></li>
		</ul>
	</div>
</body>
</html>
"""

logger = get_logger()
router = APIRouter()


@router.get("/")
def index_page() -> HTMLResponse:
	return HTMLResponse(INDEX_PAGE % {"hostname": get_opsiclientd().config.get("global", "host_id")})


@router.get("/favicon.ico")
def favicon() -> RedirectResponse:
	return RedirectResponse("/static/favicon.ico", status_code=HTTP_308_PERMANENT_REDIRECT)


def setup(app: FastAPI) -> None:
	static_dir = get_opsiclientd().config.get("control_server", "static_dir")
	logger.info("Mounting static dir %r as /static", static_dir)
	app.mount("/static", StaticFiles(directory=static_dir))
	app.include_router(router)
