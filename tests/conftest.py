"""
pytest 共享夹具：所有 test_*.py 均可直接使用
"""
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def topic_house() -> str:
    """读取测试用的「房价」核心观点"""
    return (FIXTURES_DIR / "topic_house.txt").read_text(encoding="utf-8").strip()


@pytest.fixture
def subtitle_srt() -> str:
    """读取测试用的标准 SRT 字幕"""
    return (FIXTURES_DIR / "subtitle_sample.srt").read_text(encoding="utf-8")


@pytest.fixture
def subtitle_plain() -> str:
    """读取测试用的纯文本字幕"""
    return (FIXTURES_DIR / "subtitle_plain.txt").read_text(encoding="utf-8")


@pytest.fixture
def subtitle_malformed() -> str:
    """读取测试用的混合格式字幕"""
    return (FIXTURES_DIR / "subtitle_malformed.srt").read_text(encoding="utf-8")
