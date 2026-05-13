# AstrBot TouchGal + Bangumi 插件

从 touchgal.top 搜索 Galgame 资源，支持 Bangumi 游戏信息查询。

## 命令

| 命令 | 说明 |
|------|------|
| `/gal 游戏名` | 搜索 touchgal，返回封面、详情和下载入口 |
| `/gal下载 游戏名` | 获取 touchgal 下载链接 |
| `/b 游戏名` | 搜索 Bangumi，返回多条结果，回复数字查看详情 |

## 安装

1. 将本插件文件夹放入 AstrBot 的 `data/plugins/` 目录
2. 在 AstrBot 的 Python 环境中安装依赖：
   ```bash
   pip install -r requirements.txt