FROM docker.uib.gmbh/opsi/dev/pybuilder-ssl3:uib-python-3.11

ARG DOCKER_ENV
ARG DEBIAN_FRONTEND=noninteractive

ENV DOCKER_ENV=${DOCKER_ENV} \
	# python:
	PYTHONFAULTHANDLER=1 \
	PYTHONUNBUFFERED=1 \
	PYTHONHASHSEED=random \
	# pip:
	PIP_NO_CACHE_DIR=off \
	PIP_DISABLE_PIP_VERSION_CHECK=on \
	PIP_DEFAULT_TIMEOUT=100

# System deps:
RUN apt-get update \
	&& apt-get --yes dist-upgrade \
	&& apt-get --yes install \
		cpio \
		vim \
		wget \
		gettext \
		sudo \
		git \
		bash-completion \
		psmisc \
		cifs-utils \
		davfs2 \
	&& pip install poetry

COPY files/ /

RUN chmod +x "/docker-entrypoint.sh"
