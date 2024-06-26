# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import json

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from opsicommon.logging import get_logger

from opsiclientd.webserver.application import INTERFACE_PAGE, get_opsiclientd
from opsiclientd.webserver.rpc.control import get_control_interface
from opsiclientd.webserver.rpc.jsonrpc import process_request

logger = get_logger()
interface_router = APIRouter()
jsonrpc_router = APIRouter()


@interface_router.get("/")
def index_page() -> HTMLResponse:
	interface = get_control_interface(get_opsiclientd())

	methods = {}
	for method_name, meth_if in interface.get_interface().items():
		methods[method_name] = meth_if.params

	return HTMLResponse(
		INTERFACE_PAGE
		% {
			"title": "opsiclientd interface page",
			"jsonrpc_path": "/opsiclientd",
			"methods": json.dumps(methods),
		}
	)


@jsonrpc_router.head("")
async def jsonrpc_head() -> Response:
	return Response()


@jsonrpc_router.get("")
@jsonrpc_router.post("")
@jsonrpc_router.get("{any:path}")
@jsonrpc_router.post("{any:path}")
async def jsonrpc(request: Request, response: Response) -> Response:
	return await process_request(interface=get_control_interface(get_opsiclientd()), request=request, response=response)


def setup(app: FastAPI) -> None:
	app.include_router(interface_router, prefix="/interface/opsiclientd")
	app.include_router(jsonrpc_router, prefix="/opsiclientd")
