# AndroidWorld Runtime Layer Tests

## Running Tests

### Unit Tests

```bash
# Run all ContainerManager tests
pytest tests/skyrl_agent/runtime/androidworld/test_container_manager.py -v

# Run all RuntimeClient tests
pytest tests/skyrl_agent/runtime/androidworld/test_runtime_client.py -v

# Run all runtime tests
pytest tests/skyrl_agent/runtime/androidworld/ -v
```

### Coverage

```bash
pytest --cov=skyrl_agent.runtime.androidworld --cov-report=html tests/skyrl_agent/runtime/androidworld/
```

## Test Structure

- `test_container_manager.py`: Tests for container pool management
- `test_runtime_client.py`: Tests for HTTP client communication
- `conftest.py`: Shared test fixtures

