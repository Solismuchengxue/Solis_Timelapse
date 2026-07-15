import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class DockerContractTests(unittest.TestCase):
    def test_compose_uses_confirmed_service_and_host_mounts(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
        service = compose["services"]["solis_timelapse"]
        volumes = service["volumes"]

        self.assertEqual(service["image"], "solis_timelapse")
        self.assertEqual(service["container_name"], "solis_timelapse")
        self.assertEqual(service["user"], "${PUID}:${PGID}")
        self.assertEqual(service["ports"], ["9501:9501"])
        self.assertIn("${INPUT_PATH}:/media/input:ro", volumes)
        self.assertIn("${APP_ROOT}/workspace:/media/workspace", volumes)
        self.assertIn("${APP_ROOT}/output:/media/output", volumes)
        self.assertIn("${APP_ROOT}/archive:/media/archive", volumes)
        self.assertIn("${APP_ROOT}/config:/data/config", volumes)
        self.assertNotIn("privileged", service)
        self.assertNotIn("/var/run/docker.sock", "\n".join(volumes))
        self.assertEqual(service["restart"], "unless-stopped")

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
            "APP_ROOT": "/vol1/1000/solis_timelapse",
            "PUID": "1000",
            "PGID": "1000",
        })

    def test_docker_context_excludes_local_and_growing_data(self):
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        for value in (
            ".git", ".venv", ".superpowers", "tests", "docs",
            "config/local.yaml", "workspace", "output", "archive",
        ):
            self.assertIn(value, ignored)

    def test_entrypoint_has_fail_fast_validation_contract(self):
        entrypoint = (ROOT / "docker" / "entrypoint.py").read_text(encoding="utf-8")

        self.assertIn("validate_runtime_environment", entrypoint)
        self.assertIn("Solis_Timelapse:", entrypoint)
        self.assertIn("return 2", entrypoint)
        self.assertIn('"--host", runtime.host', entrypoint)
        self.assertIn('"--no-browser"', entrypoint)


if __name__ == "__main__":
    unittest.main()
