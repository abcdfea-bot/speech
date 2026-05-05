import os
import secrets
import tempfile
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydub import AudioSegment
from starlette.middleware.sessions import SessionMiddleware

from db import (
    create_prediction_history,
    create_user,
    get_user_by_account,
    get_user_by_id,
    init_db,
    list_prediction_history,
    update_user_profile,
)
from predictor import AASISTPredictor
from schemas import AuthResponse, HistoryResponse, LoginRequest, MessageResponse, RegisterRequest, UpdateProfileRequest, UserProfile
from security import hash_password, verify_password

# ==========================================================
# Configuration
# ==========================================================
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "epoch_45_0.441.pth"
CONFIG_PATH = BASE_DIR / "config_standalone_eval.json"
THRESHOLD = 1.510585
SESSION_SECRET_PATH = BASE_DIR / ".session_secret"
SESSION_USER_KEY = "user_id"
MAX_UPLOAD_FILES = 20
MAX_UPLOAD_FILE_SIZE = 20 * 1024 * 1024
SESSION_HTTPS_ONLY = os.environ.get("APP_SESSION_HTTPS_ONLY", "false").strip().lower() == "true"
# ==========================================================

# --- [Critical] Configure pydub to use local ffmpeg ---
local_ffmpeg = BASE_DIR / "ffmpeg.exe"
local_ffprobe = BASE_DIR / "ffprobe.exe"

if local_ffmpeg.exists():
    AudioSegment.converter = str(local_ffmpeg)
    AudioSegment.ffprobe = str(local_ffprobe)
    print(f"Detected local FFmpeg: {local_ffmpeg}")
else:
    print("Warning: ffmpeg.exe was not found in the project directory. .m4a files may fail if FFmpeg is not installed.")
# ------------------------------------------------------

if not MODEL_PATH.exists() or not CONFIG_PATH.exists():
    print("Error: model or config file was not found.")
    raise SystemExit(1)

init_db()


def _load_session_secret() -> str:
    env_secret = os.environ.get("APP_SESSION_SECRET")
    if env_secret:
        return env_secret

    if SESSION_SECRET_PATH.exists():
        secret = SESSION_SECRET_PATH.read_text(encoding="utf-8").strip()
        if secret:
            return secret

    secret = secrets.token_urlsafe(32)
    SESSION_SECRET_PATH.write_text(secret, encoding="utf-8")
    return secret


SESSION_SECRET = _load_session_secret()

app = FastAPI(title="AASIST Speech Deepfake Detection")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR)), name="assets")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="speech_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
)

print("Loading model...")
predictor = AASISTPredictor(
    model_path=str(MODEL_PATH),
    config_path=str(CONFIG_PATH),
    threshold=THRESHOLD,
)
print("Model loaded.")


def _serialize_user_profile(user: dict) -> UserProfile:
    return UserProfile(
        id=user["id"],
        account=user["account"],
        username=user.get("username"),
        display_name=user.get("display_name"),
        phone=user.get("phone"),
        email=user.get("email"),
        created_at=user["created_at"],
        updated_at=user["updated_at"],
    )


def _get_session_user(request: Request) -> Optional[dict]:
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = get_user_by_id(int(user_id))
    if user is None:
        request.session.clear()
    return user


def _require_session_user(request: Request) -> dict:
    user = _get_session_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user


def _login_user(request: Request, user: dict) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = user["id"]


@app.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, request: Request):
    account = payload.account.strip()
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号不能为空")

    try:
        user = create_user(
            account=account,
            password_hash=hash_password(payload.password),
            username=payload.username,
            display_name=payload.display_name,
            phone=payload.phone,
            email=payload.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    _login_user(request, user)
    return {"message": "注册成功", "user": _serialize_user_profile(user)}


@app.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request):
    account = payload.account.strip()
    user = get_user_by_account(account)
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")

    _login_user(request, user)
    return {"message": "登录成功", "user": _serialize_user_profile(user)}


@app.post("/auth/logout", response_model=MessageResponse)
async def logout(request: Request):
    request.session.clear()
    return {"message": "已退出登录"}


@app.get("/auth/me", response_model=UserProfile)
@app.get("/profile", response_model=UserProfile)
async def current_user(request: Request):
    user = _require_session_user(request)
    return _serialize_user_profile(user)


@app.put("/auth/me", response_model=AuthResponse)
@app.put("/profile", response_model=AuthResponse)
async def update_current_user(payload: UpdateProfileRequest, request: Request):
    user = _require_session_user(request)
    password_hash = None
    if payload.new_password:
        if not payload.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="修改密码时必须填写当前密码")
        if not verify_password(payload.current_password, user["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前密码错误")
        password_hash = hash_password(payload.new_password)
    try:
        updated_user = update_user_profile(
            user_id=user["id"],
            display_name=payload.display_name,
            phone=payload.phone,
            email=payload.email,
            password_hash=password_hash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"message": "个人信息更新成功", "user": _serialize_user_profile(updated_user)}


@app.get("/history", response_model=HistoryResponse)
async def prediction_history(request: Request, limit: int = 50):
    user = _require_session_user(request)
    safe_limit = max(1, min(limit, 50))
    return {"items": list_prediction_history(user["id"], safe_limit)}


@app.post("/predict/")
async def predict_audio_batch(request: Request, files: List[UploadFile] = File(...)):
    """
    Batch process audio files while preserving the original prediction response shape.
    """
    if not files:
        return []
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"单次最多上传 {MAX_UPLOAD_FILES} 个文件")

    file_info_list = []
    temp_files_to_cleanup = []

    print(f"Received {len(files)} files. Starting processing...")

    for file in files:
        temp_input_path = None
        temp_wav_path = None

        try:
            file_ext = os.path.splitext(file.filename or "")[1].lower()
            if not file_ext:
                file_ext = ".temp"

            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                content = await file.read()
                if len(content) > MAX_UPLOAD_FILE_SIZE:
                    raise ValueError(f"文件大小超过限制，单文件最大支持 {MAX_UPLOAD_FILE_SIZE // (1024 * 1024)}MB")
                temp_file.write(content)
                temp_input_path = temp_file.name

            target_file_path = temp_input_path

            if file_ext != ".wav":
                print(f"Converting audio format: {file.filename} -> wav")
                temp_wav_path = temp_input_path + ".converted.wav"
                audio = AudioSegment.from_file(temp_input_path)
                audio.export(temp_wav_path, format="wav")
                target_file_path = temp_wav_path

            file_info_list.append(
                {
                    "filename": file.filename,
                    "file_path": target_file_path,
                    "temp_input": temp_input_path,
                    "temp_wav": temp_wav_path,
                }
            )

            temp_files_to_cleanup.append(temp_input_path)
            if temp_wav_path:
                temp_files_to_cleanup.append(temp_wav_path)

        except Exception as exc:
            print(f"File processing failed for {file.filename}: {exc}")
            file_info_list.append(
                {
                    "filename": file.filename,
                    "file_path": None,
                    "error": f"文件处理失败: {str(exc)}",
                }
            )
            if temp_input_path and os.path.exists(temp_input_path):
                try:
                    os.remove(temp_input_path)
                except OSError:
                    pass

    results = []
    valid_files = [info for info in file_info_list if info.get("file_path") is not None]
    error_files = [info for info in file_info_list if info.get("file_path") is None]

    if valid_files:
        valid_file_paths = [info["file_path"] for info in valid_files]
        print(f"Running batch inference on {len(valid_file_paths)} files...")
        pred_results = predictor.predict_batch(valid_file_paths)

        for index, file_info in enumerate(valid_files):
            pred_result = pred_results[index] if index < len(pred_results) else {"error": "预测结果缺失"}
            results.append(
                {
                    "filename": file_info["filename"],
                    "result_label": pred_result.get("label", "错误"),
                    "score": pred_result.get("score", 0),
                    "is_bonafide": pred_result.get("label") == "真实",
                    "error": pred_result.get("error"),
                }
            )

    for file_info in error_files:
        results.append(
            {
                "filename": file_info["filename"],
                "result_label": "错误",
                "score": 0,
                "is_bonafide": False,
                "error": file_info.get("error", "未知错误"),
            }
        )

    print("Cleaning up temporary files...")
    for temp_file_path in temp_files_to_cleanup:
        try:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        except Exception as exc:
            print(f"Failed to remove temp file {temp_file_path}: {exc}")

    current_user = _get_session_user(request)
    if current_user is not None:
        try:
            create_prediction_history(current_user["id"], results)
        except Exception as exc:
            print(f"Failed to persist prediction history for user {current_user['id']}: {exc}")

    print(f"Finished processing {len(results)} files.")
    return results


@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    index_path = BASE_DIR / "index.html"
    try:
        return index_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "错误: 找不到 index.html。"


if __name__ == "__main__":
    print("Starting server at http://127.0.0.1:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
