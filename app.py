import uvicorn
import os
import tempfile
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydub import AudioSegment  # 用于格式转换

# 引入预测器
from predictor import AASISTPredictor

# ==========================================================
# 配置路径
# ==========================================================
MODEL_PATH = "epoch_45_0.441.pth" 
CONFIG_PATH = "config_standalone_eval.json"
THRESHOLD = 1.510585 
# ==========================================================

# --- [关键] 配置 Pydub 使用本地 ffmpeg ---
# 检查当前目录下是否有 ffmpeg.exe，如果有，指定给 pydub
current_dir = os.path.dirname(os.path.abspath(__file__))
local_ffmpeg = os.path.join(current_dir, "ffmpeg.exe")
local_ffprobe = os.path.join(current_dir, "ffprobe.exe")

if os.path.exists(local_ffmpeg):
    AudioSegment.converter = local_ffmpeg
    AudioSegment.ffprobe = local_ffprobe
    print(f"检测到本地 FFmpeg，已启用: {local_ffmpeg}")
else:
    print("警告: 未在当前目录检测到 ffmpeg.exe。如果系统未安装 FFmpeg，.m4a 格式将无法处理。")
# ----------------------------------------

if not os.path.exists(MODEL_PATH) or not os.path.exists(CONFIG_PATH):
    print("错误: 找不到模型或配置文件。")
    exit()

app = FastAPI(title="AASIST 语音伪造检测 (批量版-优化)")

print("正在加载模型...")
predictor = AASISTPredictor(
    model_path=MODEL_PATH,
    config_path=CONFIG_PATH,
    threshold=THRESHOLD
)
print("模型加载完毕。")

@app.post("/predict/")
async def predict_audio_batch(files: List[UploadFile] = File(...)):
    """
    批量处理音频文件，使用批处理加速推理
    """
    if not files:
        return []
    
    # 第一阶段：文件保存和格式转换（可以并行处理）
    file_info_list = []  # 存储 (原始文件名, 临时文件路径, 转换后的wav路径)
    temp_files_to_cleanup = []  # 存储所有需要清理的临时文件
    
    print(f"收到 {len(files)} 个文件，开始处理...")
    
    # 处理所有文件的上传和格式转换
    for file in files:
        temp_input_path = None
        temp_wav_path = None
        
        try:
            # 1. 保存用户上传的原始文件
            file_ext = os.path.splitext(file.filename)[1].lower()
            if not file_ext:
                file_ext = ".temp" 

            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                content = await file.read()
                temp_file.write(content)
                temp_input_path = temp_file.name
            
            # 2. 格式转换逻辑
            target_file_path = temp_input_path
            
            if file_ext != ".wav":
                print(f"正在转换格式: {file.filename} -> wav")
                # 创建一个临时的 wav 文件名
                temp_wav_path = temp_input_path + ".converted.wav"
                
                # 使用 pydub 加载并导出为 wav
                audio = AudioSegment.from_file(temp_input_path)
                audio.export(temp_wav_path, format="wav")
                
                # 将目标路径指向这个新的 wav 文件
                target_file_path = temp_wav_path
            
            # 记录文件信息
            file_info_list.append({
                "filename": file.filename,
                "file_path": target_file_path,
                "temp_input": temp_input_path,
                "temp_wav": temp_wav_path
            })
            
            # 记录需要清理的文件
            temp_files_to_cleanup.append(temp_input_path)
            if temp_wav_path:
                temp_files_to_cleanup.append(temp_wav_path)
                
        except Exception as e:
            print(f"文件 {file.filename} 处理出错: {e}")
            # 记录错误文件
            file_info_list.append({
                "filename": file.filename,
                "file_path": None,
                "error": f"文件处理失败: {str(e)}"
            })
            # 清理已创建的临时文件
            if temp_input_path and os.path.exists(temp_input_path):
                try:
                    os.remove(temp_input_path)
                except:
                    pass
    
    # 第二阶段：批量推理
    results = []
    
    # 分离有效文件和错误文件
    valid_files = [info for info in file_info_list if info.get("file_path") is not None]
    error_files = [info for info in file_info_list if info.get("file_path") is None]
    
    # 批量推理有效文件
    if valid_files:
        valid_file_paths = [info["file_path"] for info in valid_files]
        print(f"开始批量推理 {len(valid_file_paths)} 个文件...")
        
        # 调用批量预测方法
        pred_results = predictor.predict_batch(valid_file_paths)
        
        # 组装结果
        for i, file_info in enumerate(valid_files):
            pred_result = pred_results[i] if i < len(pred_results) else {"error": "预测结果缺失"}
            
            results.append({
                "filename": file_info["filename"],
                "result_label": pred_result.get("label", "错误"),
                "score": pred_result.get("score", 0),
                "is_bonafide": pred_result.get("label") == "真实",
                "error": pred_result.get("error", None)
            })
    
    # 添加错误文件的结果
    for file_info in error_files:
        results.append({
            "filename": file_info["filename"],
            "result_label": "错误",
            "score": 0,
            "is_bonafide": False,
            "error": file_info.get("error", "未知错误")
        })
    
    # 第三阶段：清理所有临时文件
    print("清理临时文件...")
    for temp_file_path in temp_files_to_cleanup:
        try:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        except Exception as e:
            print(f"清理临时文件 {temp_file_path} 失败: {e}")
    
    print(f"处理完成，共处理 {len(results)} 个文件")
    return results

@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "错误: 找不到 index.html。"

if __name__ == "__main__":
    print("启动服务器，访问 http://127.0.0.1:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)