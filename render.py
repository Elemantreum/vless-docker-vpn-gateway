import base64
import json
import os
import subprocess
import sys
from urllib.parse import parse_qsl, unquote, urlsplit


def gateway_config(outbounds):
    config = {
        "inbounds": [{"listen": "127.0.0.1", "port": 8123, "protocol": "http"}],
        "outbounds": outbounds,
    }
    if len(outbounds) > 1:
        for index, outbound in enumerate(outbounds):
            outbound["tag"] = f"node-{index}"
        config["observatory"] = {
            "subjectSelector": ["node-"],
            "probeUrl": "https://www.gstatic.com/generate_204",
            "probeInterval": "10s",
            "enableConcurrency": True,
        }
        config["routing"] = {
            "balancers": [{"tag": "auto", "selector": ["node-"],
                           "strategy": {"type": "leastPing"}, "fallbackTag": "node-0"}],
            "rules": [{"type": "field", "network": "tcp,udp", "balancerTag": "auto"}],
        }
    return config


def client_outbound(url):
    link = urlsplit(url.strip())
    if link.scheme != "vless" or not link.username or not link.hostname:
        raise ValueError("Укажи ссылку vless:// в VLESS_URL")
    params = dict(parse_qsl(link.query, keep_blank_values=True))
    transport = params.pop("type", "tcp")
    security = params.pop("security", "none")
    user = {
        "id": unquote(link.username),
        "encryption": params.pop("encryption", "none"),
    }
    if params.get("flow"):
        user["flow"] = params.pop("flow")
    stream = {"network": transport, "security": security}
    if security in ("tls", "reality"):
        tls = {"serverName": params.pop("sni", "") or link.hostname}
        for key, field in (("fp", "fingerprint"), ("pbk", "password"),
                           ("sid", "shortId"), ("spx", "spiderX")):
            if key in params:
                tls[field] = params.pop(key)
        if security == "reality" and not tls.get("password"):
            raise ValueError("В ссылке REALITY отсутствует pbk")
        if params.get("alpn"):
            tls["alpn"] = params.pop("alpn").split(",")
        stream[security + "Settings"] = tls
    elif security != "none":
        raise ValueError("Неподдерживаемое значение security")
    if transport == "ws":
        stream["wsSettings"] = {"path": params.pop("path", "/"),
                                "host": params.pop("host", "")}
    elif transport == "grpc":
        mode = params.pop("mode", "gun")
        if mode not in ("gun", "multi"):
            raise ValueError("Неизвестный режим gRPC")
        stream["grpcSettings"] = {"serviceName": params.pop("serviceName", ""),
                                  "authority": params.pop("authority", ""),
                                  "multiMode": mode == "multi"}
    elif transport == "xhttp":
        stream["xhttpSettings"] = {"path": params.pop("path", "/"),
                                   "host": params.pop("host", ""),
                                   "mode": params.pop("mode", "auto")}
    elif transport not in ("raw", "tcp"):
        raise ValueError("Неподдерживаемый транспорт VLESS")
    if params.get("headerType") == "none":
        del params["headerType"]
    unknown = sorted(k for k, value in params.items() if value)
    if unknown:
        raise ValueError("Неподдерживаемые параметры ссылки: " + ", ".join(unknown))
    server = {"address": link.hostname, "port": link.port or 443, "users": [user]}
    return {"protocol": "vless", "settings": {"vnext": [server]}, "streamSettings": stream}


def select_profile(body, name):
    outbounds = []
    body = body.strip()
    if body.startswith(("{", "[")):
        profiles = json.loads(body)
        for profile in profiles if isinstance(profiles, list) else [profiles]:
            if not isinstance(profile, dict) or (name and profile.get("remarks") != name):
                continue
            for outbound in profile.get("outbounds") or []:
                if not isinstance(outbound, dict) or outbound.get("protocol") != "vless":
                    continue
                if outbound.get("proxySettings") or outbound.get("streamSettings", {}).get("sockopt", {}).get("dialerProxy"):
                    continue
                if name:
                    return gateway_config([outbound])
                outbounds.append(outbound)
    else:
        if "://" not in body:
            encoded = "".join(body.split())
            try:
                body = base64.b64decode(encoded + "=" * (-len(encoded) % 4),
                                        altchars=b"-_", validate=True).decode("utf-8-sig")
            except ValueError:
                raise ValueError("Подписка не содержит списка ссылок или JSON Xray") from None
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("vless://"):
                continue
            if name and unquote(line.partition("#")[2]) != name:
                continue
            try:
                outbound = client_outbound(line)
            except ValueError:
                if name:
                    raise
                continue
            if name:
                return gateway_config([outbound])
            outbounds.append(outbound)
    if outbounds:
        return gateway_config(outbounds)
    raise ValueError("В подписке не найден подходящий VLESS-профиль. Проверь имя сервера и формат подписки")


def load_config():
    subscription = os.getenv("SUBSCRIPTION_URL")
    if not subscription:
        return gateway_config([client_outbound(os.getenv("VLESS_URL", ""))])
    if urlsplit(subscription).scheme != "https":
        raise ValueError("SUBSCRIPTION_URL должна начинаться с https://")
    result = subprocess.run(
        ["curl", "--silent", "--fail", "--location", "--proto", "=https",
         "--proto-redir", "=https", "--max-time", "30", "--max-filesize", "8388608",
         "--", subscription], capture_output=True,
    )
    if result.returncode:
        raise ValueError(f"Не удалось скачать HTTPS-подписку (curl {result.returncode})")
    return select_profile(result.stdout.decode("utf-8-sig"), os.getenv("SUBSCRIPTION_SERVER"))


if __name__ == "__main__":
    try:
        config = load_config()
    except (KeyError, ValueError) as error:
        sys.exit(str(error))
    json.dump(config, sys.stdout)
