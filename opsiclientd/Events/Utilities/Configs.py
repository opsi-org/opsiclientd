# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

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
Event configuration utilities.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import copy as pycopy

from OPSI.Logger import Logger, LOG_DEBUG
from OPSI.Types import forceBool, forceList, forceUnicode, forceUnicodeLower
from OPSI.Util import objectToBeautifiedText

from opsiclientd.Config import Config
from opsiclientd.Localization import getLanguage

__all__ = ['getEventConfigs']

logger = Logger()
config = Config()


def getEventConfigs():
	preconditions = {}
	for (section, options) in config.getDict().items():
		section = section.lower()
		if section.startswith('precondition_'):
			preconditionId = section.split('_', 1)[1]
			preconditions[preconditionId] = {}
			try:
				for key in options.keys():
					preconditions[preconditionId][key] = forceBool(options[key])
				logger.info(u"Precondition '%s' created: %s" % (preconditionId, preconditions[preconditionId]))
			except Exception as e:
				logger.error(u"Failed to parse precondition '%s': %s" % (preconditionId, forceUnicode(e)))

	rawEventConfigs = {}
	for (section, options) in config.getDict().items():
		section = section.lower()
		if section.startswith('event_'):
			eventConfigId = section.split('_', 1)[1]
			if not eventConfigId:
				logger.error(u"No event config id defined in section '%s'" % section)
				continue

			rawEventConfigs[eventConfigId] = {
				'active': True,
				'args': {},
				'super': None,
				'precondition': None
			}

			try:
				for key in options.keys():
					if key.lower() == 'active':
						rawEventConfigs[eventConfigId]['active'] = unicode(options[key]).lower() not in ('0', 'false', 'off', 'no')
					elif key.lower() == 'super':
						rawEventConfigs[eventConfigId]['super'] = options[key]
						if rawEventConfigs[eventConfigId]['super'].startswith('event_'):
							rawEventConfigs[eventConfigId]['super'] = rawEventConfigs[eventConfigId]['super'].split('_', 1)[1]
					else:
						rawEventConfigs[eventConfigId]['args'][key.lower()] = options[key]

				if '{' in eventConfigId:
					superEventName, precondition = eventConfigId.split('{', 1)
					if not rawEventConfigs[eventConfigId]['super']:
						rawEventConfigs[eventConfigId]['super'] = superEventName.strip()
					rawEventConfigs[eventConfigId]['precondition'] = precondition.replace('}', '').strip()
			except Exception as e:
				logger.error(u"Failed to parse event config '%s': %s" % (eventConfigId, forceUnicode(e)))

	def __inheritArgsFromSuperEvents(rawEventConfigsCopy, args, superEventConfigId):
		if not superEventConfigId in rawEventConfigsCopy.keys():
			logger.error(u"Super event '%s' not found" % superEventConfigId)
			return args
		superArgs = pycopy.deepcopy(rawEventConfigsCopy[superEventConfigId]['args'])
		if rawEventConfigsCopy[superEventConfigId]['super']:
			superArgs = __inheritArgsFromSuperEvents(rawEventConfigsCopy, superArgs, rawEventConfigsCopy[superEventConfigId]['super'])
		superArgs.update(args)
		return superArgs

	rawEventConfigsCopy = pycopy.deepcopy(rawEventConfigs)
	for eventConfigId in rawEventConfigs.keys():
		if rawEventConfigs[eventConfigId]['super']:
			rawEventConfigs[eventConfigId]['args'] = __inheritArgsFromSuperEvents(
									rawEventConfigsCopy,
									rawEventConfigs[eventConfigId]['args'],
									rawEventConfigs[eventConfigId]['super'])

	eventConfigs = {}
	for (eventConfigId, rawEventConfig) in rawEventConfigs.items():
		try:
			if (rawEventConfig['args'].get('type', 'template').lower() == 'template'):
				continue

			if not rawEventConfig['active']:
				logger.notice(u"Event config '%s' is deactivated" % eventConfigId)
				continue

			eventConfigs[eventConfigId] = {'preconditions': {}}
			if rawEventConfig.get('precondition'):
				precondition = preconditions.get(rawEventConfig['precondition'])
				if not precondition:
					logger.error(u"Precondition '%s' referenced by event config '%s' not found" % (precondition, eventConfigId))
				else:
					eventConfigs[eventConfigId]['preconditions'] = precondition

			for (key, value) in rawEventConfig['args'].items():
				try:
					if key == 'type':
						eventConfigs[eventConfigId]['type'] = value
					elif key == 'wql':
						eventConfigs[eventConfigId]['wql'] = value
					elif key.startswith(('action_message', 'message')):
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except Exception:
							mLanguage = None

						if mLanguage:
							if mLanguage == getLanguage():
								eventConfigs[eventConfigId]['actionMessage'] = value
						elif not eventConfigs[eventConfigId].get('actionMessage'):
							eventConfigs[eventConfigId]['actionMessage'] = value
					elif key.startswith('shutdown_warning_message'):
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except Exception:
							mLanguage = None

						if mLanguage:
							if mLanguage == getLanguage():
								eventConfigs[eventConfigId]['shutdownWarningMessage'] = value
						elif not eventConfigs[eventConfigId].get('shutdownWarningMessage'):
							eventConfigs[eventConfigId]['shutdownWarningMessage'] = value
					elif key.startswith('name'):
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except Exception:
							mLanguage = None

						if mLanguage:
							if mLanguage == getLanguage():
								eventConfigs[eventConfigId]['name'] = value
						elif not eventConfigs[eventConfigId].get('name'):
							eventConfigs[eventConfigId]['name'] = value
					elif key == 'interval':
						eventConfigs[eventConfigId]['interval'] = int(value)
					elif key == 'max_repetitions':
						eventConfigs[eventConfigId]['maxRepetitions'] = int(value)
					elif key == 'activation_delay':
						eventConfigs[eventConfigId]['activationDelay'] = int(value)
					elif key == 'notification_delay':
						eventConfigs[eventConfigId]['notificationDelay'] = int(value)
					elif key == 'action_warning_time':
						eventConfigs[eventConfigId]['actionWarningTime'] = int(value)
					elif key == 'action_user_cancelable':
						eventConfigs[eventConfigId]['actionUserCancelable'] = int(value)
					elif key == 'shutdown':
						eventConfigs[eventConfigId]['shutdown'] = forceBool(value)
					elif key == 'reboot':
						eventConfigs[eventConfigId]['reboot'] = forceBool(value)
					elif key == 'shutdown_warning_time':
						eventConfigs[eventConfigId]['shutdownWarningTime'] = int(value)
					elif key == 'shutdown_warning_repetition_time':
						eventConfigs[eventConfigId]['shutdownWarningRepetitionTime'] = int(value)
					elif key == 'shutdown_user_cancelable':
						eventConfigs[eventConfigId]['shutdownUserCancelable'] = int(value)
					elif key == 'block_login':
						eventConfigs[eventConfigId]['blockLogin'] = forceBool(value)
					elif key == 'lock_workstation':
						eventConfigs[eventConfigId]['lockWorkstation'] = forceBool(value)
					elif key == 'logoff_current_user':
						eventConfigs[eventConfigId]['logoffCurrentUser'] = forceBool(value)
					elif key == 'process_shutdown_requests':
						eventConfigs[eventConfigId]['processShutdownRequests'] = forceBool(value)
					elif key == 'get_config_from_service':
						eventConfigs[eventConfigId]['getConfigFromService'] = forceBool(value)
					elif key == 'update_config_file':
						eventConfigs[eventConfigId]['updateConfigFile'] = forceBool(value)
					elif key == 'write_log_to_service':
						eventConfigs[eventConfigId]['writeLogToService'] = forceBool(value)
					elif key == 'cache_products':
						eventConfigs[eventConfigId]['cacheProducts'] = forceBool(value)
					elif key == 'cache_max_bandwidth':
						eventConfigs[eventConfigId]['cacheMaxBandwidth'] = int(value)
					elif key == 'cache_dynamic_bandwidth':
						eventConfigs[eventConfigId]['cacheDynamicBandwidth'] = forceBool(value)
					elif key == 'use_cached_products':
						eventConfigs[eventConfigId]['useCachedProducts'] = forceBool(value)
					elif key == 'sync_config_from_server':
						eventConfigs[eventConfigId]['syncConfigFromServer'] = forceBool(value)
					elif key == 'sync_config_to_server':
						eventConfigs[eventConfigId]['syncConfigToServer'] = forceBool(value)
					elif key == 'post_sync_config_from_server':
						eventConfigs[eventConfigId]['postSyncConfigFromServer'] = forceBool(value)
					elif key == 'post_sync_config_to_server':
						eventConfigs[eventConfigId]['postSyncConfigToServer'] = forceBool(value)
					elif key == 'use_cached_config':
						eventConfigs[eventConfigId]['useCachedConfig'] = forceBool(value)
					elif key == 'update_action_processor':
						eventConfigs[eventConfigId]['updateActionProcessor'] = forceBool(value)
					elif key == 'action_type':
						eventConfigs[eventConfigId]['actionType'] = forceUnicodeLower(value)
					elif key == 'event_notifier_command':
						eventConfigs[eventConfigId]['eventNotifierCommand'] = config.replace(forceUnicodeLower(value), escaped=True)
					elif key == 'event_notifier_desktop':
						eventConfigs[eventConfigId]['eventNotifierDesktop'] = forceUnicodeLower(value)
					elif key == 'process_actions':
						eventConfigs[eventConfigId]['processActions'] = forceBool(value)
					elif key == 'action_notifier_command':
						eventConfigs[eventConfigId]['actionNotifierCommand'] = config.replace(forceUnicodeLower(value), escaped=True)
					elif key == 'action_notifier_desktop':
						eventConfigs[eventConfigId]['actionNotifierDesktop'] = forceUnicodeLower(value)
					elif key == 'action_processor_command':
						eventConfigs[eventConfigId]['actionProcessorCommand'] = forceUnicodeLower(value)
					elif key == 'action_processor_desktop':
						eventConfigs[eventConfigId]['actionProcessorDesktop'] = forceUnicodeLower(value)
					elif key == 'action_processor_timeout':
						eventConfigs[eventConfigId]['actionProcessorTimeout'] = int(value)
					elif key == 'trusted_installer_detection':
						eventConfigs[eventConfigId]['trustedInstallerDetection'] = forceBool(value)
					elif key == 'shutdown_notifier_command':
						eventConfigs[eventConfigId]['shutdownNotifierCommand'] = config.replace(forceUnicodeLower(value), escaped=True)
					elif key == 'shutdown_notifier_desktop':
						eventConfigs[eventConfigId]['shutdownNotifierDesktop'] = forceUnicodeLower(value)
					elif key == 'pre_action_processor_command':
						eventConfigs[eventConfigId]['preActionProcessorCommand'] = config.replace(forceUnicodeLower(value), escaped=True)
					elif key == 'post_action_processor_command':
						eventConfigs[eventConfigId]['postActionProcessorCommand'] = config.replace(forceUnicodeLower(value), escaped=True)
					elif key == 'trusted_installer_check':
						eventConfigs[eventConfigId]['trustedInstallerCheck'] = forceBool(value)
					elif key == 'action_processor_productids':
						eventConfigs[eventConfigId]['actionProcessorProductIds'] = value.strip().split(",")
					elif key == 'exclude_product_group_ids':
						eventConfigs[eventConfigId]['excludeProductGroupIds'] = forceList(value)
					elif key == 'include_product_group_ids':
						eventConfigs[eventConfigId]['includeProductGroupIds'] = forceList(value)
					elif key == 'working_window':
						eventConfigs[eventConfigId]['workingWindow'] = unicode(value)
					else:
						logger.error(u"Skipping unknown option '%s' in definition of event '%s'" % (key, eventConfigId))
				except Exception as e:
					logger.logException(e, LOG_DEBUG)
					logger.error(u"Failed to set event config argument '%s' to '%s': %s" % (key, value, e))

			logger.info(
				u"Event config {!r} args:\n {}",
				eventConfigId,
				objectToBeautifiedText(eventConfigs[eventConfigId])
			)
		except Exception as e:
			logger.logException(e)

	return eventConfigs