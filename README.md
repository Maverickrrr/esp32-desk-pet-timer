# 桌宠遥控定时组件

ESP32 创建 Furniture-ESP32 热点。手机通过浏览器设置两路每日定时，也可手动启停；设备持续供电并校时后，关闭网页仍按计划工作。网页用两只瞳孔的动画显示浇水状态。

## 硬件
FireBeetle 2 ESP32-E（经典 ESP32，4 MB）。GPIO2 驱动板载 D9 灯，GPIO5 驱动板载 RGB 灯。两颗灯用于演示两路输出。

## 部署
先在板上安装 MicroPython ESP32_GENERIC v1.28.0。首次刷写基础固件会涉及原有闪存，请先备份。固件与安装说明见 https://micropython.org/download/ESP32_GENERIC/ 。

以下命令在 Windows PowerShell 的仓库根目录执行。将 COM6 替换为本机开发板端口。
1. 运行 `Copy-Item board/wifi_settings.example.py board/wifi_settings.py`，在副本内设置自己的热点密码（8–63 个 ASCII 字符）。
2. 安装上传工具并复制文件：
```powershell
py -m pip install mpremote
py -m mpremote connect COM6 fs cp board/controller.py board/index.html board/wifi_settings.py board/main.py :/
py -m mpremote connect COM6 reset
```
3. 手机连 Furniture-ESP32，打开 http://192.168.4.1/ 。系统门户是否弹出取决于手机。重新上电后打开网页完成校时。

## 快速验收
打开补光通道，再停止，核对 D9 灯。给浇水通道设定下一分钟启动、持续一分钟，启用并保存；手机离开热点后观察板载 RGB 灯是否按时亮灭。

## 协作
日常从更新后的 develop 创建个人分支，推送后提交到 develop 的 Pull Request。
