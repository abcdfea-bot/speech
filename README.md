# 中文语音克隆检测算法设计与系统实现

这是一个基于 FastAPI 和 AASIST 模型的中文语音克隆检测 Web 原型系统。系统支持用户注册登录、批量上传音频、自动格式转换、模型推理、检测结果展示和历史记录查询。

## 功能简介

- 单页 Web 前端，支持多文件上传和检测结果展示
- FastAPI 后端接口，负责认证、文件接收、音频预处理和推理调度
- AASIST 语音反欺骗模型，用于判断音频是真实语音还是伪造语音
- SQLite 本地数据库，用于保存用户信息和检测历史
- 支持 WAV 文件；安装 FFmpeg 后可处理 MP3、M4A 等常见音频格式

## 项目结构

```text
speech-load/
├── app.py                         # FastAPI 应用入口
├── db.py                          # SQLite 初始化与数据访问
├── predictor.py                   # AASIST 推理封装
├── schemas.py                     # API 请求与响应模型
├── security.py                    # 密码哈希与校验
├── config_standalone_eval.json    # 模型结构配置
├── index.html                     # 前端页面
├── logo.jpg                       # 前端页面图片资源
├── models/
│   ├── AASIST.py                  # AASIST 模型定义
│   ├── AASISTFullAttentionResidual.py
│   └── __init__.py
├── requirements.txt
└── README.md
```

## 运行前准备

### 1. Python 环境

建议使用 Python 3.10 或更高版本，并创建独立虚拟环境。

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

如果安装 PyTorch 较慢或需要 CUDA 版本，建议参考 PyTorch 官网选择与你的系统和显卡匹配的安装命令。

### 3. 准备模型权重

模型权重文件未随仓库上传。请将训练好的权重文件放到项目根目录，并命名为：

```text
epoch_45_0.441.pth
```

后端启动时会从 `app.py` 中的 `MODEL_PATH` 加载该文件。如果需要使用其他权重文件名，请同步修改 `app.py`。

### 4. 配置文件说明

`config_standalone_eval.json` 保存模型结构参数。文件开头的 `database_path`、`eval_trial_path` 和 `model_path` 主要用于离线评估脚本，GitHub 版本中默认留空，用来避免暴露本机数据集和权重路径。当前 Web 服务启动时实际使用的模型权重路径由 `app.py` 中的 `MODEL_PATH` 指定。

`model_config.architecture` 当前设置为 `AASISTFullAttentionResidual`，表示系统使用加入全注意力残差融合机制的改进版 AASIST 模型，对应源码文件为 `models/AASISTFullAttentionResidual.py`。

### 5. 准备 FFmpeg

如果只检测 WAV 文件，可以暂时不配置 FFmpeg。若需要上传 MP3、M4A 等格式，请安装 FFmpeg，或将以下两个文件放到项目根目录：

```text
ffmpeg.exe
ffprobe.exe
```

Windows 用户也可以将 FFmpeg 添加到系统环境变量。Linux/macOS 用户可通过系统包管理器安装 FFmpeg。

## 启动项目

```bash
python app.py
```

启动成功后，在浏览器访问：

```text
http://127.0.0.1:8000
```

首次运行时，系统会自动创建本地 SQLite 数据库 `app_data.db`，并生成会话密钥文件 `.session_secret`。这些文件属于本地运行数据，不应提交到 GitHub。

## 常用接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 返回前端页面 |
| `POST` | `/auth/register` | 用户注册 |
| `POST` | `/auth/login` | 用户登录 |
| `POST` | `/auth/logout` | 用户退出登录 |
| `GET` | `/auth/me` | 获取当前用户信息 |
| `PUT` | `/auth/me` | 更新当前用户信息 |
| `GET` | `/history` | 获取检测历史 |
| `POST` | `/predict/` | 批量上传音频并进行检测 |

## 环境变量

| 变量名 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_SESSION_SECRET` | 自动生成 | 生产环境建议显式设置，用于会话签名 |
| `APP_SESSION_HTTPS_ONLY` | `false` | 设置为 `true` 后，Session Cookie 仅通过 HTTPS 发送 |

## GitHub 上传说明

以下文件不建议提交到仓库，已写入 `.gitignore`：

- `.session_secret`
- `app_data.db`
- `__pycache__/`
- `*.pyc`
- `*.log`
- `*.pth`
- `ffmpeg.exe`
- `ffprobe.exe`
- `.vscode/`

模型权重建议通过 GitHub Releases、网盘链接或 Git LFS 管理，不建议直接提交到普通 Git 仓库。

## 常见问题

### 启动时报错找不到模型或配置

请确认项目根目录下存在：

```text
epoch_45_0.441.pth
config_standalone_eval.json
```

### 上传非 WAV 文件失败

请确认 FFmpeg 已安装，或项目根目录下存在 `ffmpeg.exe` 与 `ffprobe.exe`。

### 依赖安装失败

建议先升级 pip：

```bash
python -m pip install --upgrade pip
```

如果 PyTorch 安装失败，请使用 PyTorch 官网提供的安装命令单独安装，再执行：

```bash
pip install -r requirements.txt
```
