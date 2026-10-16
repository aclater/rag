"""Guard tests for the deployment's security and resource constraints."""

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
QUADLETS = sorted((DEPLOY / "quadlet").glob("*.in"))
CONTAINERS = [q for q in QUADLETS if q.name.endswith(".container.in")]
MODEL_SERVERS = {"rag-chat.container.in", "rag-embed.container.in", "rag-rerank.container.in"}
FORBIDDEN = ["SecurityLabelDisable", "/dev/kfd", "--privileged", "--ipc=host", "Network=host"]


def test_quadlets_exist() -> None:
    assert (DEPLOY / "quadlet" / "rag.pod.in").exists()
    assert len(CONTAINERS) >= 7


def test_no_forbidden_settings() -> None:
    for q in QUADLETS:
        text = q.read_text()
        for bad in FORBIDDEN:
            assert bad not in text, f"{q.name} contains {bad}"


def test_only_the_pod_publishes_and_only_on_loopback() -> None:
    for q in CONTAINERS:
        assert "PublishPort" not in q.read_text(), f"{q.name} publishes a port"
    pod = (DEPLOY / "quadlet" / "rag.pod.in").read_text()
    ports = re.findall(r"^PublishPort=(.*)$", pod, re.M)
    assert ports == ["127.0.0.1:@UI_PORT@:3000"]


def test_every_container_is_limited_and_hardened() -> None:
    for q in CONTAINERS:
        text = q.read_text()
        assert re.search(r"--cpus=\d", text), f"{q.name} has no CPU limit"
        assert re.search(r"--memory=\d+[gm]", text), f"{q.name} has no memory limit"
        assert "DropCapability=all" in text, f"{q.name} keeps capabilities"
        assert "NoNewPrivileges=true" in text, f"{q.name} allows new privileges"


def test_only_model_servers_get_the_gpu() -> None:
    for q in CONTAINERS:
        has_gpu = "AddDevice=/dev/dri" in q.read_text()
        is_model = q.name in MODEL_SERVERS
        assert has_gpu == is_model, f"{q.name}: GPU access {has_gpu}"


def test_images_pinned_by_digest() -> None:
    env = (DEPLOY / "images.env").read_text()
    images = dict(re.findall(r"^([A-Z_]+_IMAGE)=(\S+)$", env, re.M))
    assert images
    for name, ref in images.items():
        if name == "UBI_PYTHON_IMAGE":
            continue  # build base for this project's own image; pinned at build time
        assert "@sha256:" in ref, f"{name} is not pinned by digest: {ref}"


def test_profiles_define_every_placeholder() -> None:
    placeholders = set()
    for q in QUADLETS:
        placeholders |= set(re.findall(r"@([A-Z_]+)@", q.read_text()))
    provided = {
        "RAMALAMA_IMAGE",
        "LLAMA_STACK_IMAGE",
        "POSTGRES_IMAGE",
        "OPEN_WEBUI_IMAGE",
        "MODELS",
        "RUNTIME",
        "APP_TAG",
    }
    for profile in (DEPLOY / "profiles").glob("*.env"):
        keys = set(re.findall(r"^([A-Z_]+)=", profile.read_text(), re.M))
        missing = placeholders - provided - keys
        assert not missing, f"{profile.name} lacks {sorted(missing)}"
