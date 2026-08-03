# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
utils
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx._auth import BasicAuth
from httpx._models import Cookies
from httpx._types import AuthTypes
from opsi.opsi.service.model.object import deserialize, serialize
from starlette.types import Scope

from opsiclientd.Config import Config
from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd.webserver.application.main import setup_application


@pytest.fixture
def opsiclientd_url() -> str:
	return "https://localhost:4441"


@pytest.fixture
def opsiclientd_auth() -> tuple[str, str]:
	config = Config()
	config.readConfigFile()
	return (config.get("global", "host_id"), config.get("global", "opsi_host_key"))


@contextmanager
def change_dir(path: str | Path) -> Generator[None]:
	old_dir = os.getcwd()
	os.chdir(path)
	try:
		yield
	finally:
		os.chdir(old_dir)


def load_config_file(config_file: str) -> Config:
	config = Config()
	config.set("global", "config_file", config_file)
	config.readConfigFile()
	return config


@pytest.fixture
def default_config() -> Config:
	return load_config_file("tests/data/opsiclientd.conf")


class OpsiclientdTestClient(TestClient):
	def __init__(self, opsiclientd: Opsiclientd | None = None) -> None:
		if not opsiclientd:
			opsiclientd = Opsiclientd()
		super().__init__(setup_application(opsiclientd), "https://localhost:4441")
		self._address = ("127.0.0.1", 12345)
		self._username: str | None = None
		self._password: str | None = None

	def __enter__(self) -> OpsiclientdTestClient:
		super().__enter__()
		return self

	@property
	def auth(self) -> tuple[str, str] | None:
		if self._username is None or self._password is None:
			return None
		return self._username, self._password

	@auth.setter
	def auth(self, auth: AuthTypes) -> None:
		if not isinstance(auth, tuple):
			raise ValueError("Auth type not supported")

		self._username = str(auth[0]) if auth[0] else None
		self._password = str(auth[1]) if auth[1] else None
		if self._username and self._password:
			self._auth = BasicAuth(self._username, self._password)
		else:
			self._auth = None

	def reset_cookies(self) -> None:
		self.cookies = Cookies()

	def set_client_address(self, host: str, port: int) -> None:
		self._address = (host, port)

	def get_client_address(self) -> tuple[str, int]:
		return self._address

	def jsonrpc20(
		self,
		*,
		method: str,
		params: dict[str, Any] | list[Any] | None = None,
		id: int | str | None = None,
		path: str = "/rpc",
		headers: dict[str, str] | None = None,
	) -> Any:
		params = serialize(params or {})
		rpc = {"jsonrpc": "2.0", "id": id or str(uuid4()), "method": method, "params": params}
		res = self.post(path, json=rpc, headers=headers)
		if res.status_code != 200:
			print(res.text)
			res.raise_for_status()
		return deserialize(res.json(), deep=True)


@pytest.fixture()
def test_client() -> Generator[OpsiclientdTestClient]:
	with get_test_client() as client:
		yield client


@contextmanager
def get_test_client(opsiclientd: Opsiclientd | None = None) -> Generator[OpsiclientdTestClient]:
	client = OpsiclientdTestClient(opsiclientd)

	def get_client_address(asgi_adapter: Any, scope: Scope) -> tuple[str, int]:
		return client.get_client_address()

	with patch("opsiclientd.webserver.application.middleware.BaseMiddleware.get_client_address", get_client_address):
		yield client
