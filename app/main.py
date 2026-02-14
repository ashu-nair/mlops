import uuid
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException

from app.db import init_db, get_conn
from app.docker_runner import docker_build, docker_run, docker_stop, get_free_port
from app.nginx_manager import write_routes

STORAGE_DIR = Path("storage")
DEPLOYMENTS_DIR = Path("deployments")
TEMPLATE_DIR = Path("templates/model_api")

STORAGE_DIR.mkdir(exist_ok=True)
DEPLOYMENTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="MLOps Auto Deploy - Control API", version="1.0")


@app.on_event("startup")
def startup():
    init_db()


def get_active_routes():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT model_id, internal_port
    FROM versions
    WHERE status='RUNNING'
    """)
    rows = cur.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def refresh_nginx():
    routes = get_active_routes()
    write_routes(routes)


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload must be a ZIP file.")

    model_id = str(uuid.uuid4())[:8]
    model_dir = STORAGE_DIR / model_id
    model_dir.mkdir(parents=True, exist_ok=True)

    zip_path = model_dir / "upload.zip"
    with open(zip_path, "wb") as f:
        f.write(await file.read())

    # Extract
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(model_dir)

    # Find required files
    model_pkl = None
    config_json = None
    for p in model_dir.rglob("*"):
        if p.name == "model.pkl":
            model_pkl = p
        if p.name == "model_config.json":
            config_json = p

    if not model_pkl or not config_json:
        shutil.rmtree(model_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="ZIP must contain model.pkl and model_config.json")

    # Register model in DB
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO models(model_id, created_at, active_version)
    VALUES (?, ?, ?)
    """, (model_id, datetime.utcnow().isoformat(), 1))

    conn.commit()
    conn.close()

    return {"model_id": model_id, "message": "Uploaded successfully. Now deploy it."}


@app.post("/deploy/{model_id}")
def deploy(model_id: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT active_version FROM models WHERE model_id=?", (model_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Model not found")

    active_version = row[0]
    new_version = active_version + 1 if active_version else 1

    # prepare deployment folder
    deployment_folder = DEPLOYMENTS_DIR / f"{model_id}_v{new_version}"
    if deployment_folder.exists():
        shutil.rmtree(deployment_folder)
    shutil.copytree(TEMPLATE_DIR, deployment_folder)

    # copy model artifacts into deployment_folder/model/
    (deployment_folder / "model").mkdir(exist_ok=True)

    storage_model_dir = STORAGE_DIR / model_id
    model_pkl = next(storage_model_dir.rglob("model.pkl"))
    config_json = next(storage_model_dir.rglob("model_config.json"))

    shutil.copy(model_pkl, deployment_folder / "model/model.pkl")
    shutil.copy(config_json, deployment_folder / "model/model_config.json")

    image_tag = f"mlops-{model_id}:v{new_version}"

    # build docker image
    try:
        docker_build(str(deployment_folder), image_tag)
    except Exception as e:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO versions(model_id, version, status, folder_path, image_tag, container_id, internal_port, created_at, error_log)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (model_id, new_version, "FAILED", str(deployment_folder), image_tag, "", 0, datetime.utcnow().isoformat(), str(e)))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Build failed: {str(e)}")

    # run container on a free port
    port = get_free_port()
    try:
        container_id = docker_run(image_tag, port, f"/m/{model_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Run failed: {str(e)}")

    # test model endpoint
        # test model endpoint (retry because container may take time to start)
    url = f"http://127.0.0.1:{port}/health"
    ok = False
    last_err = ""

    for _ in range(15):  # ~15 seconds
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                ok = True
                break
        except Exception as e:
            last_err = str(e)

        import time
        time.sleep(1)

    if not ok:
        docker_stop(container_id)
        raise HTTPException(status_code=500, detail=f"Container test failed: {last_err}")


    # stop previous running version (rollback-friendly)
    cur.execute("""
    SELECT container_id FROM versions
    WHERE model_id=? AND status='RUNNING'
    """, (model_id,))
    prev = cur.fetchone()
    if prev and prev[0]:
        docker_stop(prev[0])

    # update DB: mark new version running
    cur.execute("""
    UPDATE models SET active_version=? WHERE model_id=?
    """, (new_version, model_id))

    cur.execute("""
    UPDATE versions SET status='STOPPED'
    WHERE model_id=? AND status='RUNNING'
    """, (model_id,))

    cur.execute("""
    INSERT INTO versions(model_id, version, status, folder_path, image_tag, container_id, internal_port, created_at, error_log)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (model_id, new_version, "RUNNING", str(deployment_folder), image_tag, container_id, port, datetime.utcnow().isoformat(), ""))

    conn.commit()
    conn.close()

    refresh_nginx()

    return {
        "model_id": model_id,
        "active_version": new_version,
        "endpoint_predict": f"/m/{model_id}/predict",
        "endpoint_docs": f"/m/{model_id}/docs"
    }


@app.post("/rollback/{model_id}/{version}")
def rollback(model_id: str, version: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT image_tag FROM versions
    WHERE model_id=? AND version=? AND status IN ('RUNNING','STOPPED')
    """, (model_id, version))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Requested version not found")

    image_tag = row[0]

    # stop current
    cur.execute("""
    SELECT container_id FROM versions
    WHERE model_id=? AND status='RUNNING'
    """, (model_id,))
    current = cur.fetchone()
    if current and current[0]:
        docker_stop(current[0])

    # run selected version
    port = get_free_port()
    container_id = docker_run(image_tag, port, f"/m/{model_id}")

    # mark DB
    cur.execute("""
    UPDATE versions SET status='STOPPED'
    WHERE model_id=? AND status='RUNNING'
    """, (model_id,))

    cur.execute("""
    UPDATE versions SET status='RUNNING', container_id=?, internal_port=?
    WHERE model_id=? AND version=?
    """, (container_id, port, model_id, version))

    cur.execute("""
    UPDATE models SET active_version=? WHERE model_id=?
    """, (version, model_id))

    conn.commit()
    conn.close()

    refresh_nginx()

    return {
        "model_id": model_id,
        "active_version": version,
        "endpoint_predict": f"/m/{model_id}/predict"
    }
