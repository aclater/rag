# Deployment

rag runs as one rootless Podman pod defined by quadlets. `deploy/install.sh`
renders the quadlets for a model profile into `~/.config/containers/systemd/`,
creates secrets, pulls the pinned images and starts the pod.

```bash
models/fetch.sh laptop-light      # download and verify the profile's models
deploy/install.sh laptop-light    # render quadlets, create secrets, start
systemctl --user status 'rag-*'   # state of every container
deploy/uninstall.sh               # stop and remove quadlets (keeps data)
deploy/uninstall.sh --purge       # also remove volumes and secrets
```

Requirements: Fedora or RHEL with Podman 5 and systemd user services, a
Vulkan-capable GPU, ~25 GB free disk for the `laptop` profile (less for
`laptop-light`, ~90 GB for `workstation`). `workstation` needs 96 GB+ of
unified memory **and** a raised GTT limit on AMD APUs; `install.sh` refuses a
profile that would leave less than 16 GiB of GPU-mappable memory free, because
a full GTT locks up the whole machine (see
[models.md](models.md#gpu-memory-on-amd-apus-raise-the-gtt-limit-before-workstation)).

Profiles: `laptop-light` (Granite 4.0-H-Micro chat), `laptop` (gpt-oss-20b,
recommended), `laptop-gemma` (Gemma 4 26B-A4B) and `workstation`
(gpt-oss-120b). Switching profile is `deploy/install.sh <profile>`; the index
is unaffected because every profile uses the same embedding model.

## Using it

Open `http://127.0.0.1:3000`; the first account created becomes the admin. The
rag tools arrive as the `rag` MCP tool server (Admin settings > External tools)
and are offered to the model when you enable **rag** in the chat's tools menu
(or as a default tool on the model in Admin settings > Models). Open WebUI
injects the server's instructions (search, then cite ids like
`[mpep:2143#1]`), and its default native function calling runs the tool loop.

To check the chat path without the browser:

```bash
deploy/mcp-check.sh "What rationales for obviousness does the MPEP list from KSR?"
```

It acts as an MCP client against `rag-mcp`, lets the profile's chat model call
the tools, and prints the tool calls, the cited ids (flagging any the tools
never returned) and timings.

## What runs

| Container | Image (pinned in `deploy/images.env`) | Listens (pod loopback) | Limits |
| --- | --- | --- | --- |
| `rag-db` | Red Hat sclorg PostgreSQL 16 on CentOS Stream 10, with pgvector 0.6.2 | 5432 | 2 CPU, 2 GB |
| `rag-chat` | RamaLama llama.cpp (Vulkan) | 8080 | 8 CPU, 8 GB |
| `rag-embed` | same | 8081 | 4 CPU, 2 GB |
| `rag-rerank` | same | 8082 | 4 CPU, 2 GB |
| `rag-stack` | Llama Stack, Red Hat Open Data Hub build (RHOAI 3.4) | 8321 | 2 CPU, 4 GB |
| `rag-mcp` | This project's retrieval tools, built locally on UBI 10 | 8090 (`/mcp`) | 1 CPU, 512 MB |
| `rag-webui` | Open WebUI, with the `rag` MCP tools configured | 3000, **published on host 127.0.0.1:3000** | 2 CPU, 3 GB |

Containers in a pod share one network namespace, so services reach each other
on `127.0.0.1`. Only the pod's single `PublishPort` (the UI, on the host's
loopback) is reachable from outside. Model memory on the GPU is allocated by
the driver and isn't counted against the container memory limits.

## Security choices

- SELinux labelling stays on for every container (llama.cpp reaches the GPU
  through `/dev/dri` with labels on). Only the three model servers get
  `/dev/dri`; nothing gets `/dev/kfd`, `--privileged` or `--ipc=host`.
- All capabilities dropped, `NoNewPrivileges=true`.
- Secrets (`rag-db-password`, `rag-db-admin-password`, `rag-webui-secret`) are
  generated once by `install.sh` into podman's secret store; nothing secret is
  written to the repository or the rendered quadlets. Open WebUI's secret is a
  Fernet key (URL-safe base64 of 32 bytes), as it requires.
- Open WebUI runs with authentication on, offline mode, CORS limited to its
  own origin, and telemetry and analytics off. Its own document features use
  the pod's embedding server, so it downloads no models. The `rag` MCP tool
  server is configured on first boot; afterwards it's managed in Admin
  settings > External tools (grant other users access there).

## Why not RamaLama's generated quadlets as-is

`ramalama serve --generate quadlet` (0.25) produces units that conflict with
this project's constraints: `SecurityLabelDisable=true`, `AddDevice=/dev/kfd`,
`PublishPort=0.0.0.0:…`, and the model mounted as an image volume. The
deployment therefore uses RamaLama's pinned container image and its
`llama-server` invocation, with tightened quadlets.

## Data ownership

Llama Stack owns its tables in the `rag` database: the pgvector store tables
(one per vector store), its registry and state (`llamastack_kvstore`,
`inference_store`, ...). This project's own tables (collections and their
revisions, full document text for `fetch`) live alongside and are created by
this repository's migrations (added with the ingestion work, #9), never by a
service at startup.

## Troubleshooting

- **A unit keeps restarting:** `journalctl --user -u rag-<name> -n 50`.
  `install.sh` resets systemd's restart limit on every run.
- **`rag-mcp` image out of date:** `install.sh` tags it by git revision and
  rebuilds it when the working tree has uncommitted changes.
- **GPU not used:** `podman run --rm --device /dev/dri <RAMALAMA_IMAGE> llama-server --list-devices`
  should list a `Vulkan0` device.
- **Llama Stack can't reach PostgreSQL:** `rag-db` reports ready only when its
  health check passes (`Notify=healthy`), and `rag-stack` waits for it.
