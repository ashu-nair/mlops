from pathlib import Path
import subprocess

NGINX_CONF_PATH = Path("/etc/nginx/sites-enabled/mlops")


def write_routes(routes: dict):
    """
    routes = {
      "abcd1234": 11001,
      "xyz99999": 11055
    }
    """
    lines = []
    lines.append("server {")
    lines.append("    listen 80;")
    lines.append("    server_name _;")
    lines.append("")
    lines.append("    client_max_body_size 50M;")
    lines.append("")

    # control api itself (optional)
    lines.append("    location /control/ {")
    lines.append("        proxy_pass http://127.0.0.1:8000/;")
    lines.append("        proxy_set_header Host $host;")
    lines.append("        proxy_set_header X-Real-IP $remote_addr;")
    lines.append("    }")
    lines.append("")

    for model_id, port in routes.items():
        lines.append(f"    location /m/{model_id}/ {{")
        lines.append(f"        proxy_pass http://127.0.0.1:{port}/;")
        lines.append("        proxy_set_header Host $host;")
        lines.append("        proxy_set_header X-Real-IP $remote_addr;")
        lines.append("    }")
        lines.append("")

    lines.append("}")
    content = "\n".join(lines) + "\n"

    tmp_path = Path("/tmp/mlops_routes.conf")
    tmp_path.write_text(content)

    subprocess.run(["sudo", "cp", str(tmp_path), str(NGINX_CONF_PATH)], check=True)
    subprocess.run(["sudo", "nginx", "-t"], check=True)
    subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=True)
