#!/bin/bash
set -eu
umask 077
python3 /opt/gateway/render.py > /tmp/xray-client.json
unset VLESS_URL SUBSCRIPTION_URL
xray run -test -config /tmp/xray-client.json
xray run -config /tmp/xray-client.json &
xray_pid=$!
tinyproxy -d -c /etc/tinyproxy/tinyproxy.conf &
proxy_pid=$!
cleanup() {
    kill "$proxy_pid" "$xray_pid" 2>/dev/null || true
    wait || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT
wait -n "$xray_pid" "$proxy_pid"
