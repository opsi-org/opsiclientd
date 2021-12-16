#!/bin/sh

mkdir -p /workspace/opsiclientd-dev-data
mkdir -p /etc/opsi-client-agent
mkdir -p /var/log/opsi-client-agent
mkdir -p /usr/share/opsi-client-agent/opsiclientd

[ -e /workspace/opsiclientd-dev-data/opsiclientd.conf ] || cp /workspace/opsiclientd_data/linux/opsiclientd.conf /workspace/opsiclientd-dev-data/opsiclientd.conf
[ -e /etc/opsi-client-agent/opsiclientd.conf ] || ln -s /workspace/opsiclientd-dev-data/opsiclientd.conf /etc/opsi-client-agent/opsiclientd.conf
[ -e /workspace/opsiclientd_data/common/static_html ] || ln -s /usr/share/opsi-client-agent/opsiclientd/static_html /workspace/opsiclientd_data/common/static_html

if [ ! -e /usr/bin/opsi-notifier ]; then
	cat <<EOF > /usr/bin/opsi-notifier
#!/bin/sh
echo \$@ >> /tmp/opsi-notifier-call.log
EOF
	chmod +x /usr/bin/opsi-notifier
fi

poetry install
