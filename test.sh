#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
BACKEND_DATA_DIR="/tmp/test_data_backend_$$"
FRONTEND_DATA_DIR="/tmp/test_data_frontend_$$"
mkdir -p "$BACKEND_DATA_DIR" "$FRONTEND_DATA_DIR"

echo "Starting Backend Web app..."
APP_MODE=web DATA_DIR="$BACKEND_DATA_DIR" PORT=8080 python3 "$DIR/backend/backend-app.py" &
WEB_PID=$!

echo "Starting Backend Writer app..."
APP_MODE=writer DATA_DIR="$BACKEND_DATA_DIR" WRITE_INTERVAL=2 python3 "$DIR/backend/backend-app.py" &
WRITER_PID=$!

echo "Starting Backend Quorum app..."
APP_MODE=quorum DATA_DIR="$BACKEND_DATA_DIR" QUORUM_INTERVAL=2 MEMBER_URLS="localhost:8080" REPLICAS=1 python3 "$DIR/backend/backend-app.py" &
QUORUM_PID=$!

echo "Starting Frontend Web app..."
APP_MODE=web DATA_DIR="$FRONTEND_DATA_DIR" PORT=8081 BACKEND_URL="http://localhost:8080" python3 "$DIR/frontend/frontend-app.py" &
FRONTEND_WEB_PID=$!

echo "Starting Frontend Worker app..."
APP_MODE=worker DATA_DIR="$FRONTEND_DATA_DIR" WORKER_INTERVAL=2 BACKEND_URL="http://localhost:8080" python3 "$DIR/frontend/frontend-app.py" &
FRONTEND_WORKER_PID=$!

cleanup() {
    echo -e "\nCleaning up..."
    kill $WEB_PID $WRITER_PID $QUORUM_PID $FRONTEND_WEB_PID $FRONTEND_WORKER_PID 2>/dev/null || true
    rm -rf "$BACKEND_DATA_DIR" "$FRONTEND_DATA_DIR"
}
trap cleanup EXIT

echo "Waiting for apps to initialize (6s)..."
sleep 6

echo "--- Testing Backend ---"
echo "Testing Backend /readyz..."
curl -s -f http://localhost:8080/readyz
echo -e "\nBackend /readyz OK"

echo "Testing Backend /healthz..."
curl -s -f http://localhost:8080/healthz
echo -e "\nBackend /healthz OK"

echo "Testing Backend /..."
curl -s -f http://localhost:8080/
echo -e "\nBackend / OK"

echo "Testing Backend /metrics..."
curl -s -f http://localhost:8080/metrics
echo -e "\nBackend /metrics OK"

echo "--- Testing Frontend ---"
echo "Testing Frontend /readyz..."
curl -s -f http://localhost:8081/readyz
echo -e "\nFrontend /readyz OK"

echo "Testing Frontend /healthz..."
curl -s -f http://localhost:8081/healthz
echo -e "\nFrontend /healthz OK"

echo "Testing Frontend /..."
curl -s -f http://localhost:8081/
echo -e "\nFrontend / OK"

echo "Testing Frontend /metrics..."
curl -s -f http://localhost:8081/metrics
echo -e "\nFrontend /metrics OK"

echo "All tests passed successfully!"
