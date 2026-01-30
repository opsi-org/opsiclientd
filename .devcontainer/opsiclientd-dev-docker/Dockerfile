FROM docker.uib.gmbh/opsi/dev/pybuilder:deb10

ENV DEBIAN_FRONTEND=noninteractive

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
	davfs2

COPY files/ /

RUN chmod +x "/docker-entrypoint.sh"
