import subprocess
import random
import socket
DOCKER_BIN = "/usr/bin/docker"
def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))  # OS assigns a free port
    port = s.getsockname()[1]
    s.close()
    return port


def docker_build(build_path: str, image_tag: str):
    code, out, err = run([DOCKER_BIN, "build", "-t", image_tag, "."], cwd=build_path)
    if code != 0:
        raise RuntimeError(f"Docker build failed:\n{err}")
    return out


def docker_run(image_tag: str, host_port: int, root_path: str):
    # container exposes 8000 internally
    code, out, err = run([
    DOCKER_BIN, "run", "-d",
    "-e", f"ROOT_PATH={root_path}",
    "-p", f"{host_port}:8000",
    image_tag
])

    if code != 0:
        raise RuntimeError(f"Docker run failed:\n{err}")
    return out.strip()


def docker_stop(container_id: str):
    run([DOCKER_BIN, "rm", "-f", container_id])
