"""Focused synthetic credential-boundary regression; no real model calls."""
import importlib.util
import json
from pathlib import Path
import secrets
import threading
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class BrokerBoundary(unittest.TestCase):
    def test_bootstrap_and_worker_authority(self):
        spec = importlib.util.spec_from_file_location('capy_broker', Path(__file__).with_name('broker.py'))
        broker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(broker)
        canary = 'Bearer CAPY_SYNTHETIC_PROVIDER_CANARY_TEST'
        received = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                received.append(self.headers.get('Authorization') == canary)
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        gateway = ThreadingHTTPServer(('127.0.0.1', 0), broker.Handler)
        cap, boot = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        broker.args = SimpleNamespace(mode='gateway', bootstrap=boot, worker_token=cap,
                                      upstream=f'http://127.0.0.1:{upstream.server_port}/v1')
        for server in (upstream, gateway):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        def request(path, method='POST', auth=canary, model=broker.MODEL):
            data = json.dumps({'model': model}).encode() if method == 'POST' else None
            req = urllib.request.Request(f'http://127.0.0.1:{gateway.server_port}{path}', data,
                                         {'Authorization': auth}, method=method)
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    response.read()
                    return response.status
            except urllib.error.HTTPError as ex:
                with ex:
                    ex.read()
                    return ex.code
        prefix = '/bootstrap/' + boot
        try:
            self.assertEqual(request(prefix + '/v1/invalid'), 403)
            self.assertEqual(request(prefix + '/v1/responses', method='GET'), 405)
            self.assertEqual(request(prefix + '/v1/responses', model='different-model'), 403)
            self.assertEqual(request(prefix + '/v1/models', method='GET'), 200)
            self.assertIsNone(broker.authorization)
            self.assertEqual(request(prefix + '/v1/responses', auth=''), 401)
            self.assertEqual(request('/v1/responses', auth=''), 401)
            self.assertEqual(request(prefix + '/v1/responses'), 200)
            self.assertEqual(broker.authorization, canary)
            self.assertEqual(broker.args.bootstrap, '')
            self.assertEqual(request(prefix + '/v1/responses', auth=canary+'changed'), 403)
            self.assertEqual(request('/v1/responses', auth='Bearer wrong'), 401)
            self.assertEqual(request('/v1/responses', auth='Bearer '+cap), 200)
            self.assertEqual(broker.authorization, canary)
            self.assertEqual(received, [True, True])
        finally:
            for server in (gateway, upstream):
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
