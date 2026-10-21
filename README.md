# 异人之下站点点赞

**识图点赞助手**是面向 Windows 10 / 11 的本地桌面程序，用于在“异人之下站点”的“小栈”帖子列表中识别空心点赞图标、点击并自动下滑。

## 下载和使用

在本仓库的 [Releases](https://github.com/lihua2233/yiren-zhixia-zhandian-dianzan/releases) 中下载 **识图点赞助手.exe**、**使用说明.txt** 和 **源码.zip**。直接运行 EXE，无需安装 Python。

1. 打开小程序的“小栈”列表，将窗口放到屏幕一侧。
2. 在助手里选择“异人之下站点”，点击“预览识别（不点击）”。绿色框应只圈住未点赞心形；不准确时先“框选空心赞”重新校准。
3. 设置本次目标数量和间隔，按需开启自动下滑，再点击“开始”。首次建议将目标设为 1，检查实际效果。
4. 运行时保留置顶进度小窗，显示确认数量、目标、用时和最新状态。保持小程序在前台，避免移动、缩放或遮挡窗口。
5. 按 **F8** 或点击小窗的“停止”随时停止。结束后恢复完整界面与日志。

完整步骤、计数规则和故障处理见 [使用说明](使用说明.txt)。

## 功能

- 自定义新增点赞目标：1–10000，默认 500。
- 自定义间隔：1.5–30 秒，默认 3 秒。
- 本地校准心形图标，识别预览不执行点击。
- 点击后检测新增红色或橙色像素才计数；彩色的已点赞图标不作为点击候选。
- 可选自动下滑，置顶进度窗自动避开目标窗口。
- 前台窗口变化、遮挡、无法确认变色或连续下滑无变化时停止。

每次开始从 0 计数。计数是界面的视觉确认，并非服务器回执；确认中途停止时，实际点赞数可能多于已确认数。

## 从源码运行

使用 64 位 Windows 和 Python 3.11：

```powershell
python -m pip install -r requirements.txt
python app.py
```

程序自带此前校准的图标，换电脑或更改页面缩放后请重新校准。校准及日志存放于 `%LOCALAPPDATA%\XiaozhanLikeAssistant`。

## 构建 EXE

```powershell
python -m pip install -r requirements-build.txt
./build.ps1
```

也可手动构建：

```powershell
$heartPath = (Resolve-Path ./heart.png).Path
$calibrationPath = (Resolve-Path ./calibration.json).Path
python -m PyInstaller --noconfirm --onefile --windowed --name XiaozhanLikeAssistant --add-data "$heartPath;." --add-data "$calibrationPath;." app.py
Copy-Item ./dist/XiaozhanLikeAssistant.exe ./dist/识图点赞助手.exe
```

## 验证

```powershell
python test_detection.py
```

6 项本地测试覆盖图标匹配、排除错误位置及已点赞图标、变色确认、Windows 输入结构、进度窗避让和空间不足保护。已检查实际页面识别、进度窗显示和停止后恢复界面，尚未验证完成 500 次真实点赞的全程运行。

程序仅使用本地截图识别和鼠标操作，不读取账号密码，不上传截图。运行依赖前台窗口，不支持后台、锁屏或遮挡运行。
