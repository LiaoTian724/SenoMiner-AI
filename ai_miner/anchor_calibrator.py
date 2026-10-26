
import re
from typing import Dict, Optional
from backend.pipelines.logger import log_print

def generate_safe_text_anchor(full_text: str, compound_name: str, window_size: int = 150) -> Optional[Dict]:
    """
    【文本锚点校准器】
    在给定的全长文本/摘要中，动态检索分子的出现位置，并向外辐射截取指定长度的上下文作为‘事实锚点’。
    同时进行模糊和大小写不敏感匹配，防止 AI 拼写变形导致定位失败。
    
    :param full_text: 原始全长文本或摘要
    :param compound_name: AI 提取出的化学物质/分子名称
    :param window_size: 锚点上下文向前/向后辐射的字符数
    :return: 包含锚点句及物理偏移量的字典，匹配失败返回 None
    """
    if not full_text or not compound_name:
        return None

    text_len = len(full_text)
    cleaned_name = str(compound_name).strip()
    
    # 构造大小写不敏感的正则转义匹配，防止小分子代号包含特殊符号(如括弧)导致正则崩溃
    try:
        pattern = re.compile(re.escape(cleaned_name), re.IGNORECASE)
    except Exception as e:
        log_print(f"[锚点校准] 正则编译失败 ({cleaned_name}): {e}")
        return None

    # 寻找第一个物理匹配点
    match = pattern.search(full_text)
    
    # 兜底
    if not match and cleaned_name.lower().endswith('s'):
        fallback_name = cleaned_name[:-1]
        pattern = re.compile(re.escape(fallback_name), re.IGNORECASE)
        match = pattern.search(full_text)

    if match:
        start_pos, end_pos = match.start(), match.end()
        
        # 匹配点为核心，向左右辐射安全窗口，切片出上下文
        anchor_start = max(0, start_pos - window_size)
        anchor_end = min(text_len, end_pos + window_size)
        
        raw_anchor_text = full_text[anchor_start:anchor_end]
        
        # 修剪切片边缘，防止单词被从中间切断，使其读起来更像人话
        # 向前修剪到第一个空格
        if anchor_start > 0:
            first_space = raw_anchor_text.find(' ')
            if first_space != -1 and first_space < 20:
                raw_anchor_text = raw_anchor_text[first_space + 1:]
                anchor_start += first_space + 1
        # 向后修剪到最后一个空格
        if anchor_end < text_len:
            last_space = raw_anchor_text.rfind(' ')
            if last_space != -1 and (len(raw_anchor_text) - last_space) < 20:
                raw_anchor_text = raw_anchor_text[:last_space]
                anchor_end = anchor_start + last_space

        return {
            "matched_text": full_text[start_pos:end_pos], # 原始文本中实际对应的文本
            "char_start": start_pos,                      # 绝对物理起始偏移量
            "char_end": end_pos,                          # 绝对物理结束偏移量
            "anchor_context": f"...{raw_anchor_text.strip()}..." # 留存的前后文证据链
        }

    # 如果在全文本里连影子都没找到，说明大模型可能在幻觉编造药名，属于不实数据
    return None