"""Exercise the real API image; successful sends use a fixture CLI, never WhatsApp."""

import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

image = sys.argv[1]
prefix = "wacli-api-smoke-" + uuid.uuid4().hex[:12]
volume = prefix + "-data"
containers = []
token = secrets.token_hex(32)
replacement = secrets.token_hex(32)


def docker(*args, check=True, input=None):
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        input=input,
        text=True,
        timeout=60,
    )


def request(base, path, key=None, body=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(
        base + path,
        headers=headers,
        data=None if body is None else json.dumps(body).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(
                raw
            ) if response.headers.get_content_type() == "application/json" else raw
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def start(suffix, key):
    name = prefix + "-" + suffix
    docker(
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-p",
        "127.0.0.1::9090",
        "-v",
        volume + ":/data",
        "-e",
        "API_TOKEN=" + key,
        "-e",
        "PORT=9090",
        image,
    )
    containers.append(name)
    address = docker("port", name, "9090/tcp").stdout.strip()
    base = "http://" + address
    for _ in range(100):
        try:
            if request(base, "/healthz")[0] == 200:
                return name, base
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise AssertionError(
        "API did not become ready: " + docker("logs", name, check=False).stderr
    )


try:
    for environment in [
        [],
        ["-e", "API_TOKEN=short"],
        ["-e", "API_TOKEN=" + token, "-e", "PORT=0"],
    ]:
        invalid = docker("run", "--rm", *environment, image, check=False)
        assert invalid.returncode != 0, "Invalid configuration accepted"

    tests = str(Path(__file__).resolve().parent)
    unit = docker(
        "run",
        "--rm",
        "-v",
        tests + ":/checks:ro",
        "--entrypoint",
        "/opt/venv/bin/python",
        image,
        "-m",
        "unittest",
        "discover",
        "-s",
        "/checks",
        "-p",
        "test_process.py",
    )
    print(unit.stderr.strip())

    docker("volume", "create", volume)
    name, base = start("first", token)
    body = {"message": "Hello", "to": "+15551234567"}
    assert request(base, "/session")[0] == 401
    assert request(base, "/session", "wrong")[0] == 401
    assert request(base, "/messages", body=body)[0] == 401
    assert request(base, "/messages", "wrong", body)[0] == 401
    assert request(base, "/session", token) == (200, {"authenticated": False})
    assert request(base, "/messages", token, body)[0] == 409
    for invalid_body in [
        {"message": "Hello", "to": "--help"},
        {"message": " ", "to": "+15551234567"},
        {"message": "Hello", "to": "+15551234567", "command": "sh"},
    ]:
        assert request(base, "/messages", token, invalid_body)[0] == 422
    assert request(base, "/docs")[0] == 200
    schema = request(base, "/openapi.json")[1]
    assert schema["paths"]["/messages"]["post"]["security"] == [{"HTTPBearer": []}]
    assert (
        docker(
            "exec", name, "stat", "-c", "%a:%u", "/data/store/session.db"
        ).stdout.strip()
        == "600:10001"
    )
    assert (
        docker("exec", name, "stat", "-c", "%a:%u", "/data/store").stdout.strip()
        == "700:10001"
    )
    health = json.loads(docker("exec", name, "wacli-run", "--json", "doctor").stdout)
    assert health["data"]["fts_enabled"] is True
    docker(
        "exec",
        name,
        "gosu",
        "wacli",
        "sh",
        "-c",
        "printf persisted > /data/store/persistence.txt",
    )
    docker("stop", "--time", "10", name)
    containers.remove(name)

    name, base = start("second", replacement)
    assert request(base, "/session", token)[0] == 401
    assert request(base, "/session", replacement)[0] == 200
    assert (
        docker("exec", name, "cat", "/data/store/persistence.txt").stdout == "persisted"
    )

    # Replace only the disposable test container's CLI to verify the HTTP adapter.
    fixture = """#!/usr/bin/python3
import json,os,sys,time
args=sys.argv[1:]
if 'sync' in args:
    open('/data/sync.pid','w').write(str(os.getpid()))
    while True: time.sleep(1)
if 'auth' in args:
    print(json.dumps({'success':True,'data':{'authenticated':True}}))
else:
    with open('/data/sends.ndjson','a') as f: f.write(json.dumps(args)+'\\n')
    message=next(x.split('=',1)[1] for x in args if x.startswith('--message='))
    if message=='upstream-failure':
        print(json.dumps({'success':False,'data':None,'error':'fixture failure'}))
        sys.exit(1)
    data={'id':'fixture-id','sent':True,'to':'15551234567@s.whatsapp.net'}
    if message=='store-warning': data['store_warning']='fixture history write failed'
    print(json.dumps({'success':True,'data':data}))
"""
    docker(
        "exec",
        "-i",
        name,
        "sh",
        "-c",
        "cat > /usr/local/bin/wacli && chmod 755 /usr/local/bin/wacli",
        input=fixture,
    )
    message = "$(touch /data/injected); --to=other\nHello"
    code, sent = request(
        base, "/messages", replacement, {"message": message, "to": "+15551234567"}
    )
    assert code == 202 and sent["sent"] is True and sent["id"] == "fixture-id"
    assert (
        docker("exec", name, "test", "-e", "/data/injected", check=False).returncode
        != 0
    )
    assert (
        request(
            base,
            "/messages",
            replacement,
            {"message": "upstream-failure", "to": "+15551234567"},
        )[0]
        == 502
    )
    code, warning = request(
        base,
        "/messages",
        replacement,
        {"message": "store-warning", "to": "+15551234567"},
    )
    assert code == 202 and warning["store_warning"] == "fixture history write failed"
    sends = docker("exec", name, "cat", "/data/sends.ndjson").stdout.splitlines()
    assert len(sends) == 3, "API retried a send"
    assert "--message=" + message in json.loads(sends[0])

    for _ in range(40):
        if (
            docker("exec", name, "test", "-f", "/data/sync.pid", check=False).returncode
            == 0
        ):
            break
        time.sleep(0.2)
    docker(
        "exec",
        name,
        "python3",
        "-c",
        "import os,signal;os.kill(int(open('/data/sync.pid').read()),signal.SIGTERM)",
    )
    for _ in range(40):
        if docker("inspect", name, check=False).returncode != 0:
            containers.remove(name)
            break
        time.sleep(0.2)
    else:
        raise AssertionError("API stayed running after its sync worker exited")
    print(
        "API authentication, validation, CLI forwarding, failure handling, token rotation and persistence passed."
    )
finally:
    for name in containers:
        docker("stop", "--time", "10", name, check=False)
    docker("volume", "rm", volume, check=False)
