# Copyright 2025 The android_world Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""pytest configuration for Tier 4 unit tests.

Unit tests exercise is_successful() in isolation by pre-setting task state
(e.g. _ground_truth) rather than calling initialize_task() on a real device.
Bypass the initialization guard so these targeted tests can run without ADB.
"""

from android_world.task_evals import task_eval


def pytest_configure(config):
    task_eval.TaskEval._check_is_initialized = lambda self: None
