FROM samuelhbne/proxy-xray:latest
RUN apk add --no-cache python3 tinyproxy
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY start.sh render.py /opt/gateway/
ENTRYPOINT ["/bin/bash", "/opt/gateway/start.sh"]
