import json
import joblib
import numpy as np
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import time
import os

MODEL_PATH = Path("/model/model.pkl")
CONFIG_PATH = Path("/model/model_config.json")

ROOT_PATH = os.getenv("ROOT_PATH", "")
app = FastAPI(title="Deployed Model API", root_path=ROOT_PATH)



class PredictRequest(BaseModel):
    data: dict


def load_model():
    with open(MODEL_PATH, "rb") as f:
        return joblib.load(MODEL_PATH)


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


MODEL = load_model()
CONFIG = load_config()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/predict")
def predict(req: PredictRequest):
    try:
        features = CONFIG["input_features"]
        X = np.array([[req.data[f] for f in features]])
    except Exception:
        raise HTTPException(status_code=400, detail="Input does not match required features")

    start = time.time()
    pred = MODEL.predict(X)
    latency = (time.time() - start) * 1000

    try:
        pred_out = pred.tolist()
    except Exception:
        pred_out = str(pred)

    return {"prediction": pred_out, "latency_ms": latency}
