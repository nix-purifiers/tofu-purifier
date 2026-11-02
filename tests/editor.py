# SPDX-License-Identifier: MIT
"""Check real language-server evaluation of the locked fixture imports."""
import json
import os
import select
import subprocess
import time
from pathlib import Path

root = Path.cwd()
server = subprocess.Popen(['tofu-ls', 'serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def send(message):
    payload = json.dumps({'jsonrpc': '2.0', **message}).encode()
    server.stdin.write(f'Content-Length: {len(payload)}\r\n\r\n'.encode() + payload)
    server.stdin.flush()


pending = b''

def receive():
    global pending
    deadline = time.monotonic() + 30
    while True:
        if b'\r\n\r\n' in pending:
            headers, body = pending.split(b'\r\n\r\n', 1)
            length = int(next(line.split(b':', 1)[1] for line in headers.split(b'\r\n') if line.lower().startswith(b'content-length:')))
            if len(body) >= length:
                pending = body[length:]
                return json.loads(body[:length])
        remaining = deadline - time.monotonic()
        assert remaining > 0 and select.select([server.stdout], [], [], remaining)[0], 'language server timed out'
        chunk = os.read(server.stdout.fileno(), 65536)
        assert chunk, 'language server exited before responding'
        pending += chunk


try:
    send({'id': 1, 'method': 'initialize', 'params': {'processId': None, 'rootUri': root.as_uri(), 'workspaceFolders': [{'uri': root.as_uri(), 'name': 'fixture'}], 'capabilities': {'workspace': {'workspaceFolders': True}}}})
    while True:
        message = receive()
        if message.get('id') == 1:
            assert 'result' in message, message
            break
    send({'method': 'initialized', 'params': {}})
    send({'method': 'textDocument/didOpen', 'params': {'textDocument': {'uri': (root / 'main.tf').as_uri(), 'languageId': 'opentofu', 'version': 1, 'text': (root / 'main.tf').read_text()}}})
    text = (root / 'main.tf').read_text().splitlines()
    line = next(i for i, value in enumerate(text) if 'module.label.id' in value)
    character = text[line].index('module.label.id') + len('module.label.')
    deadline = time.monotonic() + 30
    request = 2
    while True:
        send({'id': request, 'method': 'textDocument/definition', 'params': {
            'textDocument': {'uri': (root / 'main.tf').as_uri()},
            'position': {'line': line, 'character': character}}})
        while True:
            message = receive()
            if message.get('id') == request:
                break
        if message.get('result'):
            assert 'outputs.tf' in json.dumps(message['result']), message
            break
        assert time.monotonic() < deadline, message
        time.sleep(.1)
        request += 1
    send({'id': request + 1, 'method': 'shutdown', 'params': None})
    while receive().get('id') != request + 1:
        pass
    send({'method': 'exit', 'params': None})
    server.stdin.close()
    server.wait(timeout=10)
    assert server.returncode == 0
finally:
    if server.poll() is None:
        server.kill()
        server.wait()
print('language server resolved the locked OpenTofu module output')
