#!/bin/sh

NODE="/sys/devices/platform/soc@0/8804000.mmc/bt_reg"
CHECK_INTERVAL=0.5  # 500 ms
MAX_CHECKS=10
CHECK_COUNT=0

start() {
    while [ ! -e "$NODE" ]; do
        CHECK_COUNT=$((CHECK_COUNT + 1))
        if [ "$CHECK_COUNT" -ge "$MAX_CHECKS" ]; then
            echo "szd loop $CHECK_COUNT" >> /opt/bt_log.txt
            exit 1
        fi
        sleep $CHECK_INTERVAL
    done

    echo 1 > $NODE
    cd /usr/src/rubikpi-btapp/
    ./bsa_server -d /dev/ttyHS7 -p ./BCM4345C5_003.006.006.1081.1154.hcd -r 13 -pcmint 31100 -pcmi2s=1011
}

stop() {
    killall bsa_server
    echo 0 > $NODE
}

if [[ $1 == "start" ]]; then
    start
elif [[ $1 == "stop" ]]; then
    stop
else
    exit 1
fi


