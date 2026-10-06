import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from axdesk.core import Desk
from axdesk.http import MAX_BODY, make_server

ROOT = Path(__file__).resolve().parents[1]


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<h1>Synthetic demo</h1>", encoding="utf-8")
        (self.root / "secret.txt").write_text("must not serve", encoding="utf-8")
        desk = Desk(self.root / "desk.sqlite3", ROOT / "data")
        self.server = make_server(desk, self.web, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_state_health_and_static_file(self):
        self.assertEqual(self.request("GET", "/api/health")[0], 200)
        self.assertEqual(json.loads(self.request("GET", "/api/state")[2])["synthetic"], True)
        self.assertIn(b"Synthetic demo", self.request("GET", "/")[2])

    def test_encoded_traversal_is_denied(self):
        for path in ["/../secret.txt", "/%2e%2e/secret.txt", "/%2e%2e%5csecret.txt", "/.hidden"]:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 403)

    def test_external_host_and_origin_cannot_mutate(self):
        body = json.dumps({"id": "S003", "value": "9500"})
        self.assertEqual(self.request("POST", "/api/repair", body, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/repair", body, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/repair", body, {"Origin": "null"})[0], 403)
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertIsNone(next(r for r in state["records"] if r["id"] == "S003")["value"])

    def test_same_origin_write_and_request_bounds(self):
        body = json.dumps({"id": "S003", "value": "9500"})
        origin = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.request("POST", "/api/repair", body, {"Origin": origin})[0], 200)
        self.assertEqual(self.request("POST", "/api/reset", "x" * (MAX_BODY + 1))[0], 413)
        self.assertEqual(self.request("POST", "/api/reset", "{}")[0], 200)
        self.assertEqual(self.request("POST", "/api/reset", "{bad")[0], 400)
        self.assertEqual(self.request("POST", "/api/reset", "{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/repair", '{"id":"S003","value":NaN}')[0], 400)

    def test_export_returns_conflict_before_review(self):
        status, _, body = self.request("GET", "/api/export")
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "validation_blocked")


if __name__ == "__main__":
    unittest.main()
