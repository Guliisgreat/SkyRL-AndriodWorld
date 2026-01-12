# AndroidWorld Task Layer Tests

## Running Tests

```bash
# Run all AndroidWorldTask tests
pytest tests/skyrl_agent/tasks/androidworld/test_task.py -v

# Run with coverage
pytest --cov=skyrl_agent.tasks.androidworld --cov-report=html tests/skyrl_agent/tasks/androidworld/
```

## Test Coverage

- `initialize_runtime()`: Container pool creation
- `get_instruction()`: Message formatting
- `evaluate_result()`: Reward computation
- `_numpy_to_base64()`: Image encoding

