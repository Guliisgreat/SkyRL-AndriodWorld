"""
Test fixtures for AndroidWorldTask tests.
"""

import numpy as np
import pytest


@pytest.fixture
def sample_observation():
    """Create sample observation dict."""
    return {
        "task": "Open calculator app",
        "image": np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    }

