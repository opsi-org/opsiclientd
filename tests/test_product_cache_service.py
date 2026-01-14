# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
test_control_pipe
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from opsicommon.logging import LOG_INFO, use_logging_config
from opsicommon.objects import Config, ConfigState, Host, LocalbootProduct, OpsiDepotserver, Product, ProductOnClient, ProductOnDepot
from opsicommon.package.associated_files import create_package_content_file

from opsiclientd.Config import Config as OpsiclientdConfig
from opsiclientd.nonfree.CacheService import ProductCacheService
from opsiclientd.State import State
from opsiclientd.utils import DiskSpaceUsage, get_directory_size


def test_cache_product(tmp_path: Path) -> None:
	client_id = "client1.opsi.test"
	depot_id = "depot1.opsi.test"
	products: list[Product] = [
		LocalbootProduct(id="opsi-script", productVersion="1.0", packageVersion="1"),
		LocalbootProduct(id="prod1", productVersion="1.0", packageVersion="1"),
		LocalbootProduct(id="prod2", productVersion="1.0", packageVersion="1"),
		LocalbootProduct(id="prod3", productVersion="1.0", packageVersion="1"),
	]
	state_file = tmp_path / "state.json"
	product_ids_setup = []

	config = OpsiclientdConfig()
	config.set("global", "host_id", client_id)
	config.set("depot_server", "master_depot_id", depot_id)
	config.set("global", "state_file", str(state_file))

	state = State()
	state.start()

	storage_dir = tmp_path / "storage"
	temp_dir = storage_dir / "tmp"
	product_cache_dir = storage_dir / "depot"
	product_cache_max_size = 1_000_000_000
	available_disk_space = 1_000_000_000
	product_data_size = 100_000_000
	product_size = product_data_size

	server_path = tmp_path / "server"
	depot_path = server_path / "depot"
	depot_path.mkdir(parents=True)
	for product in products:
		product_path = depot_path / product.id
		product_path.mkdir(parents=True)
		for num in range(10):
			sub_dir = product_path
			if num % 2 == 0:
				sub_dir = product_path / "sub1"
			sub_dir.mkdir(exist_ok=True)
			data_file = sub_dir / f"{num}.bin"
			data_file.write_bytes(str(num).encode("ascii") * int(product_data_size / 10))
		package_content_file = create_package_content_file(product_path)
		product_size = product_data_size + package_content_file.stat().st_size
		assert get_directory_size(product_path) == product_size

	def mock_get_disk_space_usage(path: Path | str) -> DiskSpaceUsage:
		capacity = 100_000_000_000
		available = available_disk_space - get_directory_size(product_cache_dir)
		return DiskSpaceUsage(
			capacity=capacity,
			available=available,
			used=capacity - available,
			usage=(capacity - available) / capacity,
		)

	class MockService:
		updated_pocs: list[ProductOnClient] = []

		# Mock the ServiceClient class
		def productOnClient_updateObjects(self, productOnClients: list[ProductOnClient]) -> None:
			self.updated_pocs.extend(productOnClients)

		def host_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Host]:
			return [OpsiDepotserver(id=depot_id, depotRemoteUrl=f"file://{depot_path}")]

		def product_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Product]:
			return products

		def productOnDepot_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ProductOnDepot]:
			return [
				ProductOnDepot(
					depotId=depot_id,
					productType=p.getType(),
					productId=p.id,
					productVersion=p.productVersion,
					packageVersion=p.packageVersion,
				)
				for p in products
			]

		def productOnClient_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ProductOnClient]:
			return [
				ProductOnClient(
					clientId=client_id,
					productType=p.getType(),
					productId=p.id,
					productVersion=p.productVersion,
					packageVersion=p.packageVersion,
					installationStatus="not_installed",
					actionRequest="setup",
				)
				for p in products
				if p.id in product_ids_setup
			]

		def config_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Config]:
			return []

		def configState_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ConfigState]:
			return []

		def configState_getClientToDepotserver(
			self,
			depotIds: list[str] | None = None,
			clientIds: list[str] | None = None,
			masterOnly: bool = False,
			productIds: list[str] | None = None,
		) -> list[dict[str, str]]:
			return [
				{
					"clientId": client_id,
					"depotId": depot_id,
				}
			]

		def user_getCredentials(self, username: str | None = None, hostId: str | None = None) -> dict[str, str]:
			return {"password": "secret", "rsaPrivateKey": ""}

		def connected(self) -> bool:
			return True

	def _updateConfig(self: ProductCacheService) -> None:
		self._storage_dir = storage_dir
		self._temp_dir = temp_dir
		self._product_cache_dir = product_cache_dir
		self._product_cache_max_size = product_cache_max_size

	service_client = MockService()

	with (
		use_logging_config(stderr_level=LOG_INFO),
		patch("opsiclientd.nonfree.CacheService.get_disk_space_usage", mock_get_disk_space_usage),
		patch("opsiclientd.nonfree.CacheService.ProductCacheService._updateConfig", _updateConfig),
		patch("opsiclientd.nonfree.CacheService.ProductCacheService.service_client", service_client),
	):
		product_cache_service = ProductCacheService(opsiclientd=None)  # type: ignore[arg-type]

		# Test opsi-script only
		service_client.updated_pocs.clear()
		product_ids_setup = [products[0].id]
		available_disk_space = product_cache_service.min_free_disk_space

		product_cache_service._cacheProducts()
		# Nothing to do
		assert len(product_cache_service.last_errors) == 0
		assert len(service_client.updated_pocs) == 0

		# Test with insufficient disk space
		service_client.updated_pocs.clear()
		product_ids_setup = [products[0].id, products[1].id]
		available_disk_space = product_cache_service.min_free_disk_space

		product_cache_service._cacheProducts()
		err_msg = (
			"Failed to free enough product cache space: "
			f"Needed space: {(product_size / 1_000_000):0.2f} MB, maximum freeable space: 0.00 MB, "
			f"current product cache size: 0.00 MB, max product cache size: {(product_cache_max_size / 1_000_000):0.0f} MB ({products[0].id})"
		)
		assert len(product_cache_service.last_errors) == 1
		assert str(product_cache_service.last_errors[0]) == err_msg

		assert len(service_client.updated_pocs) == 2
		assert service_client.updated_pocs[0].productId == products[0].id
		assert service_client.updated_pocs[0].actionProgress == "caching"
		assert service_client.updated_pocs[1].productId == products[0].id
		assert service_client.updated_pocs[1].actionProgress == f"Cache failure: {err_msg}"

		# Test with enough disk space
		service_client.updated_pocs.clear()
		product_ids_setup = [products[0].id, products[1].id]
		available_disk_space = product_cache_service.min_free_disk_space + (product_size * 2)

		product_cache_service._cacheProducts()
		assert len(product_cache_service.last_errors) == 0

		assert len(service_client.updated_pocs) == 4
		assert service_client.updated_pocs[0].productId == products[0].id
		assert service_client.updated_pocs[0].actionProgress == "caching"
		assert service_client.updated_pocs[1].productId == products[0].id
		assert service_client.updated_pocs[1].actionProgress == "cached"
		assert service_client.updated_pocs[2].productId == products[1].id
		assert service_client.updated_pocs[2].actionProgress == "caching"
		assert service_client.updated_pocs[3].productId == products[1].id
		assert service_client.updated_pocs[3].actionProgress == "cached"

		for prod in product_ids_setup:
			depot_path_prod = depot_path / prod
			assert depot_path_prod.exists()
			prod_cache = product_cache_dir / prod
			assert prod_cache.exists()
			for dirpath, _dirnames, filenames in os.walk(depot_path_prod):
				for file in filenames:
					depot_file = Path(dirpath) / file
					cache_file = prod_cache / depot_file.relative_to(depot_path_prod)
					assert cache_file.read_bytes() == depot_file.read_bytes()

		# Now cache other products.
		# Product cache size is only sufficient for two products.
		# The product cached before must be removed from the cache.
		service_client.updated_pocs.clear()
		product_ids_setup = [products[2].id]  # opsi-script must be added automatically
		available_disk_space = product_cache_service.min_free_disk_space + (product_size * 2)

		product_cache_service._cacheProducts()
		assert len(product_cache_service.last_errors) == 0
		product_ids_in_cache = sorted(d.name for d in product_cache_dir.iterdir())
		assert product_ids_in_cache == sorted([products[0].id, products[2].id])

		# Test with enough disk space for three products
		# The product cached before must be kept in the cache.
		service_client.updated_pocs.clear()
		product_ids_setup = [products[1].id]
		available_disk_space = product_cache_service.min_free_disk_space + (product_size * 3)

		product_cache_service._cacheProducts()
		assert len(product_cache_service.last_errors) == 0
		product_ids_in_cache = sorted(d.name for d in product_cache_dir.iterdir())
		assert product_ids_in_cache == sorted([products[0].id, products[1].id, products[2].id])

		# Test with enough disk space for all products
		service_client.updated_pocs.clear()
		product_ids_setup = [p.id for p in products]
		available_disk_space = product_cache_service.min_free_disk_space + (product_size * len(products))

		product_cache_service._cacheProducts()
		assert len(product_cache_service.last_errors) == 0
		product_ids_in_cache = sorted(d.name for d in product_cache_dir.iterdir())
		assert product_ids_in_cache == sorted(product_ids_setup)

		# Test similar product cache dir
		service_client.updated_pocs.clear()
		product_ids_setup = [products[0].id, products[1].id]
		available_disk_space = product_cache_service.min_free_disk_space + (product_size * 10)  # Enough space for 10 products
		prod1_cache_dir = product_cache_dir / products[1].id
		similar_cache_dir = product_cache_dir / f"{products[1].id}--rfc156094"
		prod1_cache_dir.rename(similar_cache_dir)
		product_ids_in_cache = sorted(d.name for d in product_cache_dir.iterdir())
		assert similar_cache_dir.name in product_ids_in_cache

		renamed_called_with = ("", "")

		def mock_rename_product_cache_dir(product_id: str, new_product_id: str) -> None:
			nonlocal renamed_called_with
			renamed_called_with = (product_id, new_product_id)
			return ProductCacheService._rename_product_cache_dir(product_cache_service, product_id, new_product_id)

		with patch.object(product_cache_service, "_rename_product_cache_dir", mock_rename_product_cache_dir):
			product_cache_service._cacheProducts()
			assert len(product_cache_service.last_errors) == 0
			product_ids_in_cache = sorted(d.name for d in product_cache_dir.iterdir())
			# Must be renamed and reused
			assert renamed_called_with == (f"{products[1].id}--rfc156094", products[1].id)
			assert similar_cache_dir.name not in product_ids_in_cache

		# Test product_cache_max_size
		# The unneeded products cached before must be removed from the cache.
		service_client.updated_pocs.clear()
		product_ids_setup = [products[1].id]
		available_disk_space = product_cache_service.min_free_disk_space + (product_size * 10)  # Enough space for 10 products
		product_cache_max_size = product_size * 2

		product_cache_service._cacheProducts()
		assert len(product_cache_service.last_errors) == 0
		product_ids_in_cache = sorted(d.name for d in product_cache_dir.iterdir())
		assert product_ids_in_cache == sorted([products[0].id, products[1].id])

		# Test product_cache_max_size with insufficient disk space
		# opsi-script and prod1 are already in the cache.
		# No more space for prod2.
		service_client.updated_pocs.clear()
		product_ids_setup = [p.id for p in products]
		available_disk_space = product_cache_service.min_free_disk_space + (product_size * 10)  # Enough space for 10 products
		product_cache_max_size = product_size * 2

		product_cache_service._cacheProducts()
		assert len(product_cache_service.last_errors) == 1
		err_msg = (
			"Failed to free enough product cache space: "
			f"Needed space: {(product_size / 1_000_000):0.2f} MB, maximum freeable space: 0.00 MB, "
			f"current product cache size: {(product_size * 2 / 1_000_000):0.2f} MB, "
			f"max product cache size: {(product_cache_max_size / 1_000_000):0.0f} MB (prod2)"
		)
		assert str(product_cache_service.last_errors[0]) == err_msg

		# Test clear product cache
		product_cache_service.clear_cache()
		assert len(list(product_cache_dir.iterdir())) == 0
		assert product_cache_service._cache_dir_sizes == {}


@pytest.mark.windows
def test_pause_resume_product_caching_on_metered_net_connection() -> None:
	cache_service = ProductCacheService(opsiclientd=MagicMock())

	with patch.object(cache_service, "pause_caching") as pause_mock, patch.object(cache_service, "resume_caching") as resume_mock:
		# Test Case 1: Metered connection
		pause_mock.reset_mock()
		resume_mock.reset_mock()
		cache_service._on_network_status_change(connected=True, metered=True)
		pause_mock.assert_called_once()
		resume_mock.assert_not_called()

		# Test Case 2: Unmetered connection
		pause_mock.reset_mock()
		resume_mock.reset_mock()
		cache_service._on_network_status_change(connected=True, metered=False)
		resume_mock.assert_called_once()
		pause_mock.assert_not_called()

		# Test Case 3: Disconnected
		pause_mock.reset_mock()
		resume_mock.reset_mock()
		cache_service._on_network_status_change(connected=False, metered=False)
		pause_mock.assert_called_once()
		resume_mock.assert_not_called()
