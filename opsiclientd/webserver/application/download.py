# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0


from fastapi import APIRouter, BackgroundTasks, FastAPI, Query
from fastapi.responses import FileResponse
from opsicommon.logging import get_logger

from opsiclientd.Config import Config
from opsiclientd.webserver.application import get_opsiclientd

logger = get_logger()
config = Config()
download_router = APIRouter()


@download_router.get("/logs")
def download_logs(
	background_tasks: BackgroundTasks, types: list[str] | None = Query(default=None), max_age_days: int | None = Query(default=None)
) -> FileResponse:
	logger.notice("Download logs: types=%s, max_age_days=%s", types, max_age_days)
	file_path = get_opsiclientd().collectLogfiles(types=types, max_age_days=max_age_days)
	background_tasks.add_task(file_path.unlink)
	return FileResponse(file_path)


def setup(app: FastAPI) -> None:
	app.include_router(download_router, prefix="/download")
