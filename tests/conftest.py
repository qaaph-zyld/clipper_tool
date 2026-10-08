import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests that require ffmpeg/whisperx (skipped by default)"
    )


def pytest_collection_modifyitems(config, items):
    skip_integration = pytest.mark.skip(reason="Integration test — requires ffmpeg/whisperx")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
