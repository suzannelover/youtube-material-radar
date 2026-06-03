"""
keyword.py
職責：接收用戶自然語言輸入，調用 Qwen 提煉結構化三層搜索關鍵詞
"""

import json
from openai import OpenAI
from config import QWEN_API_KEY


_client = OpenAI(
    api_key=QWEN_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)


def extract_keywords(user_input: str) -> dict:
    """
    返回:
    {
        "layer1": "最精準 2 詞",
        "layer2": "稍寬 2 詞",
        "layer3": "兜底 1 詞",
        "display": "展示用關鍵詞"
    }
    """
    prompt = f"""
用戶輸入了一段描述，請提取搜索查詢，輸出 JSON 格式：
{{
  "layer1": "最核心的2個詞組合，能精準命中事件，詞之間用空格分隔",
  "layer2": "核心人物或主體 + 次要關鍵詞，2個詞，用空格分隔",
  "layer3": "單一最重要的詞，1個詞",
  "display": "3-5個關鍵詞用空格分隔，用於界面展示"
}}

規則：
- layer1 最精準，2個詞，必須能同時命中目標事件
- layer2 稍寬，2個詞，核心主體加上角度或屬性詞
- layer3 最寬，1個詞，兜底用
- 每層都是繁體中文
- 只輸出 JSON，不要任何其他文字

用戶描述：{user_input}
"""
    response = _client.chat.completions.create(
        model="qwen-plus",
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = _clean_json(response.choices[0].message.content)
    result = json.loads(raw)
    print(f"[Keyword] layer1=「{result['layer1']}」| layer2=「{result['layer2']}」| layer3=「{result['layer3']}」")
    return result


def _clean_json(raw: str) -> str:
    """去掉 LLM 可能输出的 markdown 代码块包裹"""
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()
