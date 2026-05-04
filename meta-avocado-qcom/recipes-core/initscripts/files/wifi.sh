#!/bin/sh

start() {
	wpa_supplicant  -B -Dnl80211 -iwlan0 -c /etc/wpa_supplicant.conf
}

stop() {
	killall -9 wpa_supplicant
}

if [[ $1 == "start" ]]; then
    start
elif [[ $1 == "stop" ]]; then
    stop
else
    exit 1
fi

