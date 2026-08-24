import shutil
import tempfile
from pathlib import Path
import docker


class SandboxRunner:
    def __init__(self) -> None:
        self.client = docker.from_env()

    def execute(self, code_str: str, workspace_dir: Path | str | None = None) -> dict:
        if workspace_dir is None:
            workspace_dir = Path(".")
        elif isinstance(workspace_dir, str):
            workspace_dir = Path(workspace_dir)

        workspace_dir.mkdir(parents=True, exist_ok=True)

        stdout_str = ""
        stderr_str = ""
        exit_code = 0
        artifacts = []

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)

            # 1. Write generated code
            script_path = temp_dir / "script.py"
            script_path.write_text(code_str, encoding="utf-8")

            container = None
            try:
                # 2. Spawn Docker container with 15s timeout
                container = self.client.containers.create(
                    image="data-agent-runner:latest",
                    network_mode="none",
                    mem_limit="512m",
                    nano_cpus=1000000000,
                    volumes={
                        str(temp_dir): {
                            "bind": "/workspace",
                            "mode": "rw",
                        }
                    },
                    detach=True,
                )

                container.start()
                res = container.wait(timeout=15)
                exit_code = res.get("StatusCode", 0)

                stdout_str = container.logs(stdout=True, stderr=False).decode("utf-8")
                stderr_str = container.logs(stdout=False, stderr=True).decode("utf-8")

            except Exception as e:
                stderr_str = str(e)
                exit_code = 124 if "timed out" in str(e).lower() else 1
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

            # 3. Copy generated artifact files to server current session directory
            for item in temp_dir.iterdir():
                if item.name != "script.py":
                    dest = workspace_dir / item.name
                    if item.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(item, dest)
                    else:
                        shutil.copy2(item, dest)
                    artifacts.append(str(dest))

        return {
            "stdout": stdout_str,
            "stderr": stderr_str,
            "exit_code": exit_code,
            "artifacts": artifacts,
        }
