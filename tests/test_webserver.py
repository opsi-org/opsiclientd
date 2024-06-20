# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
test_control_server
"""

from __future__ import annotations

from .utils import OpsiclientdTestClient, default_config, opsiclientd_auth, test_client  # noqa


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
		assert res.status_code == 403
