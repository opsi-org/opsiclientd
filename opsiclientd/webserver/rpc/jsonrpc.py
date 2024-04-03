# -*- coding: utf-8 -*-

# opsiconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2008-2024 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
jsonrpc
"""

from __future__ import annotations

import asyncio
import time
import urllib.parse
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Literal

import msgspec
from fastapi import HTTPException
from fastapi.requests import Request
from fastapi.responses import Response
from opsicommon.logging import get_logger
from opsicommon.objects import deserialize, serialize
from opsicommon.utils import compress_data, decompress_data
from starlette.concurrency import run_in_threadpool

from opsiclientd.webserver.rpc.interface import Interface

logger = get_logger()

COMPRESS_MIN_SIZE = 10000


def utcnow() -> datetime:
	return datetime.now(tz=timezone.utc)


@dataclass(kw_only=True)
class RequestInfo:
	client: str = ""
	date: datetime = field(default_factory=utcnow)
	deprecated: bool = False
	duration: float = 0.0


@dataclass(kw_only=True)
class JSONRPCRequest:
	method: str
	id: int | str = 0
	params: list[Any] | tuple[Any, ...] | dict[str, Any] = field(default_factory=list)
	info: RequestInfo = field(default_factory=RequestInfo)


@dataclass
class JSONRPCResponse:
	id: int | str
	result: Any | None = None
	error: None = None


@dataclass
class JSONRPCErrorResponse:
	id: int | str
	error: Any | None
	result: None = None


@dataclass(kw_only=True)
class JSONRPC20Request:
	method: str
	id: int | str = 0
	params: list[Any] | tuple[Any, ...] | dict[str, Any] = field(default_factory=list)
	jsonrpc: str = "2.0"
	info: RequestInfo = field(default_factory=RequestInfo)


@dataclass
class JSONRPC20Response:
	id: int | str
	result: Any
	jsonrpc: str = "2.0"


@dataclass
class JSONRPC20Error:
	message: str
	code: int = 0
	data: dict[str, Any] = field(default_factory=dict)


@dataclass
class JSONRPC20ErrorResponse:
	id: int | str
	error: JSONRPC20Error
	jsonrpc: str = "2.0"


def get_compression(content_encoding: str) -> Literal["lz4", "deflate", "gzip"] | None:
	if not content_encoding:
		return None
	content_encoding = content_encoding.lower()
	if content_encoding == "identity":
		return None
	if "lz4" in content_encoding:
		return "lz4"
	if "deflate" in content_encoding:
		return "deflate"
	if "gzip" in content_encoding:
		return "gzip"
	raise ValueError(f"Unhandled Content-Encoding {content_encoding!r}")


def get_request_compression(request: Request) -> Literal["lz4", "deflate", "gz", "gzip"] | None:
	content_encoding = request.headers.get("content-encoding", "")
	logger.debug("Content-Encoding: %r", content_encoding)
	return get_compression(content_encoding)


def get_response_compression(request: Request) -> Literal["lz4", "deflate", "gz", "gzip"] | None:
	content_encoding = request.headers.get("accept-encoding", "")
	logger.debug("Accept-Encoding: %r", content_encoding)
	return get_compression(content_encoding)


def get_request_serialization(request: Request) -> Literal["msgpack", "json"] | None:
	content_type = request.headers.get("content-type")
	logger.debug("Content-Type: %r", content_type)
	if content_type:
		content_type = content_type.lower()
		if "msgpack" in content_type:
			return "msgpack"
		if "json" in content_type:
			return "json"
	return None


def get_response_serialization(request: Request) -> Literal["msgpack", "json"] | None:
	accept = request.headers.get("accept")
	logger.debug("Accept: %r", accept)
	if accept:
		accept = accept.lower()
		if "msgpack" in accept:
			return "msgpack"
		if "json" in accept:
			return "json"
	return None


msgpack_decoder = msgspec.msgpack.Decoder()
json_decoder = msgspec.json.Decoder()


def deserialize_data(data: bytes, serialization: str) -> Any:
	if serialization == "msgpack":
		return msgpack_decoder.decode(data)
	if serialization == "json":
		return json_decoder.decode(data)
	raise ValueError(f"Unhandled serialization {serialization!r}")


msgpack_encoder = msgspec.msgpack.Encoder()
json_encoder = msgspec.json.Encoder()


def serialize_data(data: Any, serialization: str) -> bytes:
	if serialization == "msgpack":
		return msgpack_encoder.encode(data)
	if serialization == "json":
		return json_encoder.encode(data)
	raise ValueError(f"Unhandled serialization {serialization!r}")


def jsonrpc_request_from_dict(data: dict[str, Any], client: str) -> JSONRPCRequest | JSONRPC20Request:
	if data.get("jsonrpc") == "2.0":
		return JSONRPC20Request(
			info=RequestInfo(client=client), id=data.get("id") or 0, method=data["method"], params=data.get("params") or []
		)
	return JSONRPCRequest(info=RequestInfo(client=client), id=data.get("id") or 0, method=data["method"], params=data.get("params") or [])


def jsonrpc_request_from_data(data: bytes, serialization: str, client: str = "") -> list[JSONRPCRequest | JSONRPC20Request]:
	dat = deserialize_data(data, serialization)
	if isinstance(dat, list):
		return [jsonrpc_request_from_dict(d, client) for d in dat]
	return [jsonrpc_request_from_dict(dat, client)]


def jsonrpc_response_from_dict(data: dict[str, Any]) -> JSONRPCResponse | JSONRPCErrorResponse | JSONRPC20Response | JSONRPC20ErrorResponse:
	rpc_id = data.get("id") or 0
	if data.get("jsonrpc") == "2.0":
		if data.get("error"):
			return JSONRPC20ErrorResponse(id=rpc_id, error=data["error"])
		return JSONRPC20Response(id=rpc_id, result=data.get("result"))
	if data.get("error"):
		return JSONRPCErrorResponse(id=rpc_id, error=data["error"])
	return JSONRPCResponse(id=rpc_id, result=data.get("result"))


def jsonrpc_response_from_data(
	data: bytes, serialization: str
) -> list[JSONRPCResponse | JSONRPCErrorResponse | JSONRPC20Response | JSONRPC20ErrorResponse]:
	dat = deserialize_data(data, serialization)
	if isinstance(dat, list):
		return [jsonrpc_response_from_dict(d) for d in dat]
	return [jsonrpc_response_from_dict(dat)]


async def execute_rpc(request: JSONRPC20Request | JSONRPCRequest, interface: Interface) -> Any:
	method_name = request.method
	params = request.params

	method_interface = interface.get_method_interface(method_name)
	if not method_interface:
		logger.warning("Invalid method %r", method_name)
		raise ValueError(f"Invalid method {method_name!r}")

	if method_interface.deprecated:
		warnings.warn(f"Client {request.info.client} is calling deprecated method {method_name!r}", DeprecationWarning)
		request.info.deprecated = True

	keywords = {}
	if isinstance(params, dict):
		keywords = await run_in_threadpool(deserialize, params)
		params = []
	else:
		if method_interface.keywords:
			parameter_count = 0
			if method_interface.args:
				parameter_count += len(method_interface.args)
			if method_interface.varargs:
				parameter_count += len(method_interface.varargs)

			if len(params) >= parameter_count:
				# params needs to be a copy, leave rpc.params unchanged
				kwargs = params[-1]
				params = params[:-1]
				if not isinstance(kwargs, dict):
					raise TypeError(f"kwargs param is not a dict: {type(kwargs)}")
				keywords = {str(key): await run_in_threadpool(deserialize, value) for key, value in kwargs.items()}
		params = await run_in_threadpool(deserialize, params)

	method = getattr(interface, method_name)
	if asyncio.iscoroutinefunction(method):
		result = await method(*params, **keywords)
	else:
		result = await run_in_threadpool(method, *params, **keywords)

	return await run_in_threadpool(serialize, result)


async def process_rpc_error(
	exception: Exception, request: JSONRPC20Request | JSONRPCRequest | None = None
) -> JSONRPC20ErrorResponse | JSONRPCErrorResponse:
	_id = request.id if request else 0
	message = str(exception)
	_class = exception.__class__.__name__

	if isinstance(request, JSONRPC20Request):
		return JSONRPC20ErrorResponse(id=_id, error=JSONRPC20Error(message=message, data={"class": _class, "details": None}))
	return JSONRPCErrorResponse(id=_id, error={"message": message, "class": _class, "details": None})


async def process_rpc(request: JSONRPC20Request | JSONRPCRequest, interface: Interface) -> JSONRPC20Response | JSONRPCResponse:
	logger.debug("Method '%s', params (short): %.250s", request.method, request.params)
	logger.trace("Method '%s', params (full): %s", request.method, request.params)

	result = await execute_rpc(request, interface)
	if isinstance(request, JSONRPC20Request):
		return JSONRPC20Response(id=request.id, result=result)
	return JSONRPCResponse(id=request.id, result=result)


async def process_rpcs(
	interface: Interface, *requests: JSONRPC20Request | JSONRPCRequest
) -> AsyncGenerator[JSONRPC20Response | JSONRPC20ErrorResponse | JSONRPCResponse | JSONRPCErrorResponse, None]:
	for request in requests:
		response: JSONRPC20Response | JSONRPC20ErrorResponse | JSONRPCResponse | JSONRPCErrorResponse
		start = time.time()
		is_error = False
		num_results = 0
		try:
			logger.debug("Processing request from %s for %s", request.info.client, request.method)
			response = await process_rpc(request, interface)
			num_results = 1
			if isinstance(response.result, list):
				num_results = len(response.result)
		except Exception as err:
			is_error = True
			logger.error(err, exc_info=True)
			response = await process_rpc_error(err, request)
		end = time.time()

		logger.trace(response)
		logger.notice(
			"JSONRPC request: method=%s, num_params=%d, duration=%0.0fms, error=%s, num_results=%d",
			request.method,
			len(request.params),
			(end - start) * 1000,
			is_error,
			num_results,
		)
		yield response


async def process_request(interface: Interface, request: Request, response: Response) -> Response:
	logger.info("Processing JSONRPC request (interface=%s)", interface.__class__.__name__)
	request_compression = None
	request_serialization = None
	response_compression = None
	response_serialization = None
	client = ""
	# TODO:
	# session = contextvar_client_session.get()
	# if session:
	# client = f"{session.client_addr}/{session.user_agent}"
	try:
		request_serialization = get_request_serialization(request)
		if request_serialization:
			# Always using same response serialization as request serialization
			response_serialization = request_serialization
		else:
			logger.debug("Unhandled request serialization %r, using json", request_serialization)
			request_serialization = "json"
			response_serialization = get_response_serialization(request)
			if not response_serialization:
				logger.debug("test_compression response serialization %r, using json", response_serialization)
				response_serialization = "json"

		response_compression = get_response_compression(request)
		request_compression = get_request_compression(request)

		request_data = await request.body()
		if not isinstance(request_data, bytes):
			raise ValueError("Request data must be bytes")
		if request_data:
			if request_compression:
				request_data = await run_in_threadpool(decompress_data, request_data, request_compression)
		else:
			request_data = urllib.parse.unquote(request.url.query).encode("utf-8")
		if not request_data:
			raise ValueError("Request data empty")

		requests = await run_in_threadpool(jsonrpc_request_from_data, request_data, request_serialization, client)
		logger.trace("rpcs: %s", requests)

		coro = process_rpcs(interface, *requests)
		results = [result async for result in coro]
		response.status_code = 200
	except HTTPException as err:
		logger.error(err)
		raise
	except Exception as err:
		logger.error(err, exc_info=True)
		results = [await process_rpc_error(err)]
		response.status_code = 400

	response_serialization = response_serialization or "json"
	response.headers["content-type"] = f"application/{response_serialization}"
	response.headers["accept"] = "application/msgpack,application/json"
	response.headers["accept-encoding"] = "lz4,gzip"
	data = await run_in_threadpool(serialize_data, results[0] if len(results) == 1 else results, response_serialization)

	data_len = len(data)
	if response_compression and data_len > COMPRESS_MIN_SIZE:
		response.headers["content-encoding"] = response_compression
		lz4_block_linked = True
		if request.headers.get("user-agent", "").startswith(("opsi config editor", "opsi-configed")):
			# lz4-java - RuntimeException: Dependent block stream is unsupported (BLOCK_INDEPENDENCE must be set).
			lz4_block_linked = False
		data = await run_in_threadpool(compress_data, data, response_compression, 0, lz4_block_linked)

	content_length = len(data)
	response.headers["content-length"] = str(content_length)
	response.body = data
	logger.debug("Sending result (len: %d)", content_length)
	return response
