# Stateful Availability Tracking App

This is a multi-tier Python web application designed to track its availability using an external monitoring system and a persistent volume. It's intended to be deployed to OpenShift/Kubernetes via Kustomize.

## Architecture

The system consists of two separate Kustomize deployments:

### Backend (`/backend`)
Deployed as a `StatefulSet` with 3 replicas and a 1Gi RWO PVC.
1.  **Web Mode (`APP_MODE=web`)**: Exposes HTTP endpoints.
    *   `/readyz`: Returns HTTP 200 indicating the app is up.
    *   `/healthz`: Returns HTTP 200 if the secondary "writer" container has successfully written a file to the Persistent Volume in the last `2 * WRITE_INTERVAL` seconds.
    *   `/`: Returns a JSON overview indicating whether the StatefulSet has quorum.
2.  **Writer Mode (`APP_MODE=writer`)**: Periodically creates files.
    *   Writes a random string to a random file on the mounted PVC every `WRITE_INTERVAL` seconds. Keeps the last 30 files.
3.  **Quorum Mode (`APP_MODE=quorum`)**: Monitors cluster state.
    *   Queries the `/healthz` endpoint of all other members of the StatefulSet every `QUORUM_INTERVAL` seconds.

### Frontend (`/frontend`)
Deployed as a `Deployment` with 5 replicas and an `emptyDir` volume.
1.  **Web Mode (`APP_MODE=web`)**: Exposes HTTP endpoints.
    *   `/readyz`: Returns HTTP 200 indicating the app is up.
    *   `/healthz`: Returns HTTP 200 if it can connect to the Backend's `/readyz` endpoint.
    *   `/`: Returns a JSON overview indicating the backend connection status and the quorum state fetched by the background worker.
2.  **Worker Mode (`APP_MODE=worker`)**: Background syncing.
    *   Queries the Backend's `/` endpoint every 5 seconds and dumps the resulting JSON data into the shared `emptyDir`.

## Deployment via Kustomize

The applications are separated into two directories with their own Kustomize configurations. The backend includes a `NetworkPolicy` to allow traffic from the frontend namespace.

**Deploy Backend:**
```bash
cd backend
oc apply -k .
```

**Deploy Frontend:**
```bash
cd frontend
oc apply -k .
```

## Local Testing

You can verify the application logic locally without deploying to OpenShift using the included `test.sh` script.

```bash
chmod +x test.sh
./test.sh
```

This starts all five modes as background processes, binds to local ports, validates the endpoints with curl, and then cleans up.
