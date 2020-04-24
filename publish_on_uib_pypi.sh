#!/bin/bash

repo_name="uibpypi"
repo_url="http://pypi.uib.gmbh:8080"
repo_username="upload"
repo_password=""
pkg_name=$(grep "^name = " pyproject.toml | head -n1 | cut -d '"' -f2)
pkg_version=$(grep "^version = " pyproject.toml | head -n1 | cut -d '"' -f2)

[ -z "${UIB_PYPI_NAME}" ] || repo_name="${UIB_PYPI_NAME}"
[ -z "${UIB_PYPI_URL}" ] || repo_url="${UIB_PYPI_URL}"
[ -z "${UIB_PYPI_USERNAME}" ] || repo_username="${UIB_PYPI_USERNAME}"
[ -z "${UIB_PYPI_PASSWORD}" ] || repo_password="${UIB_PYPI_PASSWORD}"

if [ -z "${repo_password}" ]; then
	echo -n "password for user ${repo_username}: "
	read -s repo_password
	echo ""
fi

whl_name="${pkg_name/-/_}"

poetry build

curl -s -u "${repo_username}:${repo_password}" --form ":action=remove_pkg" --form "name=${pkg_name}" --form "version=${pkg_version}" "${repo_url}" >/dev/null
if [ "$whl_name" != "$pgk_name" ]; then
	curl -s -u "${repo_username}:${repo_password}" --form ":action=remove_pkg" --form "name=${whl_name}" --form "version=${pkg_version}" "${repo_url}" >/dev/null
fi

poetry publish -r "${repo_name}" -u "${repo_username}" -p "${repo_password}"
