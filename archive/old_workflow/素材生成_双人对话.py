# =============================================================================
# 通过Python调用ComfyUI + GPT-SoVITS 批量图像+音频生成脚本 (V3：音频分男女文件夹)
# 核心变化：TTS 音频根据 'gender' 字段分别保存到 "男音频" 和 "女音频" 文件夹。
# =============================================================================

# ========== 标准库与第三方模块导入 ==========
import os
import sys
import json
import time
import random
import shutil
import socket
import requests
import winsound
import subprocess
from datetime import datetime
from gradio_client import Client
from gradio_client.utils import handle_file
from pydub import AudioSegment
from typing import Dict, Any, List
# ============================================


###############################################################################
# ========================= 全局配置区域 (已简化) ===============================

# 每天需要改的只有子文件夹名
TARGET_SUBDIRS = ["32一背景"] # 要处理的子文件夹名称列表（示例） ,"0哲学引论"
 
# 路径配置
BASE_ROOT = r"V:\Default\Desktop\投稿视频\5中国古代科学哲学"  # 根目录路径
JSON_FILENAME = "prompt.json"  # 每个子文件夹内用于描述任务的 JSON 文件名

# ComfyUI 配置
COMFYUI_HOST = "http://localhost"  # comfyui本地地址
COMFYUI_PORT = 8000  # comfyui端口
COMFYUI_URL = f"{COMFYUI_HOST}:{COMFYUI_PORT}"  # comfyui链接
COMFYUI_OUTPUT_DIR = r"V:\ComfyUI\output"  # comfyui生成的图片获取位置

# GPT-SoVITS 路径
GPT_SOVITS_ROOT = r"V:\Default\Desktop\AI\GPT-SoVITS-v2pro-20250604"  # GPT-SoVITS 根目录
PYTHON_EXECUTABLE = os.path.join(GPT_SOVITS_ROOT, "runtime", "python.exe")  # GPT-SoVITS 解释器
INFERENCE_SCRIPT = os.path.join(GPT_SOVITS_ROOT, "GPT_SoVITS", "inference_webui.py")  # GPT-SoVITS 推理窗口

# TTS 配置
TTS_HOST = "http://localhost"  # GPT-SoVITS本地地址
TTS_PORT = 9872  # GPT-SoVITS端口
TTS_URL = f"{TTS_HOST}:{TTS_PORT}"  # GPT-SoVITS链接
TTS_MODEL_LOAD_WAIT = 3  # 模型切换后等待秒数 (略微增加等待时间确保加载完成)
TTS_TIMEOUT = 90.0  # 启动 Gradio 最大等待时间

# TTS 推理参数设置
TTS_PROMPT_LANG = "中文"  # 参考音频语言
TTS_TEXT_LANG = "中文"  # 生成音频语言  中英混合

# ========================= 统一角色参数配置 ============================
# Key: "0" 对应 剑灵(JL/女性); Key: "1" 对应 齐静春(QJC/男性)
ROLE_CONFIG = {
    "0": { # 剑灵 (JL) - 女性
        "name": "剑灵 (女性)",
        "gpt_model": r"GPT_weights_v2ProPlus/JL_v2ProPlus-e40.ckpt",
        "sovits_model": r"SoVITS_weights_v2ProPlus/JL_v2ProPlus_e20_s520.pth",
        "ref_wav": r"V:\Default\Desktop\AI\GPT-SoVITS-v2pro-20250604\cankao\我要加快速度，争取在六十年之内，将老剑条恢复成最开始的相貌。.wav",
        "prompt_text": "我要加快速度，争取在六十年之内，将老剑条恢复成最开始的相貌。",
        "speed": 1.15,
        "pause_second": 0.1,
        "comfyui_workflow": r"V:\Default\Desktop\投稿视频\0预设\nunchaku_qwen_image.json", 
        "image_size": (720, 960) # 剑灵尺寸
    },
    "1": { # 齐静春 (QJC) - 男性
        "name": "齐静春 (男性)",
        "gpt_model": r"GPT_weights_v2ProPlus/QJC_v2ProPlus-e40.ckpt",
        "sovits_model": r"SoVITS_weights_v2ProPlus/QJC_v2ProPlus_e20_s860.pth",
        "ref_wav": r"V:\Default\Desktop\AI\GPT-SoVITS-v2pro-20250604\cankao\有些事情我难辞其咎，必须要给你一个交代，今天，我便借这机会。.wav",
        "prompt_text": "有些事情我难辞其咎，必须要给你一个交代，今天，我便借这机会。",
        "speed": 1.4,
        "pause_second": 0.3,
        "comfyui_workflow": r"V:\Default\Desktop\投稿视频\0预设\flux_发光线条.json", 
        "image_size": (1280, 720) # 齐静春尺寸
    }
}
# 定义图片生成的默认配置（统一使用 QJC 的配置作为默认参考）
DEFAULT_COMFYUI_WORKFLOW_PATH = ROLE_CONFIG["1"]["comfyui_workflow"]  #生图工作流
DEFAULT_IMAGE_SIZE = ROLE_CONFIG["1"]["image_size"]  #图片尺寸
 

# 其他设置
COMFYUI_GENERATE_SWITCH = 0  # 图片生成开关 0开1关
TTS_GENERATE_SWITCH = 0  # 音频生成开关 0开1关

VIDEO_FRAME_RATE = 25   # 音频时间线帧率
AVG_TIME_PER_PAIR = 120 # 预计每对图片+音频的平均耗时(秒)
Image_generation_waiting_time = 600 # 图片生成等待时长（秒）
Interval_Delay = 0      # 间隔延时（毫秒）
Ending_duration = 5000  # 结尾延时（毫秒）
SHUTDOWN_DELAY = 600  # 关机等待时长（秒），10分钟
LOG_DIR = r"V:\Default\Desktop\投稿视频\0杂项\0日志"  # 日志目录路径
ALERT_SOUND_PATH = r"V:\Default\Desktop\投稿视频\0预设\不凡前奏.wav"  # 提示音
_tts_process = None  # 存储启动的 TTS 子进程对象
# =============================================================================
###############################################################################


# ========== 工具函数区域 (保持不变) ==========
def play_alert_sound():
    if os.path.exists(ALERT_SOUND_PATH):
        winsound.PlaySound(ALERT_SOUND_PATH, winsound.SND_FILENAME)

def ms_to_timecode(ms: int) -> str:
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    frames = (ms % 1000) * VIDEO_FRAME_RATE // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

def seconds_to_hms(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours}h {minutes}m {secs}s"

def wait_for_port_closed(host: str, port: int, timeout: float = 10.0):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                time.sleep(0.5)
        except (OSError, ConnectionRefusedError):
            return
    raise TimeoutError(f"端口 {port} 在 {timeout:.1f}s 内未关闭")

def is_process_running(process):
    return process is not None and process.poll() is None
# ============================================


# ========== ComfyUI 图像生成 (保持不变) ==========
# 加载 prompt.json 工作流文件
def load_workflow(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            print(f"→ 加载工作流文件: {path}")
            return json.load(f)
    raise FileNotFoundError(f"未找到工作流 JSON 文件: {path}")


# 根据提示词生成图像并保存到指定目录
def generate_and_save_image(prompt: str, workflow: Dict[str, Any], output_dir: str, idx: int, image_size: tuple):
    workflow_copy = json.loads(json.dumps(workflow))
    
    ksampler = next(k for k, v in workflow_copy.items() if v["class_type"] == "KSampler")
    clip = next(k for k, v in workflow_copy.items() if v["class_type"] == "CLIPTextEncode")

    # 设置提示词与随机种子
    workflow_copy[ksampler]["inputs"]["seed"] = random.randint(10**10,10**15)
    workflow_copy[clip]["inputs"]["text"] = prompt

    # 统一图像尺寸
    for node in workflow_copy.values():
        if "width" in node["inputs"] and "height" in node["inputs"]:
            node["inputs"]["width"], node["inputs"]["height"] = image_size

    # 发送生成请求到ComfyUI
    resp = requests.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow_copy})
    pid = resp.json()["prompt_id"]
    # print("prompt_id为："+pid)

    # 等待任务完成
    for _ in range(Image_generation_waiting_time):
        status = requests.get(f"{COMFYUI_URL}/history/{pid}").json()
        if pid in status and "outputs" in status[pid]:
            break
        time.sleep(1)
    else:
        raise TimeoutError("图像生成超时")

    # 提取并保存图像
    node_id = next(k for k, v in workflow_copy.items() if v["class_type"] == "SaveImage")
    img_info = status[pid]["outputs"][node_id]["images"][0]
    src = os.path.join(COMFYUI_OUTPUT_DIR,img_info["subfolder"] , img_info["filename"])
    
    # 保持原图质量，使用 shutil.copy2，后缀为 .png
    dst = os.path.join(output_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx:03d}.png")
    shutil.copy2(src, dst)
    print(f"[图片 {idx}] 保存成功: {dst}")
# ============================================



# ========== GPT-SoVITS 启动与关闭 (保持不变) ==========
# 启动 GPT-SoVITS
def start_tts_service(timeout: float = TTS_TIMEOUT):
    global _tts_process
    
    stop_tts_service()

    print("→ 启动 TTS 服务 ...")
    os.chdir(GPT_SOVITS_ROOT)
    
    env = os.environ.copy()
    env["PATH"] = f"{GPT_SOVITS_ROOT}\\runtime;{env['PATH']}"
    env["language"] = "zh_CN"
    
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    
    try:
        _tts_process = subprocess.Popen(
            [PYTHON_EXECUTABLE, "-s", INFERENCE_SCRIPT, "zh_CN"],
            env=env,
            creationflags=creation_flags
        )
    except Exception as e:
        raise RuntimeError(f"启动TTS服务失败: {e}")

    start = time.time()
    while time.time() - start < timeout:
        if is_process_running(_tts_process):
            try:
                if requests.get(TTS_URL, timeout=1).status_code == 200:
                    print("→ Gradio 界面已响应，等待模型加载 ...")
                    break
            except (requests.exceptions.RequestException, OSError):
                pass
        else:
            raise RuntimeError("TTS 启动失败：子进程提前退出。")
        time.sleep(0.5)
    else:
        stop_tts_service()
        raise TimeoutError(f"TTS服务在{timeout}秒内未启动")

    print(f"→ 等待模型加载 {TTS_MODEL_LOAD_WAIT} 秒 ...")
    time.sleep(TTS_MODEL_LOAD_WAIT)

    # 简单测试接口可用性（使用 QJC 的配置作为默认测试）
    try:
        test_client = Client(TTS_URL)
        test_client.predict(
            ref_wav_path=handle_file(ROLE_CONFIG["1"]["ref_wav"]),
            prompt_text=ROLE_CONFIG["1"]["prompt_text"],
            prompt_language=TTS_PROMPT_LANG,
            text="测试",
            text_language=TTS_TEXT_LANG,
            speed=ROLE_CONFIG["1"]["speed"],
            pause_second=ROLE_CONFIG["1"]["pause_second"],
            api_name="/get_tts_wav")
        print("→ ✅ TTS 接口已就绪。")
    except Exception as e:
        stop_tts_service()
        raise RuntimeError(f"TTS 接口测试失败，请检查模型路径或GPT-SoVITS运行状态：{e}")


# 关闭 GPT-SoVITS 服务 (保持不变)
def stop_tts_service():
    global _tts_process
    
    if is_process_running(_tts_process):
        print("→ 正在关闭 TTS 服务 ...")
        
        try:
            _tts_process.terminate()
            try:
                _tts_process.wait(timeout=5)
                print("→ TTS 进程已正常终止。")
            except subprocess.TimeoutExpired:
                _tts_process.kill()
                _tts_process.wait()
                print("→ TTS 进程已被强制终止。")
                
            for attempt in range(1, 11):
                try:
                    with socket.create_connection((TTS_HOST, TTS_PORT), timeout=1):
                        print(f"→ 端口仍在使用，等待中 ({attempt}/10)...")
                        time.sleep(1)
                except (OSError, ConnectionRefusedError):
                    print("→ ✅ 端口已关闭。")
                    break
            else:
                print("警告：端口未完全关闭，但已终止进程。可能需要手动检查。")
                
        except Exception as e:
            print(f"错误：关闭 TTS 服务时发生异常: {e}")
        finally:
            _tts_process = None
    else:
        print("→ TTS 服务未运行。")
# ============================================


# ========== GPT-SoVITS 音频生成 (保持不变) ==========
# 生成并保存音频，返回音频时长（毫秒）
def generate_and_save_audio(client: Client, text: str, output_dir: str,output_caption_dir: str, idx: int, config: Dict[str, Any]) -> int:
    result = client.predict(
        ref_wav_path=handle_file(config["ref_wav"]),
        prompt_text=config["prompt_text"],
        prompt_language=TTS_PROMPT_LANG,
        text=text,
        text_language=TTS_TEXT_LANG,
        speed=config["speed"],
        pause_second=config["pause_second"],
        api_name="/get_tts_wav"
    )
    
    # 修复BUG：将mp3改为wav，确保保存原始音频格式
    # 使用 shutil.copy2 确保元数据和文件完整性
    # 注意：output_dir 现在是动态的 (男音频 或 女音频)
    dst1 = os.path.join(output_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx:03d}.wav")
    dst2 = os.path.join(output_caption_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx:03d}.wav")
    shutil.copy2(result, dst1) 
    shutil.copy2(result, dst2)
    print(f"[音频 {idx}] 保存成功: {dst1}")
    
    # 返回音频时长，用于生成时间线
    return len(AudioSegment.from_file(dst1))
# ============================================


# ========== 单个子目录任务流程 (核心改动 V3) ==========
# 处理一个子目录内的图像+音频任务，返回总耗时
def process_folder(subdir: str, error_logs: List[str], comfyui_generate_switch: int, tts_generate_switch: int) -> float:  
    # 文件路径预设
    base = os.path.join(BASE_ROOT, subdir)
    image_dir = os.path.join(base, "图片")
    other_dir = os.path.join(base, "其他")
    
    # 【改动点 1】 定义区分男女声的音频目录
    male_audio_dir = os.path.join(base, "男音频") # 齐静春 (Gender 1)
    female_audio_dir = os.path.join(base, "女音频") # 剑灵 (Gender 0)
    total_audio_dir = os.path.join(base, "音频") # 剑灵 (Gender 0)
    male_caption_dir = os.path.join(base, "男字幕") # 齐静春 (Gender 1)
    female_caption_dir = os.path.join(base, "女字幕") # 剑灵 (Gender 0)
    
    # 创建必要的目录
    os.makedirs(other_dir, exist_ok=True)  #其他
    if comfyui_generate_switch == 0:
        os.makedirs(image_dir, exist_ok=True)  #图片
    if tts_generate_switch == 0:
        # 【改动点 2】 创建男女音频文件夹
        os.makedirs(male_audio_dir, exist_ok=True)  #男音频
        os.makedirs(female_audio_dir, exist_ok=True)  #女音频
        os.makedirs(total_audio_dir, exist_ok=True)  #音频
        os.makedirs(male_caption_dir, exist_ok=True)  #男字幕
        os.makedirs(female_caption_dir, exist_ok=True)  #女字幕

    # 读取prompt.json
    json_path = os.path.join(base, JSON_FILENAME)
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise IOError(f"读取或解析 {JSON_FILENAME} 失败: {e}")

    # 提取三个同步列表
    image_prompts = [d.get("image_prompt") for d in data] if comfyui_generate_switch == 0 else []
    audio_texts = [d.get("caption") for d in data] if tts_generate_switch == 0 else []
    gender_distinction = [d.get("gender") for d in data] if tts_generate_switch == 0 else [] 

    # 检查列表长度是否一致
    if len(audio_texts) != len(gender_distinction):
        raise ValueError("prompt.json 中 'caption' 和 'gender' 字段数量不匹配，请检查JSON结构。")

    # 输出任务信息
    print(f"===== 开始处理文件夹：{subdir} =====")
    info_parts = []
    if comfyui_generate_switch == 0:
        info_parts.append(f"生成图片 {len(image_prompts)} 张")
    else:
        print("===== 不生成图片 =====")
    if tts_generate_switch == 0:
        info_parts.append(f"生成音频 {len(audio_texts)} 段 (分男女文件夹)")
    else:
        print("===== 不生成音频 =====")
    
    print(f"→ 共需{', '.join(info_parts)}")

    # 图像生成 (使用默认配置)
    img_time = 0
    if comfyui_generate_switch == 0:
        img_start = time.time()
        workflow = load_workflow(DEFAULT_COMFYUI_WORKFLOW_PATH)
        for i, prompt in enumerate(image_prompts, 1):
            try:
                # 传入默认图片尺寸
                generate_and_save_image(prompt, workflow, image_dir, i, DEFAULT_IMAGE_SIZE)
            except Exception as e:
                error_msg = f"[图片错误 {i}] 文件夹 “{subdir}”: {e}"
                print(error_msg)
                error_logs.append(error_msg)
        img_time = time.time() - img_start

    # 音频生成 (核心动态切换逻辑)
    audio_time = 0
    if tts_generate_switch == 0:
        audio_start = time.time()
        start_tts_service()
        client = Client(TTS_URL)
        time_markers = []
        total_ms = 0
        
        last_gender = None # 跟踪上一个使用的性别
        
        # 生成音频文件和marker
        try:
            # 循环遍历文本和性别
            for i, (text, gender) in enumerate(zip(audio_texts, gender_distinction), 1):
                try:
                    # 1. 检查和获取当前角色配置
                    if gender is None or gender not in ROLE_CONFIG:
                        raise ValueError(f"第 {i} 段音频缺少或性别 '{gender}' 无效。")
                        
                    current_config = ROLE_CONFIG[gender]
                    
                    # 2. 动态切换模型 (效率优化点：只有在性别变化时才切换)
                    if gender != last_gender:
                        print(f"→ [TTS 切换] 切换模型到：{current_config['name']}")
                        
                        # 切换GPT模型
                        client.predict(gpt_path=current_config["gpt_model"], api_name="/change_gpt_weights")
                        
                        # 切换SoVITS模型
                        client.predict(
                            sovits_path=current_config["sovits_model"],
                            prompt_language="中文",
                            text_language="中英混合",
                            api_name="/change_sovits_weights")
                        
                        last_gender = gender # 更新上一个使用的性别
                        time.sleep(TTS_MODEL_LOAD_WAIT) # 切换后等待模型加载
                    
                    # 3. 【改动点 3】 确定输出目录并生成音频
                    if gender == "1":
                        output_dir = male_audio_dir
                        output_caption_dir = male_caption_dir
                    elif gender == "0":
                        output_dir = female_audio_dir
                        output_caption_dir = female_caption_dir
                    else:
                         raise ValueError(f"内部错误：性别值 {gender} 未知。")
                         
                    duration = generate_and_save_audio(client, text, output_dir,output_caption_dir, i, current_config)  
                    #保存音频到“男/女音频”文件夹
                    #同时保存音频到“男/女字幕”，免得每次都复制
                    #不对，这nm是生成的两个完全不一样的文件，generate_and_save_audio不只是保存，是重新运行后保存，艹,所以修改函数吧

                    time_markers.append(ms_to_timecode(total_ms))
                    total_ms += duration
                except Exception as e:
                    import traceback
                    error_msg = f"[音频错误 {i}] 文件夹“ {subdir}” ({current_config.get('name', '未知')}) : {e}\n" + "".join(traceback.format_exception(*sys.exc_info()))
                    print(error_msg)
                    error_logs.append(error_msg)
        finally:
            stop_tts_service() # 确保关闭TTS服务

        # 保存时间线 marker.txt
        if time_markers:
            time_markers.append(ms_to_timecode(total_ms + Ending_duration))
            if len(time_markers) >= 2:
                # 保持时间码处理逻辑不变
                def timecode_to_ms(tc: str) -> int:
                    h, m, s, f = map(int, tc.split(':'))
                    total_seconds = h * 3600 + m * 60 + s + f / VIDEO_FRAME_RATE
                    return int(total_seconds * 1000)
                
                last_start_ms = timecode_to_ms(time_markers[-2]) + Interval_Delay
                last_end_ms = timecode_to_ms(time_markers[-1]) + Interval_Delay
                time_markers[-2] = ms_to_timecode(last_start_ms)
                time_markers[-1] = ms_to_timecode(last_end_ms)

            marker_path = os.path.join(other_dir, "marker.txt")
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write("\n".join(time_markers))
            print(f"[时间线] 已保存：{marker_path}")

        audio_time = time.time() - audio_start

    # 总耗时计算
    total_time = img_time + audio_time
    print(f"===== {subdir} 完成，总耗时: {seconds_to_hms(total_time)} =====\n")
    return total_time
# ============================================


# ========== 主程序入口 (保持不变) ==========
if __name__ == "__main__":
    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)
    
    folder_count = len(TARGET_SUBDIRS)
    folder_names_str = ", ".join([f"“{folder}”" for folder in TARGET_SUBDIRS])
    log_filename = f"{folder_count}_"+"+".join(TARGET_SUBDIRS) + f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    log_path = os.path.join(LOG_DIR, log_filename)
    
    # 日志记录器（保持不变）
    class Logger:
        def __init__(self, log_path):
            self.terminal = sys.stdout
            self.log = open(log_path, "a", encoding="utf-8")
            sys.stdout = self
            sys.stderr = self
        
        def write(self, message):
            self.terminal.write(message)
            self.log.write(message)
            self.log.flush()
        
        def flush(self):
            self.terminal.flush()
            self.log.flush()
        
        def __del__(self):
            sys.stdout = self.terminal
            sys.stderr = self.terminal
            self.log.close()
    
    # 初始化日志记录器
    logger = Logger(log_path)
    print(f"→ 日志文件已创建: {log_path}")
    print(f"需处理的文件夹有{folder_count}个，分别为{folder_names_str}")
    
    # 检查子文件夹是否存在和JSON文件有效性（保持不变）
    try:
        missing_folders = []
        missing_json_folders = []
        for folder in TARGET_SUBDIRS:
            folder_path = os.path.join(BASE_ROOT, folder)
            if not os.path.exists(folder_path):
                missing_folders.append(folder)
            else:
                json_path = os.path.join(folder_path, JSON_FILENAME)
                if not os.path.exists(json_path):
                    missing_json_folders.append(folder)
                else:
                    try:
                        with open(json_path, encoding="utf-8") as f:
                            data = json.load(f)
                            # 额外检查是否有 'gender' 字段
                            if TTS_GENERATE_SWITCH == 0 and not all("gender" in d for d in data):
                                raise ValueError("JSON中缺少'gender'字段")
                    except Exception:
                        missing_json_folders.append(folder)

        if missing_folders:
            print("以下文件夹不存在，请检查：")
            for folder in missing_folders:
                print(f"- {folder}")
            sys.exit(1)
        
        if missing_json_folders:
            print("以下文件夹中的prompt.json文件不存在、无法正常读取或格式不正确，请检查：")
            for folder in missing_json_folders:
                print(f"- {folder}")
            sys.exit(1)
        
        # 一次性列举所有子文件夹需要处理的图片和音频数量
        total_images = 0
        total_audios = 0
        for folder in TARGET_SUBDIRS:
            base = os.path.join(BASE_ROOT, folder)
            json_path = os.path.join(base, JSON_FILENAME)
            data = json.load(open(json_path, encoding="utf-8"))
            total_images += len([d["image_prompt"] for d in data])
            total_audios += len([d["caption"] for d in data])
            print(f"文件夹 {folder} 需要生成 {len([d['image_prompt'] for d in data])} 张图片和 {len([d['caption'] for d in data])} 段音频")
        
        print(f"\n总共需要生成 {total_images} 张图片和 {total_audios} 段音频")
        estimated_seconds = total_images * AVG_TIME_PER_PAIR
        print(f"预计总耗时: {seconds_to_hms(estimated_seconds)}")

        total_time = 0.0
        start = time.time()
        results = []
        error_logs = []
        
        # 执行素材生成任务
        try:
            for folder in TARGET_SUBDIRS:
                try:
                    # 直接调用 process_folder
                    t = process_folder(folder, error_logs, COMFYUI_GENERATE_SWITCH, TTS_GENERATE_SWITCH)
                    results.append((folder, t))
                    total_time += t
                except Exception as e:
                    import traceback
                    error_msg = f"[致命错误] 处理 {folder} 时失败：{str(e)}\n"
                    error_msg += "".join(traceback.format_exception(*sys.exc_info()))
                    print(error_msg)
                    error_logs.append(error_msg)
                    play_alert_sound()
                    sys.exit(1)

            print("\n===== 所有任务完成 =====")
            for name, t in results:
                print(f"{name}: {seconds_to_hms(t)}")
            print(f"总耗时：{seconds_to_hms(time.time() - start)}")
            play_alert_sound()

            print("------------------------")
            if error_logs:
                print("运行中出现过的错误为：")
                for error in error_logs:
                    print(error)
            else:
                print("此次运行无错误")
            print("------------------------")

        finally:
            # 日志收尾
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()
            with open(log_path, 'w', encoding='utf-8') as f:
                if error_logs:
                    f.write("运行有错误\n\n")
                    f.write(f"总耗时：{seconds_to_hms(time.time() - start)}\n\n")
                else:
                    f.write("此次运行无错误\n")
                    f.write(f"总耗时：{seconds_to_hms(time.time() - start)}\n\n")
                f.write(content)
            
            # 确保程序结束时关闭TTS服务
            stop_tts_service()
            print("程序执行完毕，输出已保存。")

            # 自动关机逻辑
            print(f"\n[警告] 系统将在 {SHUTDOWN_DELAY//60} 分钟后自动关机。")
            print("按回车键立即结束程序（取消关机）...")
            try:
                subprocess.Popen(['shutdown', '/s', '/f', '/t', str(SHUTDOWN_DELAY)])
                input()
                subprocess.run(['shutdown', '/a'], check=True)
                print("程序已结束，未执行关机。")
            except:
                print("关机流程已终止。")
    
    except Exception as e:
        import traceback
        error_msg = f"[主程序错误] 发生未处理的异常：{str(e)}\n"
        error_msg += "".join(traceback.format_exception(*sys.exc_info()))
        print(error_msg)
        play_alert_sound()
        sys.exit(1)
# ============================================