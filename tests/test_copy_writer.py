"""
测试 services/copy_writer.py
模拟用户真实操作流程：读取 topic + 字幕 → 调用 LLM → 验证输出格式

注意：这部分测试会实际调用 Qwen API，属于集成测试。
若 API 不可达或 key 无效，测试会被跳过而非失败。
"""
import pytest

from services.copy_writer import generate_copy, _clean_json


# ── 工具函数测试（离线段，不调 API）────────────────────────────────────────────

class TestCleanJson:
    def test_clean_json_no_backticks(self):
        """无 markdown 包裹时直接返回原内容"""
        raw = '{"fb_post": {}}'
        assert _clean_json(raw) == raw

    def test_clean_json_with_triple_backtick(self):
        """去掉 ```json ... ``` 包裹"""
        raw = "```json\n{\"fb_post\": {}}\n```"
        assert _clean_json(raw) == '{"fb_post": {}}'

    def test_clean_json_with_triple_backtick_no_lang(self):
        """去掉 ``` ... ``` 包裹（未指定语言）"""
        raw = "```\n{\"fb_post\": {}}\n```"
        assert _clean_json(raw) == '{"fb_post": {}}'

    def test_clean_json_extra_whitespace(self):
        """前后空白应被 strip"""
        raw = "  \n  {\"fb_post\": {}}  \n  "
        assert _clean_json(raw) == '{"fb_post": {}}'


# ── 集成测试（实际调用 Qwen API）──────────────────────────────────────────────

@pytest.mark.integration
class TestGenerateCopyWithRealApi:
    """模拟用户真实操作：读文件 → 调用 API → 检查输出"""

    def test_output_contains_expected_keys(self, topic_house, subtitle_srt):
        """返回结果应包含 fb_post 和 captions 两个顶级字段"""
        result = generate_copy(topic_house, subtitle_srt)

        assert "fb_post" in result
        assert "captions" in result

        fb = result["fb_post"]
        assert "opening" in fb
        assert "body" in fb
        assert "closing" in fb
        assert "cta" in fb
        assert "tags" in fb

    def test_captions_is_list_of_5(self, topic_house, subtitle_srt):
        """captions 应是长度为 5 的字符串列表"""
        result = generate_copy(topic_house, subtitle_srt)
        captions = result["captions"]

        assert isinstance(captions, list)
        assert len(captions) == 5
        for c in captions:
            assert isinstance(c, str)
            assert len(c) > 0

    def test_output_topic_relevant(self, topic_house, subtitle_srt):
        """输出内容应与输入的「房价」主题相关"""
        result = generate_copy(topic_house, subtitle_srt)
        full_text = (
            result["fb_post"]["opening"]
            + result["fb_post"]["body"]
            + result["fb_post"]["closing"]
            + result["fb_post"]["cta"]
        )
        # 应出现与房价相关的关键词之一
        assert any(kw in full_text for kw in ["房", "房價", "買房", "房貸", "打房"]), \
            f"输出内容与房价主题无关：{full_text[:100]}"

    def test_captions_within_length_limit(self, topic_house, subtitle_srt):
        """每条金句 caption 不应超过 15 字"""
        result = generate_copy(topic_house, subtitle_srt)
        for c in result["captions"]:
            assert len(c) <= 15, f"金句过长（{len(c)}字）：{c}"

    def test_fb_post_fields_not_empty(self, topic_house, subtitle_srt):
        """fb_post 的 5 个字段均不应为空"""
        result = generate_copy(topic_house, subtitle_srt)
        fb = result["fb_post"]
        for key in ["opening", "body", "closing", "cta", "tags"]:
            assert fb[key], f"fb_post.{key} 为空"

    def test_with_plain_text_subtitle(self, topic_house, subtitle_plain):
        """用户上传纯文本字幕（非 SRT）时也能正常生成"""
        result = generate_copy(topic_house, subtitle_plain)
        assert "fb_post" in result
        assert "captions" in result

    def test_with_malformed_subtitle(self, topic_house, subtitle_malformed):
        """用户上传格式不标准的字幕时也能正常生成"""
        result = generate_copy(topic_house, subtitle_malformed)
        assert "fb_post" in result
        assert "captions" in result
