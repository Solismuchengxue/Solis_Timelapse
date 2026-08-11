import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class DockerContractTests(unittest.TestCase):
    def test_compose_uses_confirmed_service_and_host_mounts(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
        service = compose["services"]["solis_timelapse"]
        volumes = service["volumes"]

        self.assertEqual(compose["name"], "solis_timelapse")
        self.assertRegex(
            service["image"],
            r"^ghcr\.io/solismuchengxue/solis_timelapse:sha-[0-9a-f]{7,40}$",
        )
        self.assertIn(service["image"], (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertNotIn(":latest", service["image"])
        self.assertEqual(service["pull_policy"], "always")
        self.assertNotIn("build", service)
        self.assertEqual(service["container_name"], "solis_timelapse")
        self.assertIn("${PUID:?", service["user"])
        self.assertIn("${PGID:?", service["user"])
        self.assertEqual(service["ports"], ["9501:9501"])
        self.assertTrue(any(value.startswith("${INPUT_PATH:?") and value.endswith(":/media/input:ro") for value in volumes))
        for directory in ("workspace", "output", "archive", "config"):
            container_path = "/data/config" if directory == "config" else f"/media/{directory}"
            self.assertTrue(any(
                value.startswith("${APP_ROOT:?") and value.endswith(f"/{directory}:{container_path}")
                for value in volumes
            ))
        self.assertNotIn("privileged", service)
        self.assertNotIn("/var/run/docker.sock", "\n".join(volumes))
        self.assertEqual(service["restart"], "unless-stopped")

    def test_deployment_has_no_local_build_compose(self):
        self.assertFalse((ROOT / "compose.build.yaml").exists())

    def test_github_actions_publishes_amd64_image_to_ghcr(self):
        workflow_path = ROOT / ".github" / "workflows" / "docker-publish.yml"
        workflow = workflow_path.read_text(encoding="utf-8")

        self.assertIn("packages: write", workflow)
        self.assertIn("paths:", workflow)
        self.assertIn("registry: ghcr.io", workflow)
        self.assertIn("ghcr.io/solismuchengxue/solis_timelapse", workflow)
        self.assertIn("platforms: linux/amd64", workflow)
        self.assertIn("docker/build-push-action@", workflow)
        self.assertIn("push: true", workflow)
        self.assertNotIn("linux/arm64", workflow)

    def test_dockerfile_is_minimal_and_has_python_healthcheck(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertTrue(dockerfile.startswith("FROM python:3.12-slim\n"))
        self.assertIn("SOLIS_CONTAINER=1", dockerfile)
        self.assertIn("EXPOSE 9501", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("urllib.request", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "docker/entrypoint.py"]', dockerfile)
        self.assertNotIn("curl", dockerfile)
        self.assertNotIn("wget", dockerfile)
        self.assertNotRegex(dockerfile, r"(?m)^USER\s+\d+")

    def test_example_environment_matches_fnos_layout(self):
        values = {}
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value

        self.assertEqual(values, {
            "INPUT_PATH": "/vol1/1000/照片/延时摄影",
            "APP_ROOT": "/vol1/1000/Solis_Timelapse",
            "PUID": "1000",
            "PGID": "1000",
        })

    def test_docker_context_excludes_local_and_growing_data(self):
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        for value in (
            ".git", ".venv", ".superpowers", "tests", "docs",
            "config/local.yaml", "config/auth.json", ".env", "workspace", "output", "archive",
        ):
            self.assertIn(value, ignored)

    def test_fnos_authentication_and_reset_are_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("首次访问会显示“初始化管理员”", readme)
        self.assertIn("mv config/auth.json config/auth.json.bak", readme)
        self.assertIn("Windows 双击 `run.bat` 的本地模式保持原有的免登录行为", readme)
        self.assertIn("`9501` 仍是明文 HTTP", readme)
        self.assertIn("config/auth.json", gitignore)

    def test_entrypoint_has_fail_fast_validation_contract(self):
        entrypoint = (ROOT / "docker" / "entrypoint.py").read_text(encoding="utf-8")

        self.assertIn("validate_runtime_environment", entrypoint)
        self.assertIn("migrate_legacy_container_config", entrypoint)
        self.assertIn('with_name("local.yaml")', entrypoint)
        self.assertIn("Solis_Timelapse:", entrypoint)
        self.assertIn("return 2", entrypoint)
        self.assertIn('"--host", runtime.host', entrypoint)
        self.assertIn('"--no-browser"', entrypoint)


if __name__ == "__main__":
    unittest.main()
