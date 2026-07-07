# PSB Template Workbench

本地图片模板工作台，用于把素材图放入模板图片位并导出长图。

运行：

```powershell
cd D:\psb-template-workbench
py -3.10 app.py
```

打开：

```text
http://127.0.0.1:8765
```

说明：

- 导入 PSD/PSB 后默认不自带图片位，可手动新增或点击“一键识别图片位”。
- 当前版本不依赖 Photoshop，使用模板合成图作为底图，再把素材按图片位坐标裁切覆盖。
- 如果需要保留 PSD 智能对象的蒙版、滤镜和高级混合效果，后续可以增加 Photoshop COM 导出后端。
