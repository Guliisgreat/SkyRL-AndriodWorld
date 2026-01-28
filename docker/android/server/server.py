import os
import base64
import time
import uvicorn
import copy
import asyncio
import numpy as np
from pydantic import BaseModel
from typing import Annotated, Optional
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, Body

from .env import AndroidWorldEnv
from .logger_config import get_logger

env_id = int(os.getenv("ENV_ID", "0"))
logger = get_logger('server', f'/data/log/server_logs/env{env_id}.log')

# Container readiness state - tracks if emulator is truly ready for work
class ContainerState:
    def __init__(self):
        self.ready = False  # Set True after emulator verified working
        self.last_success_time = 0  # Track last successful operation
        self.consecutive_failures = 0  # Track failures to detect degradation
        self.startup_verified = False  # Set True after initial verification
    
    def mark_success(self):
        """Mark a successful operation."""
        self.ready = True
        self.last_success_time = time.time()
        self.consecutive_failures = 0
    
    def mark_failure(self):
        """Mark a failed operation."""
        self.consecutive_failures += 1
        # After 3 consecutive failures, mark as not ready
        if self.consecutive_failures >= 3:
            self.ready = False
    
    def is_healthy(self) -> bool:
        """Check if container is healthy and ready."""
        if not self.startup_verified:
            return False
        if self.consecutive_failures >= 3:
            return False
        return self.ready

container_state = ContainerState()

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

    logger.info("Server started, verifying emulator responsiveness...")
    
    # Verify emulator is truly ready by getting a screenshot
    try:
        for attempt in range(3):
            try:
                observation, info = app.state.env.get_raw_observation()
                if observation is not None and np.sum(observation) > 0:
                    container_state.startup_verified = True
                    container_state.ready = True
                    logger.info(f"Emulator verified ready after {attempt + 1} attempt(s)")
                    break
            except Exception as e:
                logger.warning(f"Startup verification attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(5)
        
        if not container_state.startup_verified:
            logger.error("Failed to verify emulator after 3 attempts, marking as not ready")
    except Exception as e:
        logger.error(f"Startup verification failed: {e}")

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

    try:
        observation, info = env.reset(seed=seed, options=options)
        container_state.mark_success()  # Track successful operation
        return {
            "status": "success", 
            "observation": prepare_observation_for_transfer(observation),
            "info": info
        }
    except Exception as e:
        container_state.mark_failure()  # Track failure
        logger.error(f"Reset failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/step")
async def step(env: Env, data: StepInput):
    action = data.action
    thought = data.thought

    logger.info(f"Server received step request with action={action}, thought={thought}.")

    try:
        observation, reward, terminated, truncated, info = env.step(action=action, thought=thought)
        container_state.mark_success()  # Track successful operation
        return {
            "status": "success", 
            "observation": prepare_observation_for_transfer(observation),
            "reward": reward, 
            "terminated": terminated,
            "truncated": truncated,
            "info": info
        }
    except Exception as e:
        container_state.mark_failure()  # Track failure
        logger.error(f"Step failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/env_log")
async def env_log(env: Env, data: LogInput):
    log_str = data.log_str
    env.custom_log(log_str=log_str)
    return {
        "status": "success", 
    }


@app.get("/health")
async def health(env: Env):
    """
    Smart health check that returns actual readiness state.
    
    Returns:
        - status: "healthy" if ready for work, "degraded" if issues, "unhealthy" if down
        - ready: boolean indicating if container can accept work
        - consecutive_failures: number of recent failures
    """
    logger.info(f"Server received health request.")

    if not isinstance(env, AndroidWorldEnv):
        return {"status": "unhealthy", "ready": False, "reason": "env_not_initialized"}
    
    if not container_state.startup_verified:
        return {"status": "unhealthy", "ready": False, "reason": "startup_not_verified"}
    
    if container_state.consecutive_failures >= 3:
        return {
            "status": "degraded", 
            "ready": False, 
            "reason": "consecutive_failures",
            "consecutive_failures": container_state.consecutive_failures
        }
    
    return {
        "status": "healthy", 
        "ready": container_state.ready,
        "consecutive_failures": container_state.consecutive_failures,
        "last_success": container_state.last_success_time
    }


@app.get("/deep_health")
async def deep_health(env: Env):
    """
    Deep health check - actually tests if emulator is responsive.
    Returns degraded status if emulator is frozen or unresponsive.
    """
    logger.info("Server received deep_health request.")
    
    try:
        # Try to get a screenshot - this tests the full stack
        start = time.time()
        observation, info = env.get_raw_observation()
        elapsed = time.time() - start
        
        # Check if we got a valid image (not zeros)
        if observation is None or np.sum(observation) == 0:
            return {
                "status": "degraded", 
                "reason": "blank_screen", 
                "response_time": elapsed
            }
        
        # Check if response time is acceptable (30s is very slow)
        if elapsed > 30.0:
            return {
                "status": "degraded", 
                "reason": "slow_response", 
                "response_time": elapsed
            }
        
        return {"status": "healthy", "response_time": elapsed}
        
    except Exception as e:
        logger.error(f"Deep health check failed: {e}")
        return {"status": "unhealthy", "reason": str(e)}


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
