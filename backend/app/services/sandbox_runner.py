import logging
import tempfile
from pathlib import Path

import docker
import docker.errors

from app.core.config import UPLOADS_PATH, SQL_RESULTS_PATH, ARTIFACTS_PATH

logger = logging.getLogger(__name__)


def _snapshot(directory: Path) -> set[Path]:
    """Return the set of all files currently present under *directory*."""
    if not directory.exists():
        return set()
    return {p for p in directory.rglob("*") if p.is_file()}


class SandboxRunner:
    def __init__(self) -> None:
        try:
            self.client = docker.from_env()
        except docker.errors.DockerException as exc:
            logger.error(
                "[SandboxRunner] Cannot connect to Docker daemon — "
                "make sure Docker is running. Detail: %s",
                exc,
            )
            raise

    def execute(self, code_str: str) -> dict:
        # Ensure all bound host directories exist before Docker mounts them.
        UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
        SQL_RESULTS_PATH.mkdir(parents=True, exist_ok=True)
        ARTIFACTS_PATH.mkdir(parents=True, exist_ok=True)

        stdout_str = ""
        stderr_str = ""
        exit_code = 0

        # Snapshot existing output artifacts so we can report only what this run produced.
        before_output = _snapshot(ARTIFACTS_PATH)

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)

            # 1. Write generated code
            script_path = temp_dir / "script.py"
            script_path.write_text(code_str, encoding="utf-8")

            container = None
            try:
                # 2. Spawn Docker container with 15s timeout.
                #    Storage directories are bind-mounted directly, so files
                #    written inside the container appear on the host immediately
                #    with no extra copy step required.
                container = self.client.containers.create(
                    image="data-agent-runner:latest",
                    network_mode="none",
                    mem_limit="512m",
                    nano_cpus=1000000000,
                    volumes={
                        str(temp_dir): {
                            "bind": "/workspace",
                            "mode": "rw",
                        },
                        # Read-only: container only reads uploaded source files.
                        str(UPLOADS_PATH): {
                            "bind": "/workspace/input",
                            "mode": "ro",
                        },
                        # Read-write: container writes query results (parquet, csv…).
                        str(SQL_RESULTS_PATH): {
                            "bind": "/workspace/intermediate",
                            "mode": "rw",
                        },
                        # Read-write: container writes output artifacts (charts, reports…).
                        str(ARTIFACTS_PATH): {
                            "bind": "/workspace/output",
                            "mode": "rw",
                        },
                    },
                    detach=True,
                )

                container.start()
                res = container.wait(timeout=15)
                exit_code = res.get("StatusCode", 0)

                stdout_str = container.logs(stdout=True, stderr=False).decode("utf-8")
                stderr_str = container.logs(stdout=False, stderr=True).decode("utf-8")

            except docker.errors.DockerException as e:
                logger.error(
                    "[SandboxRunner] Docker error during container execution — "
                    "is Docker running? Detail: %s",
                    e,
                )
                stderr_str = str(e)
                exit_code = 1
                if container:
                    try:
                        container.kill()
                    except Exception:
                        pass
            except Exception as e:
                if "timed out" in str(e).lower():
                    logger.warning(
                        "[SandboxRunner] Container execution timed out: %s", e
                    )
                    exit_code = 124
                else:
                    logger.error(
                        "[SandboxRunner] Unexpected error during container execution: %s",
                        e,
                    )
                    exit_code = 1
                stderr_str = str(e)
                if container:
                    try:
                        container.kill()
                    except Exception:
                        pass
            finally:
                if container:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass

        # 3. Collect Python-produced artifact paths only (new files under ARTIFACTS_PATH).
        #    SQL result files written to SQL_RESULTS_PATH are intentionally excluded.
        new_output = _snapshot(ARTIFACTS_PATH) - before_output
        artifacts = [str(p) for p in sorted(new_output)]

        return {
            "stdout": stdout_str,
            "stderr": stderr_str,
            "exit_code": exit_code,
            "artifacts": artifacts,
        }
