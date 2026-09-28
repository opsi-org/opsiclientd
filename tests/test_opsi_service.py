# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

from pathlib import Path
from types import SimpleNamespace

import pytest
from opsi.crypt.ssl import as_pem, create_ca

from opsiclientd import OpsiService


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
