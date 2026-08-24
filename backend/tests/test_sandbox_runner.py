from pathlib import Path
from app.services.sandbox_runner import SandboxRunner


def test_sandbox_runner_execution(tmp_path: Path):
    runner = SandboxRunner()
    code_str = (
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2], [3, 4])\n"
        "plt.savefig('/workspace/chart.png')\n"
        "print('Hello from sandbox')\n"
    )

    result = runner.execute(code_str, workspace_dir=tmp_path)

    assert result["exit_code"] == 0
    assert "Hello from sandbox" in result["stdout"]
    assert len(result["artifacts"]) == 1
    assert (tmp_path / "chart.png").exists()
