# Stateful Availability Tracking App

This is a multi-tier Python web application designed to track its availability using an external monitoring system and a persistent volume. It's intended to be deployed to OpenShift/Kubernetes via Kustomize.

## Architecture

The system consists of two separate Kustomize deployments, both including a `ServiceMonitor` for Prometheus integration:

### Backend (`/backend`)
Deployed as a `StatefulSet` with 3 replicas and a 1Gi RWO PVC.
1.  **Web Mode (`APP_MODE=web`)**: Exposes HTTP endpoints.
    *   `/readyz`: Returns HTTP 200 indicating the app is up.
    *   `/healthz`: Returns HTTP 200 if the secondary "writer" container has successfully written a file to the Persistent Volume in the last `2 * WRITE_INTERVAL` seconds.
    *   `/`: Returns a JSON overview indicating whether the StatefulSet has quorum.
    *   `/metrics`: Returns Prometheus metrics for quorum status and healthy member count.
2.  **Writer Mode (`APP_MODE=writer`)**: Periodically creates files.
    *   Writes a random string to a random file on the mounted PVC every `WRITE_INTERVAL` seconds. Keeps the last 30 files.
3.  **Quorum Mode (`APP_MODE=quorum`)**: Monitors cluster state.
    *   Queries the `/healthz` endpoint of all other members of the StatefulSet every `QUORUM_INTERVAL` seconds.

### Frontend (`/frontend`)
Deployed as a `Deployment` with 5 replicas and an `emptyDir` volume.
1.  **Web Mode (`APP_MODE=web`)**: Exposes HTTP endpoints.
    *   `/readyz`: Returns HTTP 200 indicating the app is up.
    *   `/healthz`: Returns HTTP 200 if it can connect to the Backend's `/readyz` endpoint and the background worker reports a healthy internal Kubernetes API.
    *   `/`: Returns a JSON overview indicating the backend connection status, the quorum state, and the internal Kubernetes API health state fetched by the background worker.
    *   `/metrics`: Returns Prometheus metrics tracking connection status, latency, quorum state, and K8s API health.
2.  **Worker Mode (`APP_MODE=worker`)**: Background syncing.
    *   Queries the Backend's `/` endpoint every 5 seconds and dumps the resulting JSON data into the shared `emptyDir`.
    *   Queries the internal Kubernetes API `/healthz` endpoint every 5 seconds to verify control plane health and logs the status.

## Deployment via Kustomize

The applications are separated into two directories with their own Kustomize configurations. The backend includes a `NetworkPolicy` to allow traffic from the frontend namespace.

### Pod Anti-Affinity (Fewer than 3 AZs)

By default, the Backend is configured with a `podAntiAffinity` rule that strictly requires the pods to be scheduled in different Availability Zones (`requiredDuringSchedulingIgnoredDuringExecution`).

If your cluster has fewer than 3 Availability Zones, the remaining backend pods will be stuck in a `Pending` state. You can fix this while still distributing the pods as widely as possible by adding a Kustomization patch. This patch weakens the hard zone requirement to a preference (`preferredDuringSchedulingIgnoredDuringExecution`), and adds an additional preference to spread across different host nodes.

Create a file named `backend/patch-affinity.yaml` with the following content:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: backend-app
spec:
  template:
    spec:
      affinity:
        podAntiAffinity:
          # Remove the strict requirement
          $patch: delete
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: backend-app
            topologyKey: "topology.kubernetes.io/zone"
        podAntiAffinity:
          # Add the weakened preference for zones and nodes
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels:
                  app: backend-app
              topologyKey: "topology.kubernetes.io/zone"
          - weight: 50
            podAffinityTerm:
              labelSelector:
                matchLabels:
                  app: backend-app
              topologyKey: "kubernetes.io/hostname"
```

Then, include this patch in your `backend/kustomization.yaml`:

```yaml
patches:
  - path: patch-affinity.yaml
```

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

### Linting and Formatting

The Python codebase adheres to `ruff` linting and formatting standards. You can check and format the code locally by running:

```bash
ruff check .
ruff format .
```

## License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
