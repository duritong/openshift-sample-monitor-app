import os
import sys
import time
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request
from urllib.error import URLError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MODE = os.environ.get("APP_MODE", "web")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend.sample-app.svc.cluster.local:8080")
PORT = int(os.environ.get("PORT", "8080"))
WORKER_INTERVAL = int(os.environ.get("WORKER_INTERVAL", "5"))

BACKEND_STATE_FILE = os.path.join(DATA_DIR, "backend_state.json")

def worker_mode():
    logger.info(f"Starting worker mode, watching {BACKEND_URL}")
    while True:
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
        req = urllib.request.Request(f"{BACKEND_URL}/readyz")
        with urllib.request.urlopen(req, timeout=0.5) as response:
            if response.getcode() == 200:
                return True, "ok"
            return False, f"HTTP {response.getcode()}"
    except Exception as e:
        return False, str(e)

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
            connected, msg = check_backend_connection()
            if connected:
                self._send_response(200, 'text/plain', 'ok')
            else:
                self._send_response(500, 'text/plain', f'Backend connection failed: {msg}')
        elif self.path == '/':
            connected, msg = check_backend_connection()
            
            backend_state = {}
            quorum = False
            if os.path.exists(BACKEND_STATE_FILE):
                try:
                    with open(BACKEND_STATE_FILE, "r") as f:
                        backend_state = json.load(f)
                    quorum = backend_state.get("quorum", False)
                except Exception as e:
                    logger.error(f"Error reading backend state: {e}")
            
            response_data = {
                "backend_connected": connected,
                "backend_connection_msg": msg,
                "backend_quorum": quorum,
                "backend_data": backend_state
            }
            
            if connected and quorum:
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