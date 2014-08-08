#! /bin/bash

echo .
echo   Aktueller PC: $HOSTNAME
echo   You are at PC: $HOSTNAME
echo .
echo   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo   !!                                                                    !!
echo   !!           Zum Starten der opsiclientd Installation                 !!
echo   !!             druecken Sie bitte eine beliebige Taste                !!
echo   !!        Zum Abbrechen schliessen Sie einfach dieses Fenster         !!
echo   !!                                                                    !!
echo   !!          To start the installation of the opsiclientd              !!
echo   !!                        just press any key                          !!
echo   !!                 To cancel just close this window                   !!
echo   !!                                                                    !!
echo   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo .
read

mkdir -p /tmp/opsiclientd
mkdir -p /var/log/opsi-client-agent
cp -r . /tmp/opsiclientd
chmod u+x /tmp/opsiclientd/opsi-script/32/opsi-script-nogui
/tmp/opsiclientd/opsi-script/32/opsi-script-nogui -batch /tmp/opsiclientd/setup.opsiscript /var/log/opsi-client-agent/opsi-script/opsiclientd.log

echo .
echo   Installation abgeschlossen
echo   Installation completed
echo .
