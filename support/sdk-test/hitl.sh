#!/bin/bash

. /opt/_avocado/sdk/environment-setup
ln -s /opt/_avocado/sdk/etc/netconfig /etc/netconfig

exec "$@"
