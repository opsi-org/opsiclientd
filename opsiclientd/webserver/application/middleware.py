# -*- coding: utf-8 -*-

# Copyright (c) 2024 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
application.middelware
"""

import base64
import uuid
from collections import namedtuple
from datetime import datetime, timezone
from ipaddress import IPv6Address, ip_address
from time import time
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from OPSI.Backend.Manager.Authentication import AuthenticationModule  # type: ignore[import]
from opsicommon.exceptions import BackendAuthenticationError, BackendPermissionDeniedError
from opsicommon.logging import get_logger, secret_filter
from opsicommon.logging.constants import TRACE
from opsicommon.system.info import is_linux, is_windows
from opsicommon.utils import unix_timestamp
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import Message, Receive, Scope, Send

from opsiclientd.Config import Config

SESSION_COOKIE_NAME = "opsiclientd-session"
SESSION_COOKIE_ATTRIBUTES = ("SameSite=Strict", "Secure")
SESSION_LIFETIME = 300
CLIENT_BLOCK_TIME = 120
AUTH_HEADERS = {"WWW-Authenticate": 'Basic realm="opsi", charset="UTF-8"'}

logger = get_logger()
config = Config()
server_date = (0, b"", b"")
BasicAuth = namedtuple("BasicAuth", ["username", "password"])


def get_server_date() -> tuple[bytes, bytes]:
	global server_date
	now = int(time())
	if server_date[0] != now:
		server_date = (
			now,
			str(now).encode("ascii"),
			datetime.fromtimestamp(now, timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %Z").encode("utf-8"),
		)
	return server_date[1], server_date[2]


def normalize_ip_address(address: str, exploded: bool = False) -> str:
	ipa = ip_address(address)
	if isinstance(ipa, IPv6Address) and ipa.ipv4_mapped:
		ipa = ipa.ipv4_mapped
	if exploded:
		return ipa.exploded
	return ipa.compressed


def get_session_id_from_headers(headers: Headers) -> str | None:
	# connection.cookies.get(SESSION_COOKIE_NAME, None)
	# Not working for opsi-script, which sometimes sends:
	# 'NULL; session=7b9efe97a143438684267dfb71cbace2'
	session_cookie_name = SESSION_COOKIE_NAME
	cookies = headers.get("cookie")
	if cookies:
		for cookie in cookies.split(";"):
			cookie_l = cookie.strip().split("=", 1)
			if len(cookie_l) == 2:
				if cookie_l[0].strip().lower() == session_cookie_name:
					return cookie_l[1].strip().lower()
	return None


def get_basic_auth(headers: Headers) -> BasicAuth:
	auth_header = headers.get("authorization")

	headers_401 = {}
	if headers.get("X-Requested-With", "").lower() != "xmlhttprequest":
		headers_401 = AUTH_HEADERS

	if not auth_header:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Authorization header missing",
			headers=headers_401,
		)

	if not auth_header.startswith("Basic "):
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Authorization method unsupported",
			headers=headers_401,
		)

	encoded_auth = auth_header[6:]  # Stripping "Basic "
	secret_filter.add_secrets(encoded_auth)
	auth = base64.decodebytes(encoded_auth.encode("ascii")).decode("utf-8")

	if auth.count(":") == 6:
		# Seems to be a mac address as username
		username, password = auth.rsplit(":", 1)
	else:
		username, password = auth.split(":", 1)
	secret_filter.add_secrets(password)

	return BasicAuth(username, password)


class BaseMiddleware:
	_max_authentication_failures = config.get("control_server", "max_authentication_failures")
	_server_port = config.get("control_server", "port")

	def __init__(self, app: FastAPI) -> None:
		self._app = app
		self._sessions: dict[str, Session] = {}
		self._auth_failures: dict[str, list[int]] = {}
		self._auth_module: AuthenticationModule | None = None
		if is_linux():
			import OPSI.Backend.Manager.Authentication.PAM  # type: ignore[import]

			self._auth_module = OPSI.Backend.Manager.Authentication.PAM.PAMAuthentication()
		elif is_windows():
			import OPSI.Backend.Manager.Authentication.NT  # type: ignore[import]

			self._auth_module = OPSI.Backend.Manager.Authentication.NT.NTAuthentication("S-1-5-32-544")

	@staticmethod
	def get_client_address(scope: Scope) -> tuple[str, int]:
		"""Get sanitized client address"""
		host, port = scope.get("client") or ("", 0)
		if host:
			host = normalize_ip_address(host)
		return host, port

	async def authenticate(self, scope: Scope) -> None:
		session: Session = scope["session"]
		session.authenticated = False

		logger.info("Start authentication of client %s", session.client_addr)

		current_timestamp = int(unix_timestamp())
		if session.client_addr in self._auth_failures:
			assert isinstance(session.client_addr, str)
			min_ts = current_timestamp - CLIENT_BLOCK_TIME
			self._auth_failures[session.client_addr] = [ts for ts in self._auth_failures[session.client_addr] if ts >= min_ts]
			if len(self._auth_failures[session.client_addr]) >= self._max_authentication_failures:
				logger.info("Client '%s' is blocked", session.client_addr)
				raise ConnectionRefusedError(f"Client '{session.client_addr}' is blocked")

		try:
			auth = get_basic_auth(scope["request_headers"])
			if not auth.password:
				raise BackendAuthenticationError("No password specified")

			if not auth.username or auth.username.count(".") >= 2:
				host_id = config.get("global", "host_id")
				if auth.password != config.get("global", "opsi_host_key"):
					raise BackendAuthenticationError(f"Authentication of host '{host_id}' failed")
				session.username = host_id
				session.authenticated = True
				logger.info("Host %r authenticated from %r", session.username, session.client_addr)
				return

			if not self._auth_module:
				raise BackendAuthenticationError("Authentication module not available on this platform")

			await run_in_threadpool(self._auth_module.authenticate, auth.username, auth.password)
			session.username = auth.username
			session.authenticated = True
			logger.info("User %r authenticated from %r", session.username, session.client_addr)
		except:
			if session.client_addr not in self._auth_failures:
				self._auth_failures[session.client_addr] = []
			self._auth_failures[session.client_addr].append(current_timestamp)
			raise

	async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
		scope["request_headers"] = request_headers = Headers(scope=scope)
		scope["client"] = self.get_client_address(scope)

		session: Session | None = None
		session_id = get_session_id_from_headers(request_headers)
		if session_id:
			session = self._sessions.get(session_id)
			if session:
				if session.expired:
					logger.info("Sesson %r expired", session_id)
					del self._sessions[session_id]
					session = None
				else:
					session.touch()
		if not session:
			session = Session(client_addr=scope["client"][0], headers=request_headers)
			session_id = session.session_id
			self._sessions[session_id] = session
		scope["session"] = session

		if not session.authenticated:
			await self.authenticate(scope)

		async def send_wrapper(message: Message) -> None:
			if message["type"] == "http.response.start":
				headers = MutableHeaders(scope=message)
				session.add_cookie_to_headers(headers)

				host = request_headers.get("host", "localhost:4447").split(":")[0]
				origin_scheme = "https"
				origin_port = self._server_port
				try:
					origin = urlparse(request_headers["origin"])
					origin_scheme = origin.scheme
					origin_port = int(origin.port)
				except Exception:
					pass

				headers.append("Access-Control-Allow-Origin", f"{origin_scheme}://{host}:{origin_port}")
				headers.append("Access-Control-Allow-Methods", "*")
				headers.append(
					"Access-Control-Allow-Headers",
					"Accept,Accept-Encoding,Authorization,Connection,Content-Type,Encoding,Host,Origin,X-opsi-session-lifetime,X-Requested-With",
				)
				headers.append("Access-Control-Allow-Credentials", "true")

				if logger.isEnabledFor(TRACE):
					logger.trace("<<< HTTP/%s %s %s", scope.get("http_version"), scope.get("method"), scope.get("path"))
					for header, value in request_headers.items():
						logger.trace("<<< %s: %s", header, value)
					logger.trace(">>> HTTP/%s %s", scope.get("http_version"), message.get("status"))
					for header, value in dict(headers).items():
						logger.trace(">>> %s: %s", header, value)

			if "headers" in message:
				dat = get_server_date()
				message["headers"].append((b"date", dat[1]))
				message["headers"].append((b"x-date-unix-timestamp", dat[0]))
			await send(message)

		return await self._app(scope, receive, send_wrapper)

	async def handle_request_exception(self, err: Exception, scope: Scope, receive: Receive, send: Send) -> None:
		status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
		headers = None
		error = None

		if isinstance(err, (BackendAuthenticationError, BackendPermissionDeniedError)):
			logger.warning(err)
			status_code = status.HTTP_401_UNAUTHORIZED
			if scope["request_headers"].get("X-Requested-With", "").lower() != "xmlhttprequest":
				headers = AUTH_HEADERS
			error = "Authentication error"
			if isinstance(err, BackendPermissionDeniedError):
				error = "Permission denied"

		elif isinstance(err, ConnectionRefusedError):
			status_code = status.HTTP_403_FORBIDDEN
			error = str(err)

		elif isinstance(err, HTTPException):
			status_code = err.status_code
			headers = err.headers
			error = err.detail

		else:
			logger.error(err, exc_info=True)
			error = str(err)

		headers = headers or {}
		headers["x-opsi-error"] = str(error)[:64]

		if scope["type"] == "websocket":
			if scope["request_headers"].get("upgrade") == "websocket":
				# Websocket not opened yet, tested with wsproto only
				await send(
					{
						"type": "websocket.http.response.start",
						"status": status_code,
						"headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
					}
				)
				await send({"type": "websocket.http.response.body", "body": b"ERROR XYZ AAAA"})

			# Uvicorn (0.20.0) always closes websockets with code 403
			# There is currently no way to send a custom status code or headers
			websocket_close_code = status.WS_1008_POLICY_VIOLATION
			reason = error
			if status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
				websocket_close_code = status.WS_1011_INTERNAL_ERROR
			elif status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
				websocket_close_code = status.WS_1013_TRY_AGAIN_LATER
				reason = f"{reason[:100]}\nRetry-After: {headers.get('Retry-After')}"

			# reason max length 123 bytes
			logger.debug("Closing websocket with code=%r and reason=%r", websocket_close_code, reason)
			try:
				await send({"type": "websocket.close", "code": websocket_close_code, "reason": reason})
			except RuntimeError:
				# Alread closed (can happen on shutdown)
				pass
			return

		if scope.get("session"):
			scope["session"].add_cookie_to_headers(headers)

		response: Response | None = None
		if scope["path"].startswith("/rpc"):
			logger.debug("Returning jsonrpc response because path startswith /rpc")
			content = {"id": None, "result": None, "error": error}
			if scope.get("jsonrpc20"):
				content["jsonrpc"] = "2.0"
				del content["result"]
			response = JSONResponse(status_code=status_code, content=content, headers=headers)

		if not response:
			if scope["request_headers"].get("accept") and "application/json" in scope["request_headers"].get("accept", ""):
				logger.debug("Returning json response because of accept header")
				response = JSONResponse(status_code=status_code, content={"error": error}, headers=headers)

		if not response:
			logger.debug("Returning plaintext response")
			response = PlainTextResponse(status_code=status_code, content=error, headers=headers)

		await response(scope, receive, send)

	async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
		if scope["type"] not in ("http", "websocket"):
			return await self._app(scope, receive, send)
		try:
			await self.handle_request(scope, receive, send)
		except Exception as err:
			await self.handle_request_exception(err, scope, receive, send)


class Session:
	def __init__(self, client_addr: str, headers: Headers | None = None) -> None:
		self.client_addr = client_addr
		self.headers = headers
		self.max_age = int(SESSION_LIFETIME)
		self.session_id = str(uuid.uuid4()).replace("-", "")
		self.last_used = self.created = int(unix_timestamp())
		self.username = ""
		self.authenticated = False

	def touch(self) -> None:
		self.last_used = int(unix_timestamp())

	@property
	def expired(self) -> bool:
		return self.validity <= 0

	@property
	def validity(self) -> int:
		return int(self.max_age - (unix_timestamp() - self.last_used))

	def get_cookie(self) -> str | None:
		attrs = "; ".join(SESSION_COOKIE_ATTRIBUTES)
		return f"{SESSION_COOKIE_NAME}={self.session_id}; {attrs}; path=/; Max-Age={self.max_age}"

	def add_cookie_to_headers(self, headers: dict[str, str]) -> None:
		if cookie := self.get_cookie():
			headers["set-cookie"] = cookie
