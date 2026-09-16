# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
test_control_server
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from opsiclientd.Config import Config
from opsiclientd.webserver import Webserver, _get_bind_interfaces

from .utils import OpsiclientdTestClient, default_config, opsiclientd_auth, test_client  # noqa


@pytest.mark.parametrize(
	("interfaces", "expected"),
	[
		(["127.0.0.1", "0.0.0.0", "::", "::1"], ["0.0.0.0", "::"]),
		(["::1", "::", "0.0.0.0", "127.0.0.1"], ["::", "0.0.0.0"]),
		(["0.0.0.0", "::"], ["0.0.0.0", "::"]),
		(["127.0.0.1", "::1"], ["127.0.0.1", "::1"]),
		(["127.0.0.1", "0.0.0.0", "::1"], ["0.0.0.0", "::1"]),
		(["127.0.0.1", "::", "::1"], ["127.0.0.1", "::"]),
		(["192.0.2.1", "0.0.0.0", "2001:db8::1", "::"], ["0.0.0.0", "::"]),
		(["127.0.0.1", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"], ["127.0.0.1", "::1"]),
		(["::1", "0:0:0:0:0:0:0:0", "::"], ["::"]),
		(["localhost", "0.0.0.0"], ["localhost", "0.0.0.0"]),
	],
)
def test_get_bind_interfaces(interfaces: list[str], expected: list[str]) -> None:
	original = interfaces.copy()
	assert _get_bind_interfaces(interfaces) == expected
	assert interfaces == original


def test_webserver_overlapping_interfaces(default_config: Config) -> None:  # noqa: F811
	original = default_config.get("control_server", "interface")
	try:
		default_config.set("control_server", "interface", "127.0.0.1, 0.0.0.0, ::, ::1")
		with patch("opsiclientd.webserver.setup_application"):
			server = Webserver(Mock(config=default_config))
		assert server._server is not None
		assert server._server.config.host == ["0.0.0.0", "::"]
		assert default_config.get("control_server", "interface") == ["127.0.0.1", "0.0.0.0", "::", "::1"]
	finally:
		default_config.set("control_server", "interface", original)


def test_authorization(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	with test_client as client:
		test_client.set_client_address("1.2.3.4", 1234)
		res = client.get("/")
		assert res.status_code == 401
		res = client.get("/favicon.ico")
		assert res.status_code == 401

		test_client.set_client_address("127.0.0.1", 1234)
		res = client.get("/")
		assert res.status_code == 200
		res = client.get("/favicon.ico")
		assert res.status_code == 200
		res = client.get("/rpc")
		assert res.status_code == 401  # This should be unauthorized 401 because we are not authenticated at all
