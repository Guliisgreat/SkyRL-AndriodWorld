"""
Custom dataset for AndroidWorld tasks.

Reads JSONL files with task definitions and provides them to the training pipeline.
"""

import json
from typing import Any, Dict, List, Optional

from torch.utils.data import Dataset


class AndroidWorldDataset(Dataset):
    """Dataset for AndroidWorld training tasks.

    Reads JSONL files containing task definitions with task_id, seed, and task description.
    Returns data in the format expected by skyrl-agent's AndroidAgentRunner.
    """

    def __init__(
        self,
        data_files: str,
        tokenizer: Any = None,
        processor: Any = None,
        config: Any = None,
        is_train: bool = True,
        **kwargs,
    ):
        """Initialize AndroidWorldDataset.

        Args:
            data_files: Path to JSONL file(s) containing task definitions
            tokenizer: Tokenizer instance (not used for initial prompt, kept for compatibility)
            processor: Processor instance (not used for initial prompt, kept for compatibility)
            config: Data configuration
            is_train: Whether this is training data
            **kwargs: Additional arguments (ignored)
        """
        self.tokenizer = tokenizer
        self.processor = processor
        self.config = config
        self.is_train = is_train
        self.data: List[Dict[str, Any]] = []

        # Handle single file or list of files
        if isinstance(data_files, str):
            data_files = [data_files]

        for filepath in data_files:
            self._load_file(filepath)

    def _load_file(self, filepath: str):
        """Load tasks from a JSONL file."""
        with open(filepath, 'r') as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Build the data item expected by skyrl-agent
                    item = {
                        "instance_id": f"{entry.get('task_id', line_num)}_{entry.get('seed', 0)}",
                        "instance": {
                            "task_id": entry.get("task_id", line_num),
                            "seed": entry.get("seed", 0),
                            "task": entry.get("task", ""),
                            "difficulty": entry.get("difficulty", ""),
                            "category": entry.get("category", ""),
                            "instance_id": f"{entry.get('task_id', line_num)}_{entry.get('seed', 0)}",
                        },
                        "data_source": "android_world",
                        # Raw chat format for agent-based training
                        "raw_prompt": [
                            {
                                "role": "user",
                                "content": entry.get("task", ""),
                            }
                        ],
                    }
                    self.data.append(item)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse line {line_num} in {filepath}: {e}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        return self.data[idx]


def create_android_dataset(
    data_files: str,
    config: Any,
    tokenizer: Any = None,
    processor: Any = None,
    is_train: bool = True,
) -> AndroidWorldDataset:
    """Factory function to create AndroidWorldDataset.

    Args:
        data_files: Path to JSONL file(s)
        config: Data configuration
        tokenizer: Tokenizer instance
        processor: Processor instance
        is_train: Whether this is training data

    Returns:
        AndroidWorldDataset instance
    """
    return AndroidWorldDataset(
        data_files=data_files,
        tokenizer=tokenizer,
        processor=processor,
        config=config,
        is_train=is_train,
    )
