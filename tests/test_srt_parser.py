"""
测试 utils/srt_parser.py
纯逻辑解析，不依赖外部 API，离线段可独立运行
"""
from pathlib import Path

from utils.srt_parser import parse_srt, blocks_to_prompt_text, sec_to_timestamp

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_standard_srt():
    """标准 SRT 格式应正确解析出 5 条字幕块"""
    content = (FIXTURES_DIR / "subtitle_sample.srt").read_text(encoding="utf-8")
    blocks = parse_srt(content)

    assert len(blocks) == 5

    # 检查第 1 条
    assert blocks[0].index == 1
    assert blocks[0].start_sec == 5.0
    assert blocks[0].end_sec == 10.0
    assert "房價" in blocks[0].text

    # 检查第 3 条（中间）
    assert blocks[2].index == 3
    assert blocks[2].start_sec == 15.5
    assert "16年" in blocks[2].text

    # 检查最后一条
    assert blocks[4].index == 5
    assert blocks[4].start_sec == 26.0
    assert "資金氾濫" in blocks[4].text


def test_parse_plain_text():
    """纯文本字幕（无时间戳）应能自动解析并分配时间"""
    content = (FIXTURES_DIR / "subtitle_plain.txt").read_text(encoding="utf-8")
    blocks = parse_srt(content)

    assert len(blocks) == 5
    assert blocks[0].index == 1
    assert blocks[0].start_sec == 0.0
    assert blocks[0].end_sec == 3.0
    assert "房價" in blocks[0].text


def test_parse_malformed_srt():
    """混合格式（部分标准 SRT + 部分杂乱文字）应正常解析有效部分"""
    content = (FIXTURES_DIR / "subtitle_malformed.srt").read_text(encoding="utf-8")
    blocks = parse_srt(content)

    assert len(blocks) >= 2
    assert "第一條正常字幕" in blocks[0].text
    assert "第二條正常字幕" in blocks[1].text


def test_parse_empty_content():
    """空内容应返回空列表"""
    blocks = parse_srt("")
    assert blocks == []


def test_parse_whitespace_only():
    """纯空白内容应返回空列表"""
    blocks = parse_srt("   \n\n  \n  ")
    assert blocks == []


def test_blocks_to_prompt_text():
    """blocks_to_prompt_text 应输出 [MM:SS] 格式文本"""
    content = (FIXTURES_DIR / "subtitle_sample.srt").read_text(encoding="utf-8")
    blocks = parse_srt(content)
    result = blocks_to_prompt_text(blocks)

    assert "[00:05]" in result
    assert "房價" in result
    assert "[00:15]" in result
    assert "16年" in result

    lines = result.strip().splitlines()
    assert len(lines) == 5


def test_sec_to_timestamp():
    """秒数转换为可读时间戳"""
    assert sec_to_timestamp(0) == "0:00"
    assert sec_to_timestamp(5) == "0:05"
    assert sec_to_timestamp(80) == "1:20"
    assert sec_to_timestamp(3661) == "1:01:01"


def test_sec_to_timestamp_large():
    """大秒数也能正确处理"""
    assert sec_to_timestamp(7200) == "2:00:00"
    assert sec_to_timestamp(3661) == "1:01:01"
