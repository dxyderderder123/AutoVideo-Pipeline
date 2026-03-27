# =============================================================================
# V2：字幕修正脚本 - 批量处理 + 智能引号句首修正
# 用途：批量处理指定子目录下的SRT文件，将出现在句首的中文反引号“)”
#       移动到上一个字幕的末尾。
# =============================================================================

import os
import re
import sys
from typing import List, Set, Tuple

# ========== 全局配置区域 ==========
# 根目录路径：处理文件所在的文件夹（与您的其他脚本保持一致）
BASE_ROOT = r"V:\Default\Desktop\投稿视频\5中国古代科学哲学"

# 每天需要改的子文件夹名列表，支持批量处理
# 示例：如果您需要处理 "5中国古代科学哲学\3法兰克福\其他" 文件夹，
#      则在列表中填写 "3法兰克福\其他"
TARGET_SUBDIRS = ["32一背景"+"\其他"] 

# 要处理的字幕文件名列表（在每个 TARGET_SUBDIRS 内部查找）
TARGET_SRT_FILENAMES = ["男字幕.srt", "女字幕.srt"] 

# 修正后字幕文件的前缀
OUTPUT_PREFIX = "修正_"

# 定义要处理的字符集合 (已修改: 现在包含 '”' 和 '）')
# 只要句首出现这些字符，都会被移动到前一个字幕块的末尾
QUOTE_CHAR = '’”）。,' 
# =================================


def process_srt_for_quotes_v2(input_file: str, output_file: str, quote_char: str) -> bool:
    """
    V2 字幕修正：
    1. 查找当前字幕块文本开头处的指定引号字符（如 ”）。
    2. 将该引号移动到上一个字幕块的末尾。
    3. 如果移动后当前字幕块变为空，则删除该字幕块。
    
    返回：如果文件被修改，返回 True；否则返回 False。
    """
    if not os.path.exists(input_file):
        print(f"警告：输入文件不存在: {input_file}")
        return False

    # 尝试读取文件
    try:
        with open(input_file, 'r', encoding='utf-8') as f_in:
            lines = f_in.readlines()
    except Exception as e:
        print(f"错误：无法读取文件 {input_file}：{e}")
        return False
    
    processed_lines: List[str] = []
    # 记录上一个有效字幕块中“最后一行文本”在 processed_lines 中的索引
    # 此索引用于定位和附加引号
    last_text_line_out_index: int = -1
    i = 0
    n = len(lines)
    modified = False

    while i < n:
        line = lines[i]
        
        # 1. 识别序号行（标准块起始）
        if re.match(r'^\s*\d+\s*$', line):
            # 1.1 读取当前字幕块的序号、时间
            num_line = line
            i += 1
            if i >= n: break
            time_line = lines[i]
            i += 1
            if i >= n: break

            # 1.2 提取文本行
            text_lines: List[str] = []
            j = i
            while j < n and lines[j].strip() != '' and not re.match(r'^\s*\d+\s*$', lines[j]):
                text_lines.append(lines[j])
                j += 1
            
            # 1.3 检查文本行是否以引号开头
            # 这里检查的是文本行是否以 '”' 或 '）' 开头
            starts_with_quote = any(text_lines[0].lstrip().startswith(c) for c in quote_char) if text_lines else False

            if starts_with_quote:
                modified = True
                
                # a. 移动引号字符
                current_line = text_lines[0].lstrip()
                
                # 确定要移动的字符并移除（只移除最开头的一个字符，无论是 ” 还是 ））
                char_to_move = ''
                for char in quote_char:
                    if current_line.startswith(char):
                        char_to_move = char
                        break
                
                if char_to_move:
                    
                    # 移除当前行开头的该字符
                    new_text_line_content = current_line.lstrip(char_to_move).lstrip()
                    
                    # 重新构建当前字幕行：保留末尾换行符
                    text_lines[0] = new_text_line_content + ('\n' if text_lines[0].endswith('\n') else '')
                    
                    # 附加到上一个字幕文本的末尾
                    if last_text_line_out_index != -1:
                        # 找到上一个字幕的文本行
                        last_text_line = processed_lines[last_text_line_out_index]
                        
                        # 移除上一个字幕文本行末尾的换行符
                        if last_text_line.endswith('\n'):
                            last_text_line = last_text_line[:-1]
                        
                        # 添加被移动的字符，并确保末尾有一个换行符
                        processed_lines[last_text_line_out_index] = last_text_line + char_to_move + '\n'
                        
                        # 为了打印日志，获取上一个块的序号
                        # 序号在 last_text_line_out_index 往前数两行
                        prev_num = processed_lines[last_text_line_out_index-2].strip() if last_text_line_out_index >= 2 else "N/A"
                        print(f"  → 修正：字符 '{char_to_move}' 移动到前一句末尾 (序号 {prev_num})")
                    else:
                        print(f"  → 警告：字符 '{char_to_move}' 无法移动 (无上一个字幕块)，已删除。")
                    
                    # b. 处理移动后的当前字幕块
                    
                    # 检查当前字幕块是否变为空
                    is_empty_after_move = all(t.strip() == '' for t in text_lines)
                    
                    if is_empty_after_move:
                        # 如果为空，删除整个块（序号+时间+文本），跳到下一块
                        print(f"  → 修正：字幕块 {num_line.strip()} 仅剩空白，已删除。")
                        i = j # i 跳到当前块文本结束后的位置
                        # 额外跳过一个空行（如果存在）
                        if i < n and lines[i].strip() == '': 
                            i += 1 
                        continue
            
            # 正常或修正后的字幕块：写入 processed_lines
            # 检查：即使没有引号，如果文本行全空，也跳过这个块
            if all(t.strip() == '' for t in text_lines):
                i = j
                if i < n and lines[i].strip() == '':
                    i += 1
                continue
            
            processed_lines.append(num_line)
            processed_lines.append(time_line)
            # 写入文本行
            current_text_start_index = len(processed_lines) 
            for t in text_lines:
                processed_lines.append(t if t.endswith('\n') else t + '\n')
            
            # 如果原始块后面有空行，原样保留
            if j < n and lines[j].strip() == '':
                processed_lines.append(lines[j])
                i = j + 1
            else:
                i = j
                
            # 更新上一条字幕的“最后一行文本”的索引
            # 最后一行文本是 processed_lines 中的最后一个文本行
            last_text_line_out_index = current_text_start_index + len(text_lines) - 1
            continue
            
        else:
            # 不是标准块起始（非序号、非空行），直接复制
            processed_lines.append(lines[i])
            i += 1
            
    if modified:
        try:
            with open(output_file, 'w', encoding='utf-8') as f_out:
                # 写入处理后的行
                f_out.writelines(processed_lines)
                
            print(f"✅ 修正后的字幕已保存到: {output_file}")
            # 额外添加一个警告：由于删除块，序号可能不连续，建议使用专业工具重新编号
            print(f"⚠️ 注意：由于字幕块被删除，文件序号可能不连续，建议使用工具重新编号。")
        except Exception as e:
             print(f"❌ 错误：写入修正后的文件 {output_file} 时失败: {e}")
             return False
    else:
        print(f"ℹ️ 文件 {os.path.basename(input_file)} 未发现需要修正的引号。")
        
    return modified


def main_srt_batch_processor():
    """
    批量处理 TARGET_SUBDIRS 列表中的每个文件夹下的 SRT 文件的主要入口函数。
    """
    if not TARGET_SUBDIRS:
        print("错误：TARGET_SUBDIRS 列表为空，没有文件夹需要处理。")
        return

    print(f"===== 开始批量字幕修正（根目录: {BASE_ROOT}）=====")
    
    total_modified_count = 0
    total_processed_count = 0
    
    for sub_dir in TARGET_SUBDIRS:
        # 1. 构造当前子文件夹的完整路径
        root_dir = os.path.join(BASE_ROOT, sub_dir)
        
        print(f"\n--- 正在处理目录: {root_dir} ---")
        
        if not os.path.isdir(root_dir):
            print(f"❌ 错误：目标子目录不存在: {root_dir}")
            continue

        for filename in TARGET_SRT_FILENAMES:
            total_processed_count += 1
            
            input_file_path = os.path.join(root_dir, filename)
            output_file_path = os.path.join(root_dir, f"{OUTPUT_PREFIX}{filename}")
            
            print(f"   > 尝试修正文件: {filename}")
            
            try:
                if process_srt_for_quotes_v2(input_file_path, output_file_path, QUOTE_CHAR):
                    total_modified_count += 1
            except Exception as e:
                print(f"❌ 严重错误：处理文件 {input_file_path} 时发生异常: {e}")
                # 打印堆栈信息，方便调试
                # import traceback
                # print(traceback.format_exc())

    print(f"\n===== 批量修正完成。=====")
    print(f"总共尝试处理 {total_processed_count} 个文件。")
    print(f"其中 {total_modified_count} 个文件被修正并保存。")


if __name__ == "__main__":
    # 确保运行路径正确
    main_srt_batch_processor()
