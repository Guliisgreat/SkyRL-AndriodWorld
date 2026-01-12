import os
import base64
import uvicorn
import copy
from pydantic import BaseModel
from typing import Annotated, Optional
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, Body

from .env import AndroidWorldEnv
from .logger_config import get_logger

env_id = int(os.getenv("ENV_ID", "0"))
logger = get_logger('server', f'/data/log/server_logs/env{env_id}.log')

class ResetInput(BaseModel):
    seed: Optional[int] = None
    options: Optional[dict] = None

class StepInput(BaseModel):
    action: dict
    thought: str = "Not provided"

class LogInput(BaseModel):
    log_str: str

def str_to_bool(value):
    return str(value).lower() in ("true", "1", "yes", "y")

def prepare_observation_for_transfer(observation):
    obs_copy = dict(observation)
    img = obs_copy["image"]
    obs_copy["image"] = base64.b64encode(img.tobytes()).decode("utf-8")
    obs_copy["image_shape"] = img.shape
    obs_copy["image_dtype"] = str(img.dtype)
    return obs_copy

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    sample_mode = os.getenv("ENV_SAMPLE_MODE", "random")
    save_images = str_to_bool(os.getenv("ENV_SAVE_IMAGES", "True"))
    env_id = int(os.getenv("ENV_ID", "0"))
    snapshot = os.getenv("ENV_SNAPSHOT", "clean")
    task_family = os.getenv("ENV_TASK_FAMILY", "android")
    emulator_port = os.getenv("EMULATOR_PORT", 5554)
    grpc_port = os.getenv("GRPC_PORT", 8554)

    logger.info("Server is starting...")

    app.state.env = AndroidWorldEnv(
        sample_mode = sample_mode,
        save_images = save_images,
        env_id = env_id,
        snapshot = snapshot,
        task_family = task_family,
        console_port = int(emulator_port),
        grpc_port = int(grpc_port)
    )

    logger.info("Server started.")

    yield
    # Shutdown
    if app.state.env is not None:
        app.state.env.close()


app = FastAPI(lifespan=lifespan)

def get_app_env(request: Request) -> AndroidWorldEnv:
    return request.app.state.env

Env = Annotated[AndroidWorldEnv, Depends(get_app_env)]

@app.post("/reset")
async def reset(env: Env, data: ResetInput):
    seed = data.seed
    options = data.options

    logger.info(f"Server received reset request with seed={seed}, options={options}.")

    observation, info = env.reset(seed=seed, options=options)
    return {
        "status": "success", 
        "observation": prepare_observation_for_transfer(observation),
        "info": info
    }

@app.post("/step")
async def step(env: Env, data: StepInput):
    action = data.action
    thought = data.thought

    logger.info(f"Server received step request with action={action}, thought={thought}.")

    observation, reward, terminated, truncated, info = env.step(action=action, thought=thought)
    return {
        "status": "success", 
        "observation": prepare_observation_for_transfer(observation),
        "reward": reward, 
        "terminated": terminated,
        "truncated": truncated,
        "info": info
    }

@app.post("/env_log")
async def env_log(env: Env, data: LogInput):
    log_str = data.log_str
    env.custom_log(log_str=log_str)
    return {
        "status": "success", 
    }


@app.get("/health")
async def health(env: Env):

    logger.info(f"Server received health request.")

    if isinstance(env, AndroidWorldEnv):
        return {"status": "success"}
    raise HTTPException(status_code=500, detail="Environment not initialized")

@app.get("/get_n_tasks")
async def get_n_tasks(env: Env):

    logger.info(f"Server received get_n_tasks request.")

    n_tasks = len(env.all_tasks)
    
    return {
        "status": "success",
        "n_tasks": n_tasks
    }

if __name__ == "__main__":
    server_port = os.getenv("SERVER_PORT", 5000)
    uvicorn.run(app, host="0.0.0.0", port=int(server_port))
