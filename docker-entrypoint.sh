#!/bin/sh
set -e

readonly RSYSLOG_PID="/var/run/rsyslogd.pid"

# first arg is `-f` or `--some-option`
if [ "${1#-}" != "$1" ]; then
	set -- haproxy "$@"
fi

if [ "$1" = 'haproxy' ]; then
	shift # "haproxy"
	# if the user wants "haproxy", let's add a couple useful flags
	#   -W  -- "master-worker mode" (similar to the old "haproxy-systemd-wrapper"; allows for reload via "SIGUSR2")
	#   -db -- disables background mode
	set -- haproxy -W -db "$@"
fi

echo "starting rsyslogd"
# make sure we have rsyslogd's pid file not
# created before
start_rsyslogd() {
  rm -f $RSYSLOG_PID
  rsyslogd -n &
}

start_rsyslogd

echo "starting haproxy_config"
cd /usr/local/haproxy_config/ && ./haproxy_config.py &
sleep 5s

exec "$@"
