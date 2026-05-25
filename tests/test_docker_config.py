from __future__ import annotations

from pathlib import Path


class TestDockerFiles:
    def test_dockerfile_exists(self):
        assert Path("docker/Dockerfile.server").exists()

    def test_docker_compose_exists(self):
        assert Path("docker/docker-compose.yml").exists()

    def test_dockerfile_uses_python_311(self):
        content = Path("docker/Dockerfile.server").read_text()
        assert "python:3.11" in content

    def test_dockerfile_installs_server_extras(self):
        content = Path("docker/Dockerfile.server").read_text()
        assert "[server]" in content

    def test_compose_has_postgres(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "postgres" in content

    def test_compose_has_api_server(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "api-server" in content

    def test_compose_has_healthcheck(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "healthcheck" in content

    def test_compose_default_password_changeme(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "changeme" in content

    def test_compose_port_3001(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "3001" in content

    def test_compose_volume_persistence(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "pgdata" in content
