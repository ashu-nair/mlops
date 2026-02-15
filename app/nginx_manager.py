from pathlib import Path
import subprocess

NGINX_SITE_PATH = Path("/etc/nginx/sites-available/mlops")
NGINX_ENABLED_PATH = Path("/etc/nginx/sites-enabled/mlops")
UI_ROOT = Path("/var/www/mlops-ui")


def write_routes(routes: dict):
    """
    routes format:
    {
      "control": "http://127.0.0.1:8000/",
      "models": {
          "54b2e32b": "http://127.0.0.1:42037/",
          "683b2426": "http://127.0.0.1:45217/"
      }
    }
    """

    control_upstream = routes.get("control", "http://127.0.0.1:8000/")
    model_routes = routes.get("models", {})

    # Build nginx config
    conf = f"""
server {{
    listen 80;
    server_name _;

    client_max_body_size 50M;

    # ========= UI (ALWAYS ON) =========
    location / {{
        root {UI_ROOT};
        index index.html;
        try_files $uri $uri/ /index.html;
    }}

    # ========= Control API =========
    location /control/ {{
        proxy_pass {control_upstream};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }}
"""

    # Add model routes
    for model_id, upstream in model_routes.items():
        conf += f"""
    location /m/{model_id}/ {{
        proxy_pass {upstream};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }}
"""

    conf += "\n}\n"

    # Write config
    NGINX_SITE_PATH.write_text(conf)

    # Ensure enabled symlink exists
    if not NGINX_ENABLED_PATH.exists():
        subprocess.run(["sudo", "ln", "-s", str(NGINX_SITE_PATH), str(NGINX_ENABLED_PATH)], check=False)

    # Reload nginx safely
    subprocess.run(["sudo", "nginx", "-t"], check=True)
    subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=True)
