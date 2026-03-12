# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.

"""
opsiclientd.nonfree.DepotSync

@copyright:	uib GmbH <info@uib.de>
"""

import os
import shutil
import threading
from typing import Any, Optional, Sequence

from opsi_legacy.Util import md5sum
from opsi_legacy.Util.File.Opsi import PackageContentFile
from opsi_legacy.Util.Message import ProgressSubject
from opsi_legacy.Util.Path import cd
from opsi_legacy.Util.Repository import Repository
from opsicommon.logging import get_logger
from opsicommon.types import forceUnicode, forceUnicodeList

logger = get_logger()


class DepotToLocalDirectorySynchronizer:
	def __init__(
		self,
		sourceDepot: Repository,
		destinationDirectory: str,
		productIds: Optional[Sequence[str]] = None,
		maxBandwidth: int = 0,
		dynamicBandwidth: bool = False,
		continue_event: Optional[threading.Event] = None,
	) -> None:
		productIds = productIds or []
		self._sourceDepot: Any = sourceDepot
		self._destinationDirectory: str = forceUnicode(destinationDirectory)
		self._productIds: list[str] = forceUnicodeList(productIds)
		self._productId: Optional[str] = None
		self._linkFiles: dict[str, str] = {}
		self._fileInfo: Optional[dict[str, Any]] = None
		os.makedirs(self._destinationDirectory, exist_ok=True)
		self._sourceDepot.setBandwidth(dynamicBandwidth=dynamicBandwidth, maxBandwidth=maxBandwidth)
		self._continue_event = continue_event

	def _synchronizeDirectories(self, source: str, destination: str, progressSubject: Optional[ProgressSubject] = None) -> None:
		source = forceUnicode(source)
		destination = forceUnicode(destination)
		logger.debug("Syncing directory %s to %s", source, destination)
		os.makedirs(destination, exist_ok=True)

		# Local directory cleanup
		for item in os.listdir(destination):
			relSource = (source + "/" + item).split("/", 1)[1]
			if self._productId is not None and relSource == self._productId + ".files":
				continue
			if self._fileInfo and relSource in self._fileInfo:
				continue

			path = os.path.join(destination, item)
			logger.info("Deleting '%s'", relSource)
			if os.path.isdir(path) and not os.path.islink(path):
				shutil.rmtree(path)
			else:
				os.remove(path)

		# Start sync
		for item in self._sourceDepot.content(source):
			if self._continue_event:
				self._continue_event.wait()

			source = forceUnicode(source)
			sourcePath = source + "/" + item["name"]
			destinationPath = os.path.join(destination, item["name"])
			relSource = sourcePath.split("/", 1)[1]
			if self._productId is not None and relSource == self._productId + ".files":
				continue
			if not self._fileInfo or relSource not in self._fileInfo:
				continue
			if self._fileInfo[relSource]["type"] == "d":
				self._synchronizeDirectories(sourcePath, destinationPath, progressSubject)
			else:
				logger.debug(
					"Syncing %s with %s %s",
					relSource,
					destinationPath,
					self._fileInfo[relSource],
				)
				if self._fileInfo[relSource]["type"] == "l":
					self._linkFiles[relSource] = self._fileInfo[relSource]["target"]
					continue
				size = 0
				localSize = 0
				exists = False
				if self._fileInfo[relSource]["type"] == "f":
					size = int(self._fileInfo[relSource]["size"])
					exists = os.path.exists(destinationPath)
					if exists and os.path.isdir(destinationPath):
						shutil.rmtree(destinationPath)
						exists = False
					if exists:
						md5s = md5sum(destinationPath)
						logger.debug(
							"Destination file '%s' already exists (size: %s, md5sum: %s)",
							destinationPath,
							size,
							md5s,
						)
						localSize = os.path.getsize(destinationPath)
						if localSize == size and md5s == self._fileInfo[relSource]["md5sum"]:
							continue

				if progressSubject:
					progressSubject.setMessage("Downloading file '%s'" % item["name"])

				partialEndFile = f"{destinationPath}.opsi_sync_endpart"
				partialStartFile = f"{destinationPath}.opsi_sync_startpart"

				composed = False
				if exists and (localSize < size):
					try:
						# First byte needed is byte number <localSize>
						logger.info(
							"Downloading file '%s' starting at byte number %d",
							item["name"],
							localSize,
						)
						if os.path.exists(partialEndFile):
							os.remove(partialEndFile)
						self._sourceDepot.download(sourcePath, partialEndFile, startByteNumber=localSize, pauseEvent=self._continue_event)

						with open(destinationPath, "ab") as f1:
							with open(partialEndFile, "rb") as f2:
								shutil.copyfileobj(f2, f1)

						md5s = md5sum(destinationPath)
						if md5s != self._fileInfo[relSource]["md5sum"]:
							logger.info("MD5sum of composed file differs after downloading end part")
							if os.path.exists(partialStartFile):
								os.remove(partialStartFile)
							# Last byte needed is byte number <localSize> - 1
							logger.info(
								"Downloading file '%s' ending at byte number %d",
								item["name"],
								localSize - 1,
							)
							self._sourceDepot.download(
								sourcePath,
								partialStartFile,
								endByteNumber=localSize - 1,
								pauseEvent=self._continue_event,
							)

							with open(partialStartFile, "ab") as f1:
								with open(partialEndFile, "rb") as f2:
									shutil.copyfileobj(f2, f1)

							if os.path.exists(destinationPath):
								os.remove(destinationPath)
							os.rename(partialStartFile, destinationPath)
							md5s = md5sum(destinationPath)
							if md5s != self._fileInfo[relSource]["md5sum"]:
								logger.info("MD5sum of composed file differs after downloading start part")
								raise RuntimeError("MD5sum differs")
						composed = True
					except Exception as err:
						logger.warning(
							"Error completing a partially downloaded file '%s': %s",
							item["name"],
							err,
							exc_info=True,
						)

				for fn in (partialEndFile, partialStartFile):
					if os.path.exists(fn):
						os.remove(fn)

				if not composed:
					if os.path.exists(destinationPath):
						os.remove(destinationPath)
					logger.info("Downloading file '%s'", item["name"])
					self._sourceDepot.download(
						sourcePath, destinationPath, progressSubject=progressSubject, pauseEvent=self._continue_event
					)

				md5s = md5sum(destinationPath)
				if md5s != self._fileInfo[relSource]["md5sum"]:
					error = (
						f"Failed to download '{item['name']}': "
						f"MD5sum mismatch (local:{md5s} != remote:{self._fileInfo[relSource]['md5sum']})"
					)
					logger.error(error)
					raise RuntimeError(error)

	def synchronize(self, productProgressObserver: Optional[Any] = None, overallProgressObserver: Optional[Any] = None) -> None:
		if not self._productIds:
			logger.info("Getting product dirs of depot '%s'", self._sourceDepot)
			for item in self._sourceDepot.content():
				self._productIds.append(item["name"])

		overallProgressSubject = ProgressSubject(
			id="sync_products_overall",
			type="product_sync",
			end=len(self._productIds),
			fireAlways=True,
		)
		overallProgressSubject.setMessage("Synchronizing products")
		if overallProgressObserver:
			overallProgressSubject.attachObserver(overallProgressObserver)

		for self._productId in self._productIds:
			if self._continue_event:
				self._continue_event.wait()

			productProgressSubject = ProgressSubject(
				id="sync_product_" + self._productId,
				type="product_sync",
				fireAlways=True,
			)
			productProgressSubject.setMessage("Synchronizing product %s" % self._productId)
			if productProgressObserver:
				productProgressSubject.attachObserver(productProgressObserver)
			packageContentFile = None

			try:
				self._linkFiles = {}
				logger.notice(
					"Syncing product %s of depot %s with local directory %s",
					self._productId,
					self._sourceDepot,
					self._destinationDirectory,
				)

				productDestinationDirectory = os.path.join(self._destinationDirectory, self._productId)
				if not os.path.isdir(productDestinationDirectory):
					os.mkdir(productDestinationDirectory)

				logger.info("Downloading package content file")
				packageContentFile = os.path.join(productDestinationDirectory, f"{self._productId}.files")
				self._sourceDepot.download(
					f"{self._productId}/{self._productId}.files", packageContentFile, pauseEvent=self._continue_event
				)
				self._fileInfo = PackageContentFile(packageContentFile).parse()

				size = 0
				for value in self._fileInfo.values():
					try:
						size += int(value["size"])
					except KeyError:
						pass

				productProgressSubject.setMessage("Synchronizing product %s (%.2fkByte)" % (self._productId, (size / 1000)))
				productProgressSubject.setEnd(size)
				productProgressSubject.setEndChangable(False)

				self._synchronizeDirectories(self._productId, productDestinationDirectory, productProgressSubject)

				links = list(self._linkFiles.keys())
				links.sort()
				for linkDestination in links:
					linkSource = self._linkFiles[linkDestination]

					with cd(productDestinationDirectory):
						if os.name == "nt":
							if linkSource.startswith("/"):
								linkSource = linkSource[1:]
							if linkDestination.startswith("/"):
								linkDestination = linkDestination[1:]
							linkSource = os.path.join(
								productDestinationDirectory,
								linkSource.replace("/", "\\"),
							)
							linkDestination = os.path.join(
								productDestinationDirectory,
								linkDestination.replace("/", "\\"),
							)
							if os.path.exists(linkDestination):
								if os.path.isdir(linkDestination):
									shutil.rmtree(linkDestination)
								else:
									os.remove(linkDestination)
							logger.info(
								"Symlink => copying '%s' to '%s'",
								linkSource,
								linkDestination,
							)
							if os.path.isdir(linkSource):
								shutil.copytree(linkSource, linkDestination)
							else:
								shutil.copyfile(linkSource, linkDestination)
						else:
							if os.path.exists(linkDestination):
								if os.path.isdir(linkDestination) and not os.path.islink(linkDestination):
									shutil.rmtree(linkDestination)
								else:
									os.remove(linkDestination)
							parts = len(linkDestination.split("/"))
							parts -= len(linkSource.split("/"))
							for _counter in range(parts):
								linkSource = os.path.join("..", linkSource)
							logger.info("Symlink '%s' to '%s'", linkDestination, linkSource)
							os.symlink(linkSource, linkDestination)
			except Exception as error:
				productProgressSubject.setMessage("Failed to sync product %s: %s" % (self._productId, error))
				if packageContentFile and os.path.exists(packageContentFile):
					os.unlink(packageContentFile)
				raise

			if overallProgressSubject:
				overallProgressSubject.addToState(1)

			if productProgressObserver:
				productProgressSubject.detachObserver(productProgressObserver)

		if overallProgressObserver:
			overallProgressSubject.detachObserver(overallProgressObserver)
