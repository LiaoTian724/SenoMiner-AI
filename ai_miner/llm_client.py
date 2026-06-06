# ai_miner/llm_client.py

import os
import json
import time
from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("ARK_API_KEY")
BASE_URL = os.getenv("ARK_BASE_URL")
MODEL_ID = os.getenv("ARK_MODEL_ID")


if not API_KEY or not MODEL_ID:
    print("未检测到合规的 ARK_API_KEY 或 ARK_MODEL_ID, 请检查 .env 文件！")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

def call_doubao_json(prompt: str, system_prompt: str, max_retries: int = 5) -> dict:
    """
    调用豆包API并弹性强制返回标准的 Python 字典 (JSON)
    网络抖动和 API 限流
    """
    # 如果客户端未正确初始化，直接返回空字典
    if not API_KEY:
        print("API_KEY 为空!")
        return {}

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=30  # 超时控制
            )
            
            res_content = response.choices[0].message.content
            if not res_content:
                raise ValueError("大模型返回了空的文本内容")

            # 尝试解析 JSON
            try:
                return json.loads(res_content)
            except json.JSONDecodeError as je:
                print(f"大模型返回了非标准JSON。原内容: {res_content[:200]}... 错误: {je}")
                raise je  # 抛出以触发外层重试
                
        except Exception as e:
            sleep_time = 2 ** (attempt + 1)
            print(f"正在进行第 {attempt + 1}/{max_retries} 次重试... "
                  f"等待 {sleep_time} 秒。错误原因: {e}")
            time.sleep(sleep_time)
            
    print(f"在{max_retries} 次重试后依旧无法获取有效数据，返回空结果占位")
    return {}  # 注意返回空字典而不是 None!