"""
copy_writer.py
職責：根據核心觀點 + 字幕，生成 FB/IG 爆款貼文及影片金句字幕
"""

import json
from openai import OpenAI
from config import QWEN_API_KEY


_client = OpenAI(
    api_key=QWEN_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

_SYSTEM_PROMPT = """你是一位極具洞察力的台灣自媒體評論家。你對執政當局主政下的社會亂象深感不滿，擅長用犀利、幽默且充滿情緒的在地口語，拆穿政客的謊言，引發一般民眾的共鳴。

【核心要求】
- 你的批判必須緊扣用戶提供的【核心觀點】和【影片字幕】中所涉及的具體社會問題與民生痛點，從中提煉素材，而不是依賴預設的議題列表。

【撰寫規範】
1. 語言風格：100% 台灣在地口語（例如：講乾話、割韭菜、大撒幣、綠能你不能、真的太離譜、苦民所苦都是假）。
2. 情緒基調：諷刺、憤怒、痛心、充滿力量。
3. 受眾鎖定：台灣基層百姓、對現狀不滿的中老年族群、被通膨壓得喘不過氣的年輕人及打工族。
4. 避雷指南：絕對不要出現大陸用語（如：質量、優化、水平、給力），請替換為（品質、優化/提升、水準、超讚/厲害）。"""


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def generate_copy(topic: str, subtitle: str) -> dict:
    """
    參數:
        topic    - 用戶輸入的核心觀點
        subtitle - 字幕文本（SRT 或純文字均可）
    返回:
        {
            "fb_post": { opening, body, closing, cta, tags },
            "captions": ["金句1", ..., "金句5"]
        }
    """
    # 字幕清洗：去空行，截斷到 2000 字
    cleaned = "\n".join(line.strip() for line in subtitle.splitlines() if line.strip())
    cleaned = cleaned[:2000]

    user_prompt = f"""根據以下【核心觀點】與【影片字幕】，產出內容。

【核心觀點】
{topic}

【影片字幕】
{cleaned}

請嚴格按照以下 JSON 格式輸出，不要任何其他文字：
{{
  "fb_post": {{
    "opening": "【震撼首行】一句話把火點起來，包含民生痛點",
    "body": "【內容論述】結合影片對話，針對核心觀點中所指的社會問題進行精準抨擊，凸顯執政者與百姓之間的落差對比，2-4段",
    "closing": "【紮心結論】台式幽默或酸度破表的收尾一句話",
    "cta": "【留言區引戰】讓大家忍不住想進來罵兩句的問題",
    "tags": "【標籤】#台灣現狀 #講乾話 #百姓的心聲 等5個標籤"
  }},
  "captions": [
    "金句一，不超過10字",
    "金句二，不超過10字",
    "金句三，不超過10字",
    "金句四，不超過10字",
    "金句五，不超過10字"
  ]
}}"""

    response = _client.chat.completions.create(
        model="qwen-plus",
        temperature=0.7,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt}
        ]
    )
    raw = _clean_json(response.choices[0].message.content)
    return json.loads(raw)
