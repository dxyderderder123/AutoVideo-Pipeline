import json
import os
import sys

# ========================= 全局配置区域 ===============================
# 根目录路径，需要与素材生成脚本保持一致
BASE_ROOT = r"V:\Default\Desktop\投稿视频\5中国古代科学哲学"
# 要处理的子文件夹名称列表，修改这里即可批量处理
TARGET_SUBDIRS = ["32一背景"] # 示例：请根据您的需求填写，如 ["3法兰克福", "0哲学引论"]
JSON_FILENAME = "prompt.json" # 每个子文件夹内用于描述任务的 JSON 文件名

# 定义输出文件名
MALE_OUTPUT_FILENAME = "男.txt"
FEMALE_OUTPUT_FILENAME = "女.txt"
# ====================================================================

# 将核心逻辑封装成一个函数
def separate_captions_by_gender(sub_folder: str):
    """
    处理单个子文件夹，读取 prompt.json 并按 gender 分离字幕到 '男.txt' 和 '女.txt'。
    """
    
    # 1. 构造 JSON 文件的完整路径
    json_path = os.path.join(BASE_ROOT, sub_folder, JSON_FILENAME)

    print(f"\n===== 开始处理文件夹：{sub_folder} =====")
    
    try:
        # 2. 打开JSON文件并加载数据
        with open(json_path, 'r', encoding='utf-8') as file:
            data = json.load(file)

        # 3. 提取文件所在目录，用于保存txt文件
        file_dir = os.path.dirname(json_path)
        male_output_path = os.path.join(file_dir, MALE_OUTPUT_FILENAME)
        female_output_path = os.path.join(file_dir, FEMALE_OUTPUT_FILENAME)

        # 4. 用于存储不同角色的 caption
        male_captions = []    # gender "1" 齐静春 (男性)
        female_captions = []  # gender "0" 剑灵 (女性)

        # 5. 遍历JSON数据，按gender分离字幕
        for item in data:
            caption = item.get('caption')
            gender = item.get('gender')
            
            if caption:
                if gender == "1":
                    male_captions.append(caption)
                elif gender == "0":
                    female_captions.append(caption)
                else:
                    print(f"警告：[{sub_folder}] 发现缺少或无法识别的 gender 字段 ({gender})。字幕将跳过保存: {caption[:20]}...")
            
        # 6. 将内容写入各自的TXT文件
        
        # 写入女声字幕
        female_output_text = '\n'.join(female_captions)
        with open(female_output_path, 'w', encoding='utf-8') as f:
            f.write(female_output_text)
        print(f"女声字幕（共 {len(female_captions)} 条）已成功保存到: {female_output_path}")

        # 写入男声字幕
        male_output_text = '\n'.join(male_captions)
        with open(male_output_path, 'w', encoding='utf-8') as f:
            f.write(male_output_text)
        print(f"男声字幕（共 {len(male_captions)} 条）已成功保存到: {male_output_path}")

        print(f"✅ {sub_folder} 字幕分离和保存任务完成。总共处理 {len(data)} 条记录。")

    except FileNotFoundError:
        print(f"❌ 错误：[{sub_folder}] 未找到文件: {json_path}，请检查文件路径是否正确。")
    except json.JSONDecodeError:
        print(f"❌ 错误：[{sub_folder}] 无法解析JSON文件，请确认文件内容是否为有效的JSON格式。")
    except Exception as e:
        print(f"❌ [{sub_folder}] 发生未知错误: {e}")
        

# ========== 主程序入口 ==========
if __name__ == "__main__":
    
    if not TARGET_SUBDIRS:
        print("警告：TARGET_SUBDIRS 列表为空，没有文件夹需要处理。")
        sys.exit(0)
    
    print(f"--- 批量字幕分离工具启动 ---")
    print(f"根目录: {BASE_ROOT}")
    print(f"待处理文件夹: {', '.join(TARGET_SUBDIRS)}")
    
    processed_count = 0
    
    for folder_name in TARGET_SUBDIRS:
        try:
            separate_captions_by_gender(folder_name)
            processed_count += 1
        except Exception as e:
            # 捕获并记录处理单个文件夹时的异常，但不中断整个循环
            print(f"致命错误：处理文件夹 {folder_name} 时发生异常：{e}")
            
    print(f"\n--- 批量处理完成 ---")
    print(f"总共处理了 {processed_count} 个文件夹。")