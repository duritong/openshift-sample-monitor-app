# Copyright 2026 the sample-monitor-app contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import time
import json
import uuid
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request
import concurrent.futures

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

MODE = os.environ.get("APP_MODE", "web")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
WRITE_INTERVAL = int(os.environ.get("WRITE_INTERVAL", "60"))
QUORUM_INTERVAL = int(os.environ.get("QUORUM_INTERVAL", "5"))
REPLICAS = int(os.environ.get("REPLICAS", "3"))
STS_NAME = os.environ.get("STATEFULSET_NAME", "backend-app")
SVC_NAME = os.environ.get("SERVICE_NAME", "backend-headless")
NAMESPACE = os.environ.get("NAMESPACE", "sample-app")
PORT = int(os.environ.get("PORT", "8080"))

QUORUM_FILE = os.path.join(DATA_DIR, "quorum.json")


def writer_mode():
    logger.info("Starting writer mode")
    while True:
        try:
            filename = f"write_{int(time.time())}_{uuid.uuid4().hex[:8]}.txt"
            filepath = os.path.join(DATA_DIR, filename)
            with open(filepath, "w") as f:
                f.write(uuid.uuid4().hex)
            logger.info(f"Wrote file {filename}")

            files = [
                os.path.join(DATA_DIR, f)
                for f in os.listdir(DATA_DIR)
                if f.startswith("write_") and f.endswith(".txt")
            ]
            files.sort(key=os.path.getmtime)
            while len(files) > 30:
                oldest = files.pop(0)
                os.remove(oldest)
                logger.info(f"Deleted old file {oldest}")
        except Exception as e:
            logger.error(f"Error in writer: {e}")

        time.sleep(WRITE_INTERVAL)


def check_member_health(member_target):
    for attempt in range(2):
        try:
            req = urllib.request.Request(f"http://{member_target}/healthz")
            with urllib.request.urlopen(req, timeout=1.0) as response:
                if response.getcode() == 200:
                    return member_target, True, "ok"
                if attempt == 1:
                    return member_target, False, f"HTTP {response.getcode()}"
        except Exception as e:
            if attempt == 1:
                return member_target, False, str(e)
        time.sleep(0.5)


def quorum_mode():
    logger.info("Starting quorum mode")
    while True:
        try:
            members = []
            custom_urls = os.environ.get("MEMBER_URLS")
            if custom_urls:
                members = custom_urls.split(",")
            else:
                for i in range(REPLICAS):
                    members.append(
                        f"{STS_NAME}-{i}.{SVC_NAME}.{NAMESPACE}.svc.cluster.local:{PORT}"
                    )

            results = []
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, len(members))
            ) as executor:
                future_to_url = {
                    executor.submit(check_member_health, m): m for m in members
                }
                for future in concurrent.futures.as_completed(future_to_url):
                    results.append(future.result())

            healthy_count = sum(1 for _, is_healthy, _ in results if is_healthy)
            quorum = healthy_count > (len(members) / 2)

            member_details = [
                {"member": m, "healthy": h, "details": d} for m, h, d in results
            ]

            data = {
                "quorum": quorum,
                "total_members": len(members),
                "healthy_members": healthy_count,
                "members": member_details,
                "timestamp": time.time(),
            }

            tmp_file = QUORUM_FILE + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_file, QUORUM_FILE)
            logger.info(f"Updated quorum status. Quorum: {quorum}")

        except Exception as e:
            logger.error(f"Error in quorum: {e}")

        time.sleep(QUORUM_INTERVAL)


class AppHandler(BaseHTTPRequestHandler):
    def _send_response(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-type", content_type)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        if self.path == "/readyz":
            self._send_response(200, "text/plain", "ok")
        elif self.path == "/metrics":
            if not os.path.exists(QUORUM_FILE):
                self._send_response(
                    200,
                    "text/plain",
                    "app_backend_quorum_status 0\napp_backend_healthy_members_count 0\n",
                )
                return

            try:
                with open(QUORUM_FILE, "r") as f:
                    data = json.load(f)

                quorum = 1 if data.get("quorum", False) else 0
                healthy = data.get("healthy_members", 0)
                metrics = f"app_backend_quorum_status {quorum}\napp_backend_healthy_members_count {healthy}\n"
                self._send_response(200, "text/plain", metrics)
            except Exception as e:
                self._send_response(500, "text/plain", f"Error: {e}")
        elif self.path == "/healthz":
            try:
                files = [
                    os.path.join(DATA_DIR, f)
                    for f in os.listdir(DATA_DIR)
                    if f.startswith("write_") and f.endswith(".txt")
                ]
                if not files:
                    self._send_response(500, "text/plain", "No write files found")
                    return

                newest = max(files, key=os.path.getmtime)
                mtime = os.path.getmtime(newest)
                now = time.time()
                diff = now - mtime

                if diff <= (2 * WRITE_INTERVAL):
                    self._send_response(200, "text/plain", "ok")
                else:
                    self._send_response(
                        500, "text/plain", f"Last write was {diff:.2f} seconds ago"
                    )
            except Exception as e:
                self._send_response(500, "text/plain", f"Error checking health: {e}")

        elif self.path == "/":
            if not os.path.exists(QUORUM_FILE):
                self._send_response(
                    500,
                    "application/json",
                    json.dumps({"error": "Quorum data not available yet"}),
                )
                return

            try:
                with open(QUORUM_FILE, "r") as f:
                    data = json.load(f)

                if data.get("quorum", False):
                    self._send_response(
                        200, "application/json", json.dumps(data, indent=2)
                    )
                else:
                    self._send_response(
                        500, "application/json", json.dumps(data, indent=2)
                    )
            except Exception as e:
                self._send_response(
                    500, "application/json", json.dumps({"error": str(e)})
                )
        else:
            self._send_response(404, "text/plain", "Not Found")


def web_mode():
    logger.info(f"Starting web server on port {PORT}")
    server = HTTPServer(("0.0.0.0", PORT), AppHandler)
    server.serve_forever()


if __name__ == "__main__":
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create DATA_DIR: {e}")

    if MODE == "writer":
        writer_mode()
    elif MODE == "quorum":
        quorum_mode()
    else:
        web_mode()
