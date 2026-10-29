"""돈 계산 속성 테스트 프로필: dev=200개, nightly=5000개."""

import os

import pytest

hypothesis = pytest.importorskip("hypothesis")

hypothesis.settings.register_profile(
    "dev",
    max_examples=200,
    deadline=None,
)
hypothesis.settings.register_profile(
    "nightly",
    max_examples=5000,
    deadline=None,
)
hypothesis.settings.load_profile(
    os.environ.get("HYPOTHESIS_PROFILE", "dev")
)
