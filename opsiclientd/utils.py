# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
utils
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
