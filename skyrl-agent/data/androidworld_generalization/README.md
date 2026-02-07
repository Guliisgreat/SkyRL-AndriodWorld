# AndroidWorld Dataset

This folder contains datasets and data preparation scripts for AndroidWorld tasks.

## Structure

```
data/androidworld/
├── README.md              # This file
├── prepare_data.py        # Data preparation script (optional)
├── train.json             # Training dataset
├── validation.json        # Validation dataset
└── test.json              # Test dataset (optional)
```

## Dataset Format

Each JSON file contains a list of task instances:

```json
[
  {
    "instance_id": 0,
    "task_id": "contacts_add_contact",
    "task": "Add a new contact named John Doe with phone number 555-1234",
    "task_family": "android_world",
    ...
  },
  ...
]
```

## Usage

Reference these files in `verl_android.sh`:

```bash
DATA_DIR="./data/androidworld"
train_data="${DATA_DIR}/train.json"
test_data="${DATA_DIR}/validation.json"
```
