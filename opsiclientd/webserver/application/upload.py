# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

import os
import shutil
import tempfile

from fastapi import APIRouter, FastAPI, UploadFile
from fastapi.responses import JSONResponse
from opsi.logging import get_logger
from starlette.concurrency import run_in_threadpool

from opsiclientd.webserver.application import get_opsiclientd

logger = get_logger()
upload_router = APIRouter()


def _save_and_update(file: UploadFile, filename: str) -> None:
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_file = os.path.join(tmp_dir, filename)
		with open(tmp_file, "wb") as file_handle:
			shutil.copyfileobj(file.file, file_handle)
		get_opsiclientd().self_update_from_file(tmp_file)


@upload_router.post("/update/opsiclientd")
async def update_opsiclientd(file: UploadFile) -> JSONResponse:
	logger.notice("Self-update from upload")
	if not file.filename:
		raise RuntimeError("Filename missing")

	filename = file.filename.split("/")[-1].split("\\")[-1]

	try:
		await run_in_threadpool(_save_and_update, file, filename)
	except Exception as err:
		logger.exception(err)
		return JSONResponse(str(err), status_code=500)
	return JSONResponse("ok")


def setup(app: FastAPI) -> None:
	app.include_router(upload_router, prefix="/upload")
