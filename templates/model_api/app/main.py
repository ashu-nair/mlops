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
    return joblib.load(MODEL_PATH)


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


MODEL = load_model()
CONFIG = load_config()

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/predict")
def predict(req: PredictRequest):
    start = time.time()

    data = req.data

    try:
        # data is dict: {"f1":1, "f2":2}
        if isinstance(data, dict):
            if "input_features" in CONFIG:
                feats = CONFIG["input_features"]
                row = [data[f] for f in feats]
            else:
                row = list(data.values())

            X = np.array([row], dtype=float)

        # data is list: [1,2,3]
        elif isinstance(data, list):
            X = np.array([data], dtype=float)

        else:
            raise ValueError("data must be dict or list")

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Input parsing failed: {str(e)}")

    try:
        pred = MODEL.predict(X)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model prediction failed: {str(e)}")

    pred_list = pred.tolist() if hasattr(pred, "tolist") else [pred]

    latency = (time.time() - start) * 1000

    resp = {
        "prediction": pred_list,
        "latency_ms": latency
    }

    # Add labels if available
    if "class_names" in CONFIG:
        try:
            class_names = CONFIG["class_names"]
            labels = [class_names[int(p)] for p in pred_list]
            resp["label"] = labels
        except Exception:
            pass

    return resp

