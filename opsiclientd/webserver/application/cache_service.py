# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0


import json

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from opsicommon.logging import get_logger
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from opsiclientd.Config import Config
from opsiclientd.webserver.application import INTERFACE_PAGE, get_opsiclientd
from opsiclientd.webserver.rpc.control import get_cache_service_interface
from opsiclientd.webserver.rpc.jsonrpc import JSONRPC20Error, JSONRPC20ErrorResponse, process_request, serialize_data

logger = get_logger()
config = Config()
jsonrpc_router = APIRouter()
interface_router = APIRouter()


@interface_router.get("/")
def index_page() -> HTMLResponse:
	interface = get_cache_service_interface(get_opsiclientd())

	methods = {}
	for method_name, meth_if in interface.get_interface().items():
		methods[method_name] = meth_if.params

	return HTMLResponse(
		INTERFACE_PAGE
		% {
			"title": "opsiclientd cache service interface page",
			"jsonrpc_path": "/rpc",
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
	server_version = "4.2.0.0"
	try:
		opsiclientd = get_opsiclientd()
		cache_service = opsiclientd.getCacheService()
		server_version = cache_service.getConfigCacheState().get("server_version", server_version)
		response = await process_request(interface=get_cache_service_interface(opsiclientd), request=request, response=response)
	except Exception as err:
		response.status_code = HTTP_500_INTERNAL_SERVER_ERROR
		jsonrpc_response = JSONRPC20ErrorResponse(id=0, error=JSONRPC20Error(message=str(err)))
		data = serialize_data(jsonrpc_response, "json")
		response.headers["Content-Type"] = "application/json"
		response.headers["content-length"] = str(len(data))
		response.body = data
	response.headers.append("server", f"opsiclientd config cache service {server_version}")
	return response


def setup(app: FastAPI) -> None:
	app.include_router(interface_router, prefix="/interface/rpc")
	app.include_router(jsonrpc_router, prefix="/rpc")
