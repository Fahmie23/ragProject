from __future__ import annotations

import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def test_compose_uses_pinned_pgvector_and_readiness_conditions() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "pgvector/pgvector:0.8.6-pg16-bookworm" in text
    assert "condition: service_healthy" in text
    assert "condition: service_completed_successfully" in text
    assert ":latest" not in text


def test_compose_preserves_filesystem_artifacts_and_model_cache() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./backend/data:/app/data" in text
    assert "rag_hf_cache:/home/rag/.cache/huggingface" in text
    assert "rag_pgdata:/var/lib/postgresql/data" in text


def test_compose_matches_frozen_generation_model_profile() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "GENERATION_MODEL: ${GENERATION_MODEL:-openai/gpt-oss-120b}" in text


def test_backend_image_requires_lock_and_exact_python_image() -> None:
    text = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12.14-slim-bookworm" in text
    assert "COPY requirements.lock.txt" in text
    assert "pip install -r requirements.lock.txt" in text
    assert "USER rag" in text
    assert "FROM python-base AS test" in text
    assert "COPY requirements-dev.lock.txt" in text
    assert 'CMD ["python", "-m", "pytest", "-q"]' in text


def test_frontend_image_uses_exact_node_and_nginx_images() -> None:
    text = (REPO_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:24.19.0-bookworm-slim" in text
    assert "FROM nginx:1.31.4-alpine" in text
    assert "npm ci" in text
    assert ":latest" not in text


def test_frontend_direct_dependencies_are_exact_pins() -> None:
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for version in package[section].values():
            assert version != "latest"
            assert not version.startswith(("^", "~", ">", "<", "*"))
    assert package["engines"]["node"] == "24.19.x"


def test_frontend_api_base_keeps_local_default_but_is_container_configurable() -> None:
    text = (REPO_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    assert 'import.meta.env.VITE_API_BASE ?? "http://localhost:8000"' in text


def test_secret_examples_do_not_contain_real_generation_key() -> None:
    for path in (BACKEND_DIR / ".env.example", REPO_ROOT / "docker.env.example"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("GROQ_API_KEY="):
                assert line == "GROQ_API_KEY="


def test_compose_defines_verify_only_locked_backend_test_service() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["verify"]' in text
    assert "target: test" in text
    assert "working_dir: /workspace/repo/backend" in text
    assert ".:/workspace/repo:ro" in text
    assert 'command: ["python", "-m", "pytest", "-q"]' in text


def test_docker_frontend_proxies_api_same_origin() -> None:
    text = (REPO_ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "location /api/" in text
    assert "proxy_pass http://backend:8000/api/;" in text
    assert "location = /health" in text
