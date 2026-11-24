# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import stamina
from opsi.crypt.ssl import as_pem, create_ca
from opsi.exception import OpsiServiceConnectionError, OpsiServiceVerificationError

from opsiclientd import OpsiService


@pytest.fixture(autouse=True)
def no_retry_wait() -> Iterator[None]:
	with stamina.set_testing(True, attempts=6):
		yield


def test_update_os_ca_store_removes_only_opsi_cas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	non_opsi_ca, _ = create_ca(subject={"CN": "Unrelated CA"}, valid_days=30)
	opsi_ca, _ = create_ca(subject={"CN": "Customer OPSI CA"}, valid_days=30)
	ca_cert_file = tmp_path / "ca-certs.pem"
	ca_cert_file.write_text(as_pem(non_opsi_ca) + as_pem(opsi_ca), encoding="utf-8")

	stored_cas = {
		"Unrelated CA": [non_opsi_ca],
		"Customer OPSI CA": [opsi_ca],
	}
	removed_cas: list[tuple[str, str]] = []
	monkeypatch.setattr(OpsiService, "config", SimpleNamespace(ca_cert_file=ca_cert_file, get=lambda section, option: False))
	monkeypatch.setattr(OpsiService, "load_cas", lambda subject_name: stored_cas[subject_name])
	monkeypatch.setattr(OpsiService, "remove_ca", lambda subject_name, fingerprint: removed_cas.append((subject_name, fingerprint)))

	OpsiService.update_os_ca_store(allow_remove=True)

	assert [subject_name for subject_name, _fingerprint in removed_cas] == ["Customer OPSI CA"]


def test_update_os_ca_store_prunes_only_opsi_cas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	non_opsi_cas = [create_ca(subject={"CN": "Unrelated CA"}, valid_days=30)[0] for _ in range(3)]
	opsi_cas = [create_ca(subject={"CN": "Customer OPSI CA"}, valid_days=30)[0] for _ in range(3)]
	ca_cert_file = tmp_path / "ca-certs.pem"
	ca_cert_file.write_text(as_pem(non_opsi_cas[0]) + as_pem(opsi_cas[0]), encoding="utf-8")

	stored_cas = {
		"Unrelated CA": non_opsi_cas,
		"Customer OPSI CA": opsi_cas,
	}
	removed_cas: list[tuple[str, str]] = []
	monkeypatch.setattr(OpsiService, "config", SimpleNamespace(ca_cert_file=ca_cert_file, get=lambda section, option: True))
	monkeypatch.setattr(OpsiService, "load_cas", lambda subject_name: stored_cas[subject_name])
	monkeypatch.setattr(OpsiService, "remove_ca", lambda subject_name, fingerprint: removed_cas.append((subject_name, fingerprint)))
	monkeypatch.setattr(OpsiService, "install_ca", lambda ca_cert: None)

	OpsiService.update_os_ca_store(allow_remove=True)

	assert removed_cas
	assert {subject_name for subject_name, _fingerprint in removed_cas} == {"Customer OPSI CA"}


def test_download_from_depot_retries_on_network_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	attempts = {"service": 0, "depot": 0}

	class FakeClient:
		def connect(self) -> None:
			attempts["service"] += 1
			if attempts["service"] < 3:
				raise OpsiServiceConnectionError("Failed to resolve")

		def product_getIdents(self, id: str) -> list[str]:
			return [id]

		def stop(self) -> None:
			pass

		def download(self, source: str, destination: Path) -> None:
			attempts["depot"] += 1
			if attempts["depot"] < 2:
				raise requests.exceptions.ChunkedEncodingError("connection broken")

		def disconnect(self) -> None:
			pass

	depot = SimpleNamespace(depotWebdavUrl="webdavs://depot.example.org:4447/depot")
	monkeypatch.setattr(OpsiService, "get_service_client", lambda address=None, connect_timeout=10.0: FakeClient())
	monkeypatch.setattr(OpsiService, "config", SimpleNamespace(getDepot=lambda **kwargs: [depot]))

	OpsiService.download_from_depot("opsi-client-agent", tmp_path)

	assert attempts == {"service": 3, "depot": 2}


def test_download_from_depot_does_not_retry_non_network_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	calls = 0

	class FakeClient:
		def connect(self) -> None:
			nonlocal calls
			calls += 1
			raise OpsiServiceVerificationError("certificate verify failed")

		def stop(self) -> None:
			pass

	monkeypatch.setattr(OpsiService, "get_service_client", lambda address=None, connect_timeout=10.0: FakeClient())

	with pytest.raises(OpsiServiceVerificationError):
		OpsiService.download_from_depot("opsi-client-agent", tmp_path)
	assert calls == 1
