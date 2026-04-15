import gymnasium as gym
from gymnasium import spaces
import numpy as np
import os
import random
import time
import subprocess
from typing import List, Dict, Any, Tuple, Optional, Union, Callable
from termcolor import colored, cprint
from PIL import Image
import grp
import pwd
import json
import threading
from google.protobuf import json_format

from android_world.env import env_launcher, json_action, adb_utils
from android_world import suite_utils

from .logger_config import get_logger
from .patches import apply_all as _apply_patches
from .registry_ext import TaskRegistry as _TaskRegistry

# Apply runtime monkey-patches (ADB port override, screenshot skip)
_apply_patches()

SKIP_SCREENSHOT = os.getenv("ENV_SKIP_SCREENSHOT", "false").lower() in ("true", "1", "yes")


# Global flag to track if KVM check has been performed
_KVM_CHECK_PERFORMED = threading.Event()

class AndroidWorldEnv(gym.Env):
    """
    Gymnasium-compatible Android World environment.

    This environment provides a standard interface for interacting with the Android emulator.

    Attributes:
        metadata (dict): Environment metadata including render modes and FPS.
        action_space (spaces.Dict): The action space for the environment.
        observation_space (spaces.Dict): The observation space for the environment.
        env_id (int): Unique identifier for this environment instance.
    """

    metadata = {"render_modes": ["rgb_array"], "render_fps": 4}

    def __init__(
        self,
        emulator_path: str = '~/.android/emulator/emulator',
        avd_name: str = os.getenv("AVD_NAME", "AWAvd"),
        console_port: int = 5554,
        grpc_port: int = 8554,
        no_window: bool = True,
        adb_path: str = '~/.android/platform-tools/adb', 
        emulator_setup: bool = False,
        sample_mode: str = "random",
        n_task_combinations: int = 1,
        seed: Optional[int] = None,
        temp_path: str = '/data/images',
        save_images: bool = False,
        render_mode: str = "rgb_array",
        env_id: int = 0,
        snapshot: str = "clean",
        task_family: str = "android",
    ):
        """
        Initialize the Android World environment.

        Args:
            emulator_path: Path to the Android emulator executable.
            avd_name: Name of the Android Virtual Device to use.
            console_port: Port for the emulator console.
            grpc_port: Port for the gRPC server.
            no_window: Whether to run the emulator without a window.
            adb_path: Path to the Android Debug Bridge executable.
            emulator_setup: Whether to set up the emulator (unused).
            sample_mode: Mode for sampling tasks ("random" or "sequential").
            n_task_combinations: Number of task combinations (unused).
            seed: Random seed for reproducibility.
            temp_path: Base path for temporary files.
            save_images: Whether to save screenshots.
            render_mode: Render mode for the environment.
            env_id: Unique identifier for this environment instance.
            snapshot: Snapshot to use for the emulator.
            task_family: The task set for android world.
        """
        super().__init__()

        # Store environment ID for vectorization
        self.env_id = env_id

        # Create logger
        self.task_logger = None
        self.env_logger = get_logger('env', f'/data/log/server_logs/env{self.env_id}.log')

        # Expand paths
        self.emulator_path = os.path.expanduser(emulator_path)
        self.adb_path = os.path.expanduser(adb_path)
        self.adb_server_port = int(os.getenv("ADB_SERVER_PORT", "5037"))
        os.environ["ANDROID_ADB_SERVER_PORT"] = str(self.adb_server_port)
        self.temp_path = temp_path

        # Create temp directory if it doesn't exist
        if not os.path.exists(self.temp_path):
            os.makedirs(self.temp_path)

        # Check KVM access before initializing the environment components
        # Only perform KVM check once across all environment instances
        if not _KVM_CHECK_PERFORMED.is_set():
            self._check_and_fix_kvm_access()
            _KVM_CHECK_PERFORMED.set()

        # Initialize the task registry
        self.task_family = task_family
        self._initialize_task_registry()

        # Store configuration
        self.avd_name = avd_name
        self.console_port = console_port
        self.grpc_port = grpc_port
        self.no_window = no_window
        self.sample_mode = sample_mode
        self.save_images = save_images
        self.skip_screenshot = SKIP_SCREENSHOT
        self.emulator_setup = emulator_setup
        self.snapshot = snapshot
        self.render_mode = render_mode
        self.image_folder = None

        # Start emulator
        self._start_emulator()

        # Initialize other variables
        self.image_id = str(time.time())
        self.steps = 0
        self.start = None
        self.max_steps = 0
        self.terminated = False
        self.truncated = False
        self.current_observation = None
        self.env_history = []

        # Define action and observation spaces
        self._define_spaces()

    def _initialize_task_registry(self):
        """Initialize the task registry and load available tasks."""
        task_registry = _TaskRegistry()
        android_world_registry = task_registry.get_registry(
            family=self.task_family
        )
        self.all_tasks = list(android_world_registry.items())
        self.env_logger.info(f"Number of tasks available: {len(self.all_tasks)}")

    def _start_emulator(self):
        """Start the Android emulator."""
        self.env_logger.info(f"Starting Emulator {self.avd_name} (ID: {self.env_id}) on port {self.console_port}")
        
        # Build the emulator command
        command = f"{self.emulator_path} -avd {self.avd_name} -snapshot {self.snapshot} -no-audio -skip-adb-auth -no-boot-anim -gpu off -no-snapshot-save -read-only -port {self.console_port} -grpc {self.grpc_port}"
        if self.no_window:
            command += " -no-window"
        
        self.emulator_process = subprocess.Popen(
            command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.env_logger.info(f"Executing command: {command}")

        self.terminated = False
        self.truncated = False
        time.sleep(30)  # Wait for emulator to start

        # Construct android world environment
        self.env = env_launcher.load_and_setup_env(
            console_port=self.console_port,
            emulator_setup=self.emulator_setup,
            adb_path=self.adb_path,
            grpc_port=self.grpc_port)
        self.screen_size = self.env.logical_screen_size
        self.orientation = self.env.orientation
        self.physical_frame_boundary = self.env.physical_frame_boundary
        adb_utils.set_root_if_needed(env=self.env.controller)
        self.env_logger.info(
            f"Emulator {self.env_id} setup completed: console_port {self.console_port} grpc_port {self.grpc_port}"
        )
        

    def _define_spaces(self):
        """Define the action and observation spaces for the environment."""
        # Define action space
        self.action_space = spaces.Dict(
            {
                "action_type": spaces.Discrete(14),  # click, scroll, type, navigate_back, navigate_home, keyboard_enter, status 
                                                    # double_tap, long_press, open_app, swipe, unknown, wait, answer
                "touch_point": spaces.Box(low=0, high=1, shape=(2,), dtype=np.float32),
                "direction": spaces.Discrete(5),  # None, up, down, left, right
                "text": spaces.Text(max_length=100),
                "goal_status": spaces.Discrete(3),  # None, complete, infeasible
                "index": spaces.Discrete(1000),
                "app_name": spaces.Text(max_length=50),
                "keycode": spaces.Text(max_length=10),
            }
        )

        # Define observation space - we'll initialize with default values and update after connecting to the emulator
        self.screen_height, self.screen_width = 1920, 1080  # Default values, will be updated after connecting
        self.observation_space = spaces.Dict(
            {
                "image": spaces.Box(
                    low=0,
                    high=255,
                    shape=(self.screen_height, self.screen_width, 3),
                    dtype=np.uint8,
                ),
                "task": spaces.Text(max_length=1000),
            }
        )
        
    def _update_spaces(self):
        """Update the observation space with the actual screen dimensions."""
        if hasattr(self, 'env') and hasattr(self.env, 'logical_screen_size'):
            self.screen_height, self.screen_width = self.env.logical_screen_size[1], self.env.logical_screen_size[0]
            self.observation_space = spaces.Dict(
                {
                    "image": spaces.Box(
                        low=0,
                        high=255,
                        shape=(self.screen_height, self.screen_width, 3),
                        dtype=np.uint8,
                    ),
                    "task": spaces.Text(max_length=1000),
                }
            )

    def count_white_pixels(self, img):
        """
        Count white pixels to detect blank screens.
        
        Args:
            img: PIL Image object
            
        Returns:
            bool: True if the image is mostly white, False otherwise
        """
        img = img.convert("RGB")
        data = np.array(img)
        white_count = np.sum(np.all(data > 240, axis=-1))
        return white_count > 2_300_000
    
    def _bounding_box_to_dict(self, bbox):
        """Convert Android World UI-Element bounding box to json format."""
        return {
            "x_min": bbox.x_min,
            "x_max": bbox.x_max,
            "y_min": bbox.y_min,
            "y_max": bbox.y_max
        }

    def _ui_element_to_dict(self, ui_element):
        """Convert UI-Element to json format."""
        data = vars(ui_element).copy()
        if "bbox_pixels" in data and data["bbox_pixels"] is not None:
            data["bbox_pixels"] = self._bounding_box_to_dict(data["bbox_pixels"])
        return data
    
    def _get_raw_observation_no_screenshot(self):
        """Fast observation path: skip white-screen loop and image capture, return only a11y tree."""
        _error_obs = lambda: (
            np.zeros((self.screen_height, self.screen_width, 3), dtype=np.uint8),
            {"task": "Error getting observation", "env_id": self.env_id},
        )
        for attempt in range(3):
            try:
                state = self.env.get_state(wait_to_stabilize=True)
                task = getattr(self, "task", None)
                info = {
                    "task": task.goal if task else "",
                    "env_id": self.env_id,
                    "max_steps": self.max_steps,
                    "task_name": task.name if task else "",
                }
                try:
                    info["ui_elements"] = [
                        self._ui_element_to_dict(el) for el in state.ui_elements
                    ]
                except Exception:
                    info["ui_elements"] = []

                if self.save_images and self.image_folder:
                    ui_element_path = os.path.join(
                        self.image_folder, f"{self.image_id}_{self.steps}_ui_element.json"
                    )
                    with open(ui_element_path, "w", encoding="utf-8") as file:
                        json.dump(info["ui_elements"], file, ensure_ascii=False, indent=4)
                    try:
                        ally_tree_path = os.path.join(
                            self.image_folder, f"{self.image_id}_{self.steps}_ally_tree.json"
                        )
                        json_data = json_format.MessageToDict(state.forest, preserving_proto_field_name=True)
                        with open(ally_tree_path, "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=4)
                    except Exception:
                        ally_tree_path = os.path.join(
                            self.image_folder, f"{self.image_id}_{self.steps}_ally_tree.txt"
                        )
                        with open(ally_tree_path, "w", encoding="utf-8") as file:
                            file.write(str(state.forest))

                info["image_path"] = None
                dummy_image = np.zeros((self.screen_height, self.screen_width, 3), dtype=np.uint8)
                return dummy_image, info
            except Exception as e:
                self.env_logger.error(f"Exception in get_raw_observation (no-screenshot) env {self.env_id}")
                self.env_logger.error(e)
                import traceback
                self.env_logger.error(traceback.format_exc())
                time.sleep(3)
                if not self._check_emulator_running():
                    if not self._restart_emulator():
                        self.env_logger.info(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
                        if self.task_logger:
                            self.task_logger.info(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
                        return _error_obs()
                    if not self._restore_env():
                        self.env_logger.info(f"Failed to restore emulator {self.avd_name} (ID: {self.env_id})")
                        if self.task_logger:
                            self.task_logger.info(f"Failed to restore emulator {self.avd_name} (ID: {self.env_id})")
                        return _error_obs()
                self.env = env_launcher.load_and_setup_env(
                    console_port=self.console_port,
                    adb_path=self.adb_path,
                    grpc_port=self.grpc_port)
                time.sleep(10)
                continue
        return _error_obs()

    def get_raw_observation(self):
        """
        Get the raw observation from the environment.
        
        Returns:
            tuple: (observation, info) where observation is the screen image and info is a dictionary with metadata
        """
        if self.skip_screenshot:
            return self._get_raw_observation_no_screenshot()

        for attempt in range(3):
            try:
                # Reference uses get_state(wait_to_stabilize=True) directly
                # with no extra sleep. The stabilization loop inside get_state
                # already waits for the UI to settle.
                state = self.env.get_state(wait_to_stabilize=True)
                nparray_image = state.pixels.copy()
                image = Image.fromarray(nparray_image)

                task = getattr(self, "task", None)
                info = {
                    "task": task.goal if task else "",
                    "env_id": self.env_id,
                    "max_steps": self.max_steps,
                    "task_name": task.name if task else "",
                }

                try:
                    info["ui_elements"] = [
                        self._ui_element_to_dict(el) for el in state.ui_elements
                    ]
                except Exception:
                    info["ui_elements"] = []
                
                if self.save_images and self.image_folder:
                    ui_element_path = os.path.join(
                        self.image_folder, f"{self.image_id}_{self.steps}_ui_element.json"
                    )
                    with open(ui_element_path, "w", encoding="utf-8") as file:
                        json.dump(info["ui_elements"], file, ensure_ascii=False, indent=4)
                    
                    try:
                        ally_tree_path = os.path.join(
                            self.image_folder, f"{self.image_id}_{self.steps}_ally_tree.json"
                        )
                        json_data = json_format.MessageToDict(state.forest, preserving_proto_field_name=True)
                        with open(ally_tree_path, "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=4)
                    except Exception as e:
                        ally_tree_path = os.path.join(
                            self.image_folder, f"{self.image_id}_{self.steps}_ally_tree.txt"
                        )
                        with open(ally_tree_path, "w", encoding="utf-8") as file:
                            file.write(str(state.forest))

                    image_path = os.path.join(
                        self.image_folder, f"{self.image_id}_{self.steps}.png"
                    )
                    image.save(image_path)
                    info["image_path"] = image_path
                else:
                    info["image_path"] = None

                return nparray_image, info
            except Exception as e:
                self.env_logger.error(f"Exception happened during screenshotting in env {self.env_id}")
                self.env_logger.error(e)
                import traceback
                self.env_logger.error(traceback.format_exc())
                time.sleep(3)
                if not self._check_emulator_running():
                    if not self._restart_emulator():
                        self.env_logger.info(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
                        self.task_logger.info(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
                        return np.zeros((self.screen_height, self.screen_width, 3), dtype=np.uint8), {
                            "task": "Error getting observation",
                            "env_id": self.env_id,
                        }
                    if not self._restore_env():
                        self.env_logger.info(f"Failed to restore emulator {self.avd_name} (ID: {self.env_id})")
                        self.task_logger.info(f"Failed to restore emulator {self.avd_name} (ID: {self.env_id})")
                        return np.zeros((self.screen_height, self.screen_width, 3), dtype=np.uint8), {
                            "task": "Error getting observation",
                            "env_id": self.env_id,
                        }
                self.env = env_launcher.load_and_setup_env(
                    console_port=self.console_port,
                    adb_path=self.adb_path,
                    grpc_port=self.grpc_port)
                time.sleep(10)
                continue

        # If we get here, something went wrong
        return np.zeros((self.screen_height, self.screen_width, 3), dtype=np.uint8), {
            "task": "Error getting observation",
            "env_id": self.env_id,
        }

    def reset(self, *, seed=None, options=None):
        """
        Reset the environment to a new state.
        
        Args:
            seed: Random seed for reproducibility
            options: Additional options for reset
            
        Returns:
            tuple: (observation, info) where observation is the initial state and info is a dictionary with metadata
        """
        super().reset(seed=seed)

        # Clear env history
        self.env_history = []
        
        # Check if the emulator is running and restart it if needed
        if not self._check_emulator_running():
            self.env_logger.warning(f"Emulator {self.avd_name} (ID: {self.env_id}) is not running, attempting to restart...")
            if not self._restart_emulator():
                self.env_logger.warning(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
                raise RuntimeError(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
        
        # Clean up previous task if it exists
        if hasattr(self, "task"):
            if self.task.initialized:
                self.task.tear_down(self.env)
            del self.task

        # Process options
        go_home_on_reset = True
        task_id = 0
        epoch = 0
        mode = "train"
        traj = 0
        total_traj = 1
        if options is not None:
            go_home_on_reset = options.get("go_home_on_reset", True)
            task_id = options.get("task_id", 0)
            epoch = options.get("epoch", epoch)
            mode = options.get("mode", mode)
            traj = options.get("traj", traj)
            total_traj = options.get("total_traj", total_traj)
        
        if total_traj == 1:
            self.image_folder = f'/data/log/{mode}/epoch{epoch}/task{task_id}'
            os.makedirs(self.image_folder, exist_ok=True)
        else:
            self.image_folder = f'/data/log/{mode}/epoch{epoch}/task{task_id}/traj{traj}'
            os.makedirs(self.image_folder, exist_ok=True)
        self.task_logger = get_logger(f"env{self.env_id}", f'{self.image_folder}/log.log')

        # Reset the environment
        self.env.reset(go_home=go_home_on_reset)
        self.env.hide_automation_ui()
        self.steps = 0
        self.terminated = False
        self.truncated = False
        self.image_id = str(time.time())

        # Select and initialize task
        self._select_and_initialize_task(seed, task_id)

        # Store env history (for restoration)
        self.env_history.append({
            'action': '_select_and_initialize_task',
            'parameter': {
                'seed': seed,
                'task_id': task_id
            }
        })

        # Get observation
        observation, info = self.get_raw_observation()
        self.current_observation = {
            "image": observation,
            "task": info["task"],
            "ui_elements": info.get("ui_elements", []),
        }

        return self.current_observation, info

    def _select_and_initialize_task(self, seed, task_id):
        """
        Select and initialize a task for the environment.
        
        Args:
            seed: Random seed for reproducibility
            task_id: Task ID for sequential sampling
        """
        # Select task
        if self.sample_mode == "random":
            name, task_type = random.choice(self.all_tasks)
            # name, task_type = self.all_tasks[0]
        elif self.sample_mode == "sequential":
            name, task_type = self.all_tasks[(task_id) % len(self.all_tasks)]
        else:
            self.env_logger.warning(f"Invalid sample mode in env {self.env_id}, defaulting to first task")
            name, task_type = self.all_tasks[0]
            
        self.task = suite_utils._instantiate_task(task_type, seed=seed, env=None)

        msg = f"Env {self.env_id} running task: {name}"
        self.env_logger.info(msg + "\n" + "=" * len(msg))
        self.task_logger.info(msg + "\n" + "=" * len(msg))

        # Initialize task
        self.start = time.time()
        if not self.task.initialized:
            self.task.initialize_task(self.env)
        else:
            self.env_logger.warning(f"Error detected in env {self.env_id}, trying to initialize an initialized task")

        # Allocate step budget
        self.max_steps = self._allocate_step_budget(self.task.complexity)
        self.env_logger.info(f'Env {self.env_id} running task {self.task.name} with goal "{self.task.goal}" and budget "{self.max_steps}"')
        self.task_logger.info(f'Env {self.env_id} running task {self.task.name} with goal "{self.task.goal}" and budget "{self.max_steps}"')

    def _allocate_step_budget(self, task_complexity):
        """
        Allocate step budget based on task complexity.
        
        Args:
            task_complexity: Complexity of the task
            
        Returns:
            int: Number of steps allocated for the task
        """
        if task_complexity is None:
            raise ValueError("Task complexity must be provided.")
        return int(50 * (task_complexity))  # extra generous budget

    def perform_action(self, action):
        """
        Perform an action in the environment.
        
        Args:
            action: Action to perform
            
        Returns:
            bool: True if the action was successful, False otherwise
        """
        try:
            self.env.execute_action(action)
            return True
        except Exception as e:
            self.env_logger.warning(f"An exception occurred during environment interaction in env {self.env_id}")
            self.task_logger.warning(f"An exception occurred during environment interaction in env {self.env_id}")
            self.env_logger.warning(e)
            self.task_logger.warning(e)
            return False

    def step(self, action, thought = "Not provided"):
        """
        Take a step in the environment.
        
        Args:
            action: Action to take
            
        Returns:
            tuple: (observation, reward, terminated, truncated, info)
        """
        if self.terminated:
            return self.current_observation, 0, True, False, {"env_id": self.env_id}

        self.steps += 1
        self.env_logger.info(f"Env {self.env_id} step {self.steps}/{self.max_steps} raw action: {action}")

        self.task_logger.info(f"Env {self.env_id} step {self.steps}/{self.max_steps}")
        self.task_logger.info(f"thought: {thought}")
        self.task_logger.info(f"raw action: {action}")

        # Check if the emulator is running and restart it if needed
        if not self._check_emulator_running():
            self.env_logger.info(f"Emulator {self.avd_name} (ID: {self.env_id}) is not running, attempting to restart...")
            self.task_logger.info(f"Emulator {self.avd_name} (ID: {self.env_id}) is not running, attempting to restart...")
            if not self._restart_emulator():
                self.env_logger.info(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
                self.task_logger.info(f"Failed to restart emulator {self.avd_name} (ID: {self.env_id})")
                self.terminated = True
                return self.current_observation, 0, True, False, {"env_id": self.env_id, "error": "Emulator not running"}
            if not self._restore_env():
                self.env_logger.info(f"Failed to restore emulator {self.avd_name} (ID: {self.env_id})")
                self.task_logger.info(f"Failed to restore emulator {self.avd_name} (ID: {self.env_id})")
                self.terminated = True
                return self.current_observation, 0, True, False, {"env_id": self.env_id, "error": "Emulator not recovered"}

        # Process the action
        AW_action = None

        # Handle invalid actions or max steps exceeded
        if action is None or self.steps > self.max_steps or not isinstance(action, dict):
            self.truncated = True
            self.terminated = True
            AW_action = json_action.JSONAction(
                action_type="status", goal_status="infeasible"
            )

        # Handle infeasible status
        elif action.get("action_type") == "status" and action.get("goal_status") == "infeasible":
            AW_action = json_action.JSONAction(
                action_type="status", goal_status="infeasible"
            )
            self.terminated = True
            self.env_logger.info(f"Terminate Environment {self.env_id}: Max Steps Exceeded {self.max_steps}.")

        # Handle complete status
        elif action.get("action_type") == "status" and action.get("goal_status") == "complete":
            AW_action = json_action.JSONAction(
                action_type="status", goal_status="complete"
            )
            self.terminated = True
        
        # Handle regular actions
        else:     
            try:
                # Convert touch_point to x, y coordinates
                if action.get("touch_point") and len(action.get("touch_point", [])) == 2:
                    action["x"] = action["touch_point"][0] * self.screen_size[0]
                    action["y"] = action["touch_point"][1] * self.screen_size[1]
                    
                # Normalize app_name to lowercase
                if action.get("app_name"):
                    action["app_name"] = action["app_name"].lower()
                    
                # Create JSONAction from action dict
                AW_action = json_action.JSONAction(
                    **{k: v for k, v in action.items() if k != "touch_point"}
                )
                self.env_logger.info(f"Env {self.env_id} step {self.steps}/{self.max_steps} parsed action: {AW_action}")
                self.task_logger.info(f"parsed action: {AW_action}")
                
                # Perform the action
                self.perform_action(action=AW_action)

                self.env_history.append({
                    'action': 'perform_action',
                    'parameter': {
                        'action': AW_action
                    }
                })

            except Exception as e:
                self.env_logger.warning(f"An exception occurred during action parsing in env {self.env_id}")
                self.task_logger.warning(f"An exception occurred during action parsing in env {self.env_id}")
                self.env_logger.warning(e)
                self.task_logger.warning(e)
        
        # Get the next observation
        observation, info = self.get_raw_observation()
        self.current_observation = {
            "image": observation,
            "task": info["task"],
            "ui_elements": info.get("ui_elements", []),
        }

        # Calculate reward — only evaluate on terminal steps (matching reference)
        if self.terminated:
            reward = self.evaluation()
        else:
            reward = 0

        # Check if the episode is done
        if reward >= 1 or self.terminated:
            self.env_logger.info(f"Env {self.env_id} task run time: {time.time() - self.start}")
            self.task_logger.info(f"Env {self.env_id} task run time: {time.time() - self.start}")

        return self.current_observation, reward, self.terminated, self.truncated, info

    def evaluation(self):
        """
        Evaluate if the task was successful.
        
        Returns:
            float: 1.0 if the task was successful, 0.0 otherwise
        """
        try:
            task_successful = self.task.is_successful(self.env)
        except Exception as e:
            task_successful = 0
            self.env_logger.warning(colored("an Exception occurred during evaluation", "red"))
            self.env_logger.warning(e)
            
        agent_successful = task_successful if self.terminated and not self.truncated else 0.0
        r = 1 if agent_successful > 0.5 else 0
        
        self.env_logger.info(f'Env {self.env_id}: {"Task Successful ✅" if r==1 else "Task Failed ❌"}; {self.task.goal}')
        self.task_logger.info(f'Env {self.env_id}: {"Task Successful ✅" if r==1 else "Task Failed ❌"}; {self.task.goal}\n')
        return r

    def render(self):
        """
        Render the environment.
        
        Returns:
            numpy.ndarray: The current observation image if render_mode is "rgb_array", None otherwise
        """
        if self.render_mode == "rgb_array" and self.current_observation is not None:
            return self.current_observation["image"]
        return None

    def close(self):
        """Close the environment and clean up resources."""
        if hasattr(self, "emulator_process") and self.emulator_process is not None:
            try:
                self.emulator_process.terminate()
                self.emulator_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.emulator_process.kill()
            except Exception as e:
                self.env_logger.warning(f"Error closing emulator process in env {self.env_id}: {e}")

        # Kill emulator using ADB
        try:
            subprocess.run(
                [self.adb_path, "-P", str(self.adb_server_port), "-s", f"emulator-{self.console_port}", "emu", "kill"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception as e:
            self.env_logger.warning(f"Error killing emulator via ADB in env {self.env_id}: {e}")

        self.env_logger.info(f"Environment {self.env_id} closed successfully")

    def _check_and_fix_kvm_access(self):
        """Check if the current user has KVM access and fix if needed."""
        try:
            # Check if /dev/kvm exists
            if not os.path.exists('/dev/kvm'):
                self.env_logger.critical("Warning: /dev/kvm does not exist. KVM acceleration may not be available.")
                return
            
            # Check if current user is in the kvm group
            username = pwd.getpwuid(os.getuid()).pw_name
            try:
                kvm_group = grp.getgrnam('kvm')
                user_in_kvm_group = username in kvm_group.gr_mem
            except KeyError:
                self.env_logger.warning("Warning: KVM group does not exist on this system.") # TODO: root user will trigger this as false warning
                self.env_logger.info("Root user will trigger this as false warning.")
                return
            
            # Check if we have permission to access /dev/kvm
            kvm_accessible = os.access('/dev/kvm', os.R_OK | os.W_OK)
            
            if not user_in_kvm_group and not kvm_accessible:
                self.env_logger.Warning(f"Warning: User '{username}' is not in the KVM group and cannot access /dev/kvm")
                
                # Try to fix permissions for this session
                try:
                    # Method 1: Try using setfacl to grant access to this user
                    subprocess.run(['sudo', 'setfacl', '-m', f'u:{username}:rw', '/dev/kvm'], 
                                  check=True, capture_output=True, timeout=5)
                    self.env_logger.info("Applied ACL permissions to allow KVM access for this session.")
                except Exception as e:
                    self.env_logger.info(f"Failed to set KVM permissions with setfacl: {e}")
                    
                    # Method 2: Try changing the group ownership temporarily
                    try:
                        subprocess.run(['sudo', 'chown', f'root:{username}', '/dev/kvm'], 
                                      check=True, capture_output=True, timeout=5)
                        self.env_logger.info("Changed KVM device ownership temporarily.")
                    except Exception as e:
                        self.env_logger.info(f"Failed to change KVM device ownership: {e}")
                        
                        # Method 3: Inform user about permanent fix
                        self.env_logger.info("\nUnable to automatically fix KVM permissions.")
                        self.env_logger.info("Please run these commands to fix permanently:")
                        self.env_logger.info("  sudo usermod -aG kvm $USER")
                        self.env_logger.info("  sudo chmod 666 /dev/kvm")
                        self.env_logger.info("Then log out and log back in, or run 'newgrp kvm' in your terminal.")
            elif not user_in_kvm_group and kvm_accessible:
                self.env_logger.info(f"User '{username}' is not in KVM group but has access to /dev/kvm. Continuing.")
            elif user_in_kvm_group and not kvm_accessible:
                self.env_logger.info(f"User '{username}' is in KVM group but cannot access /dev/kvm. Trying to fix permissions...")
                try:
                    subprocess.run(['sudo', 'chmod', '666', '/dev/kvm'], 
                                  check=True, capture_output=True, timeout=5)
                    self.env_logger.info("Fixed KVM device permissions.")
                except Exception as e:
                    self.env_logger.info(f"Failed to fix KVM permissions: {e}")
        except Exception as e:
            self.env_logger.info(f"Warning: Failed to check KVM group access: {e}")
            self.env_logger.info("If emulator fails to start, ensure your user is in the KVM group.")

    def _check_emulator_running(self):
        """
        Check if the emulator is running and restart it if needed.
        
        Returns:
            bool: True if the emulator is running, False otherwise
        """
        # Check if the emulator process is still running
        if self.emulator_process.poll() is not None:
            self.env_logger.info(f"Emulator process has terminated with exit code {self.emulator_process.returncode}")
            return False
            
        # Check if the emulator is detected by ADB
        try:
            result = subprocess.run(
                [self.adb_path, "-P", str(self.adb_server_port), "devices"],
                capture_output=True,
                text=True,
                check=True
            )
            device_name = f"emulator-{self.console_port}"
            if device_name not in result.stdout:
                self.env_logger.info(f"Emulator {device_name} not detected by ADB")
                return False
        except Exception as e:
            self.env_logger.info(f"Error checking ADB devices: {e}")
            return False
            
        return True
        
    def _restart_emulator(self):
        """
        Restart the emulator if it's not running.
        
        Returns:
            bool: True if the emulator was restarted successfully, False otherwise
        """
        if not self._check_emulator_running():
            self.env_logger.info(f"Restarting emulator {self.avd_name} (ID: {self.env_id})")
            
            # Kill the existing emulator process if it's still running
            if hasattr(self, 'emulator_process') and self.emulator_process.poll() is None:
                try:
                    self.emulator_process.terminate()
                    self.emulator_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.emulator_process.kill()
                except Exception as e:
                    self.env_logger.info(f"Error terminating emulator process: {e}")
            
            # Kill the emulator using ADB
            try:
                subprocess.run(
                    [self.adb_path, "-P", str(self.adb_server_port), "-s", f"emulator-{self.console_port}", "emu", "kill"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except Exception as e:
                self.env_logger.info(f"Error killing emulator via ADB: {e}")
            
            # Wait for the emulator to be fully stopped
            time.sleep(10)
            
            # Start the emulator again
            try:
                self._start_emulator()
                return True
            except Exception as e:
                self.env_logger.info(f"Error restarting emulator: {e}")
                return False
                
        return True
    
    def _restore_env(self):
        """
        Restore the state of a restarted emulator
        
        Returns:
            bool: True if the emulator state was restored successfully, False otherwise
        """
        self.env_logger.info(f"Restoring from environment history. (ID: {self.env_id})")
        self.task_logger.info(f"Restoring from environment history. (ID: {self.env_id})")

        for entry in self.env_history:
            action_name = entry['action']
            parameters = entry['parameter']

            method = getattr(self, action_name, None)
            if method is None:
                self.env_logger.info(f"Restore emulator state failed: Unknown action '{action_name}'")
                self.task_logger.info(f"Restore emulator state failed: Unknown action '{action_name}'")
            try:
                method(**parameters)
            except Exception as e:
                self.env_logger.info(f"Restore emulator state failed with error: '{e}'")
                self.task_logger.info(f"Restore emulator state failed with error: '{e}'")
                return False
            
            # Wait for action to be performed
            if action_name == "perform_action":
                time.sleep(5)
        return True
    
    def custom_log(self, log_str):
        self.task_logger.info(log_str)
