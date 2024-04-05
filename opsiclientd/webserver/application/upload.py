# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import os
import tempfile

from fastapi import APIRouter, FastAPI, UploadFile
from fastapi.responses import JSONResponse
from opsicommon.logging import get_logger

from opsiclientd.webserver.application import get_opsiclientd

logger = get_logger()
upload_router = APIRouter()


@upload_router.post("/update/opsiclientd")
async def update_opsiclientd(file: UploadFile) -> JSONResponse:
	logger.notice("Self-update from upload")
	filename = file.filename.split("/")[-1].split("\\")[-1]

	if not filename:
		raise RuntimeError("Filename missing")

	try:
		with tempfile.TemporaryDirectory() as tmp_dir:
			tmp_file = os.path.join(tmp_dir, filename)
			with open(tmp_file, "wb") as file_handle:
				while data := await file.read(100_000):
					file_handle.write(data)
			get_opsiclientd().self_update_from_file(tmp_file)
	except Exception as err:
		logger.error(err, exc_info=True)
		return JSONResponse(str(err), status_code=500)
	return JSONResponse("ok")


def setup(app: FastAPI) -> None:
	app.include_router(upload_router, prefix="/upload")
