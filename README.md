# 环境安装步骤
1、打开自己虚拟环境
2、文件内打开终端，pip install -r requirements.txt下载依赖
3、python app.py运行后端
4、http://127.0.0.1:8000登陆浏览器

# 安装依赖可能出现的问题：
问题：./app.py", line 1, in <module>
    import uvicorn
ModuleNotFoundError: No module named 'uvicorn'
解决方法：pip install "numpy<2" --only-binary=:all:
                  然后再：pip install -r requirements.txt
		再启动：python app.py