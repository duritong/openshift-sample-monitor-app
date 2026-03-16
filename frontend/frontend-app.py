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
import sys
import time
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request
from urllib.error import URLError
import ssl

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MODE = os.environ.get("APP_MODE", "web")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend.sample-app.svc.cluster.local:8080")
K8S_API_URL = os.environ.get("K8S_API_URL", "https://kubernetes.default.svc/healthz")
PORT = int(os.environ.get("PORT", "8080"))
WORKER_INTERVAL = int(os.environ.get("WORKER_INTERVAL", "5"))

BACKEND_STATE_FILE = os.path.join(DATA_DIR, "backend_state.json")
K8S_STATE_FILE = os.path.join(DATA_DIR, "k8s_state.json")

def worker_mode():
    logger.info(f"Starting worker mode, watching {BACKEND_URL} and {K8S_API_URL}")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    while True:
        try:
            k8s_req = urllib.request.Request(K8S_API_URL)
            with urllib.request.urlopen(k8s_req, timeout=2.0, context=ctx) as response:
                k8s_up = (response.getcode() == 200)
        except Exception as e:
            logger.error(f"Error fetching k8s api state: {e}")
            k8s_up = False
            
        try:
            tmp_k8s = K8S_STATE_FILE + ".tmp"
            with open(tmp_k8s, "w") as f:
                json.dump({"k8s_api_health": k8s_up, "timestamp": time.time()}, f)
            os.replace(tmp_k8s, K8S_STATE_FILE)
        except Exception as e:
            logger.error(f"Error saving k8s state: {e}")

        try:
            req = urllib.request.Request(f"{BACKEND_URL}/")
            with urllib.request.urlopen(req, timeout=2.0) as response:
                if response.getcode() == 200:
                    data = response.read().decode('utf-8')
                    tmp_file = BACKEND_STATE_FILE + ".tmp"
                    with open(tmp_file, "w") as f:
                        f.write(data)
                    os.replace(tmp_file, BACKEND_STATE_FILE)
                    logger.info("Successfully fetched and saved backend state")
                else:
                    logger.warning(f"Backend returned HTTP {response.getcode()}")
        except Exception as e:
            logger.error(f"Error fetching backend state: {e}")
        
        time.sleep(WORKER_INTERVAL)

def check_backend_connection():
    try:
        start_time = time.time()
        req = urllib.request.Request(f"{BACKEND_URL}/readyz")
        with urllib.request.urlopen(req, timeout=0.5) as response:
            latency = time.time() - start_time
            if response.getcode() == 200:
                return True, "ok", latency
            return False, f"HTTP {response.getcode()}", latency
    except Exception as e:
        return False, str(e), 0.0

class AppHandler(BaseHTTPRequestHandler):
    def _send_response(self, code, content_type, body):
        self.send_response(code)
        self.send_header('Content-type', content_type)
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))

    def do_GET(self):
        if self.path == '/readyz':
            self._send_response(200, 'text/plain', 'ok')
        elif self.path == '/healthz':
            connected, msg, _ = check_backend_connection()
            k8s_health = False
            if os.path.exists(K8S_STATE_FILE):
                try:
                    mtime = os.path.getmtime(K8S_STATE_FILE)
                    if (time.time() - mtime) <= 15:
                        with open(K8S_STATE_FILE, "r") as f:
                            k8s_state = json.load(f)
                        k8s_health = k8s_state.get("k8s_api_health", False)
                except:
                    pass

            if connected and k8s_health:
                self._send_response(200, 'text/plain', 'ok')
            elif not connected:
                self._send_response(500, 'text/plain', f'Backend connection failed: {msg}')
            else:
                self._send_response(500, 'text/plain', 'K8s API health check failed')
        elif self.path == '/metrics':
            connected, _, latency = check_backend_connection()
            metrics = f"app_frontend_backend_connected {1 if connected else 0}\n"
            metrics += f"app_frontend_backend_latency_seconds {latency:.4f}\n"
            
            k8s_health_metric = 0
            if os.path.exists(K8S_STATE_FILE):
                try:
                    mtime = os.path.getmtime(K8S_STATE_FILE)
                    if (time.time() - mtime) <= 15:
                        with open(K8S_STATE_FILE, "r") as f:
                            k8s_state = json.load(f)
                        if k8s_state.get("k8s_api_health", False):
                            k8s_health_metric = 1
                except:
                    pass
            metrics += f"app_frontend_k8s_api_health {k8s_health_metric}\n"

            quorum = 0
            if os.path.exists(BACKEND_STATE_FILE):
                try:
                    mtime = os.path.getmtime(BACKEND_STATE_FILE)
                    if (time.time() - mtime) <= 15:
                        with open(BACKEND_STATE_FILE, "r") as f:
                            backend_state = json.load(f)
                        if backend_state.get("quorum", False):
                            quorum = 1
                except:
                    pass
            metrics += f"app_frontend_backend_quorum_status {quorum}\n"
            self._send_response(200, 'text/plain', metrics)
        elif self.path == '/':
            connected, msg, latency = check_backend_connection()
            
            k8s_health = False
            if os.path.exists(K8S_STATE_FILE):
                try:
                    mtime = os.path.getmtime(K8S_STATE_FILE)
                    if (time.time() - mtime) > 15:
                        logger.warning("K8s state is stale")
                    else:
                        with open(K8S_STATE_FILE, "r") as f:
                            k8s_state = json.load(f)
                        k8s_health = k8s_state.get("k8s_api_health", False)
                except Exception as e:
                    logger.error(f"Error reading k8s state: {e}")

            backend_state = {}
            quorum = False
            if os.path.exists(BACKEND_STATE_FILE):
                try:
                    mtime = os.path.getmtime(BACKEND_STATE_FILE)
                    if (time.time() - mtime) > 15:
                        logger.warning("Backend state is stale")
                    else:
                        with open(BACKEND_STATE_FILE, "r") as f:
                            backend_state = json.load(f)
                        quorum = backend_state.get("quorum", False)
                except Exception as e:
                    logger.error(f"Error reading backend state: {e}")
            
            response_data = {
                "backend_connected": connected,
                "backend_connection_msg": msg,
                "backend_latency": latency,
                "backend_quorum": quorum,
                "k8s_api_health": k8s_health,
                "backend_data": backend_state
            }
            
            if connected and quorum and k8s_health:
                self._send_response(200, 'application/json', json.dumps(response_data, indent=2))
            else:
                self._send_response(500, 'application/json', json.dumps(response_data, indent=2))
        else:
            self._send_response(404, 'text/plain', 'Not Found')

def web_mode():
    logger.info(f"Starting web server on port {PORT}")
    server = HTTPServer(('0.0.0.0', PORT), AppHandler)
    server.serve_forever()

if __name__ == '__main__':
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create DATA_DIR: {e}")
            
    if MODE == "worker":
        worker_mode()
    else:
        web_mode()
