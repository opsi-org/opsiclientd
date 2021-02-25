# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2019 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
utils

:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

from opsicommon.logging import logger


def get_include_exclude_product_ids(config_service, includeProductGroupIds, excludeProductGroupIds):
	includeProductIds = []
	excludeProductIds = []

	logger.debug("Given includeProductGroupIds: '%s'", includeProductGroupIds)
	logger.debug("Given excludeProductGroupIds: '%s'", excludeProductGroupIds)

	if includeProductGroupIds:
		includeProductIds = [
			obj.objectId for obj in
			config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=includeProductGroupIds) # pylint: disable=no-member
		]
		logger.debug("Only products ids %s will be regarded.", includeProductIds)

	if excludeProductGroupIds:
		excludeProductIds = [
			obj.objectId for obj in
			config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=excludeProductGroupIds) # pylint: disable=no-member
		]
		logger.debug("Product ids %s will be excluded.", excludeProductIds)

	return includeProductIds, excludeProductIds
