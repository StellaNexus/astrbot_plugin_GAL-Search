"""
TouchGal + Bangumi - AstrBot 插件
/gal 游戏名      → touchgal 搜索，返回多条结果供选择
回复数字         → 选择结果查看详情（含简介）
/gal下载 游戏名  → touchgal 获取下载链接，多结果可选
/b 游戏名        → bangumi 搜索，返回前5个结果供选择
回复数字         → 选择结果查看详情
"""
import json
import os
import re
import uuid
import tempfile
import time
import base64
import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter

try:
    from PIL import Image
    import pillow_avif
    HAS_AVIF = True
except ImportError:
    HAS_AVIF = False


@register(
    "astrbot_plugin_touchgal",
    "TouchGal+Bangumi",
    "gal搜资源 / gal下载 / b搜信息",
    "1.5.0",
)
class TouchGalPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._load_config()
        self.base_url = "https://www.touchgal.ink"
        self._tg_cache = {}
        self._tg_cache_type = {}
        self._bgm_cache = {}
        self.temp_dir = os.path.join(tempfile.gettempdir(), "astrbot_touchgal")
        os.makedirs(self.temp_dir, exist_ok=True)

        if HAS_AVIF:
            logger.info("图片转换依赖已就绪")
        else:
            logger.warning("Pillow 或 pillow-avif-plugin 未安装，封面将以文本链接形式发送")

    # ============ 数字选择（最高优先级） ============
    @filter.regex(r"^\d+$")
    async def number_select(self, event):
        user_id = event.get_sender_id()

        if user_id in self._tg_cache:
            cache_type = self._tg_cache_type.get(user_id, "search")
            if cache_type == "download":
                index = int(event.message_str.strip()) - 1
                async for result in self._tg_download_show(event, index):
                    yield result
                event.stop_event()
                return
            else:
                index = int(event.message_str.strip()) - 1
                async for result in self._tg_show_detail(event, index):
                    yield result
                event.stop_event()
                return

        if user_id in self._bgm_cache:
            index = int(event.message_str.strip()) - 1
            async for result in self._bgm_show_detail(event, index):
                yield result
            event.stop_event()
            return

    # ============ 配置加载 ============
    def _load_config(self):
        astr_cfg = getattr(self, "config", {}) or {}
        self._cookie = astr_cfg.get("touchgal_cookie", "")
        self.bangumi_key = astr_cfg.get("bangumi_api_key", "")

        if not self._cookie or not self.bangumi_key:
            config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
            if os.path.exists(config_path):
                try:
                    import yaml
                    with open(config_path, "r", encoding="utf-8") as f:
                        file_cfg = yaml.safe_load(f) or {}
                    if not self._cookie:
                        self._cookie = file_cfg.get("touchgal_cookie", "")
                    if not self.bangumi_key:
                        self.bangumi_key = file_cfg.get("bangumi_api_key", "")
                except ImportError:
                    pass

        if not self._cookie:
            logger.warning("TouchGal Cookie 未配置。")
        if not self.bangumi_key:
            logger.warning("Bangumi API Key 未配置。")

    # ============ Token 过期检测 ============
    def _check_token_expiry(self) -> str | None:
        try:
            token = None
            for part in self._cookie.split(";"):
                if "kun-galgame-patch-moe-token" in part:
                    token = part.split("=", 1)[1].strip()
                    break
            if not token:
                return None
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            data = json.loads(base64.b64decode(payload))
            exp = data.get("exp", 0)
            remaining = exp - int(time.time())
            days = remaining / 86400
            if days < 7:
                return f"\n⚠️ TouchGal 登录 Token 还剩 {days:.0f} 天过期，请重新登录后更新配置。"
        except Exception:
            pass
        return None

    # ============ 工具方法 ============

    def _tg_headers(self, referer=""):
        h = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "cache-control": "no-cache",
            "content-type": "text/plain;charset=UTF-8",
            "Cookie": self._cookie,
            "origin": "https://www.touchgal.ink",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": referer if referer else "https://www.touchgal.ink/search",
            "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36 Edg/148.0.0.0",
            "x-requested-with": "kun-fetch",
        }
        return h

    def _bgm_headers(self):
        return {
            "User-Agent": "AstrBot/1.0",
            "Authorization": f"Bearer {self.bangumi_key}",
        }

    async def _download_and_convert(self, url: str) -> str | None:
        if not HAS_AVIF:
            return None
        try:
            name = uuid.uuid4().hex
            tmp_path = os.path.join(self.temp_dir, f"{name}_tmp")
            jpg_path = os.path.join(self.temp_dir, f"{name}.jpg")

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    with open(tmp_path, "wb") as f:
                        f.write(await resp.read())

            img = Image.open(tmp_path)
            img.convert("RGB").save(jpg_path, "JPEG", quality=65)
            os.remove(tmp_path)
            return jpg_path
        except Exception as e:
            logger.error(f"图片处理失败: {e}")
            return None

    async def _tg_search(self, keyword: str) -> list:
        h = self._tg_headers(f"{self.base_url}/search")
        payload = {
            "queryString": json.dumps([{"type": "keyword", "mode": "include", "name": keyword}]),
            "limit": 5, "page": 1, "minRatingCount": 0,
            "searchOption": {"searchInIntroduction": False, "searchInAlias": True, "searchInTag": False},
            "selectedLanguage": "all", "selectedMonths": ["all"],
            "selectedPlatform": "all", "selectedType": "all",
            "selectedYears": ["all"], "sortField": "resource_update_time", "sortOrder": "desc",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/api/search", json=payload, headers=h) as resp:
                data = await resp.json()
                if isinstance(data, str):
                    return []
                return data.get("galgames", [])[:5]

    async def _tg_detail(self, unique_id: str) -> dict | None:
        h = self._tg_headers(f"{self.base_url}/{unique_id}")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/{unique_id}", headers=h) as resp:
                html = await resp.text()

        introduction = ""
        desc_match = re.search(r'<meta name="description" content="([^"]+)"', html)
        if desc_match:
            introduction = desc_match.group(1).replace("\\n", "\n").replace("&gt;", ">").replace("&lt;", "<")

        if not introduction:
            og_desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
            if og_desc_match:
                introduction = og_desc_match.group(1).replace("\\n", "\n").replace("&gt;", ">").replace("&lt;", "<")

        return {"introduction": introduction}

    async def _tg_resources(self, patch_id: int, unique_id: str) -> list:
        h = self._tg_headers(f"{self.base_url}/{unique_id}")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/api/patch/resource",
                params={"patchId": patch_id}, headers=h
            ) as resp:
                return await resp.json() if resp.status == 200 else []

    async def _bgm_fetch_detail(self, subject_id: int) -> dict | None:
        h = self._bgm_headers()
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.bgm.tv/v0/subjects/{subject_id}", headers=h) as resp:
                return await resp.json() if resp.status == 200 else None

    async def _bgm_search_list(self, keyword: str) -> list:
        h = self._bgm_headers()
        h["Content-Type"] = "application/json"
        payload = {"keyword": keyword, "sort": "rank", "filter": {"type": [4]}}
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.bgm.tv/v0/search/subjects", json=payload, headers=h) as resp:
                data = await resp.json()
                return data.get("data", [])[:5]

    def _parse_kw(self, msg: str, prefix: str) -> str:
        if msg.startswith(prefix + " "):
            return msg[len(prefix) + 1:].strip()
        elif msg.startswith(prefix):
            return msg[len(prefix):].strip()
        return ""

    def _send_cover_and_text(self, jpg_path: str | None, cover_url: str, text: str):
        chain = []
        if jpg_path:
            chain.append(Comp.Image(file=f"file:///{jpg_path}"))
        elif cover_url:
            chain.append(Comp.Plain(f"[封面] {cover_url}\n"))
        chain.append(Comp.Plain(text))
        return chain

    # ============ /gal ============
    @filter.command("gal")
    async def gal_search(self, event):
        if not self._cookie:
            yield event.plain_result("TouchGal Cookie 未配置，请联系管理员。")
            return

        keyword = self._parse_kw(event.message_str, "gal")
        if not keyword:
            yield event.plain_result("请输入游戏名称，例如：/gal 千恋万花")
            return

        if keyword.isdigit():
            async for result in self._tg_select(event, int(keyword)):
                yield result
            return

        results = await self._tg_search(keyword)
        if not results:
            yield event.plain_result(f"未找到与「{keyword}」相关的游戏。")
            return

        user_id = event.get_sender_id()
        self._tg_cache[user_id] = results
        self._tg_cache_type[user_id] = "search"

        lines = [f"TouchGal 找到 {len(results)} 个结果，回复数字查看详情：\n"]
        for i, r in enumerate(results):
            name = r.get("name", "")
            lines.append(f"{i+1}. {name}")

        yield event.plain_result("\n".join(lines))

    async def _tg_select(self, event, index: int):
        async for result in self._tg_show_detail(event, index - 1):
            yield result

    async def _tg_show_detail(self, event, index: int):
        user_id = event.get_sender_id()
        results = self._tg_cache.get(user_id, [])

        if index < 0 or index >= len(results):
            yield event.plain_result("序号无效，请重新搜索。")
            return

        game = results[index]
        unique_id = game.get("uniqueId", "")
        name = game.get("name", "")
        banner = game.get("banner", "")
        detail_url = f"{self.base_url}/{unique_id}"
        rating = game.get("averageRating", 0) or "暂无"
        view = game.get("view", 0)
        download = game.get("download", 0)
        platforms = " ".join(game.get("platform", []))
        languages = " ".join(game.get("language", []))

        detail_info = await self._tg_detail(unique_id)
        intro = ""
        if detail_info:
            intro = detail_info.get("introduction", "")
            if intro.startswith("游戏介绍"):
                intro = intro.replace("游戏介绍", "", 1).strip()

        text = f"{name}\n"
        text += f"详情：{detail_url}\n"
        text += f"评分：{rating} | 浏览：{view} | 下载：{download}\n"
        text += f"平台：{platforms}\n"
        text += f"语言：{languages}\n"
        if intro:
            text += f"\n{intro}\n"
        text += f"\n输入 /gal下载 {name} 获取下载链接"

        # Token 过期提醒
        expiry_warning = self._check_token_expiry()
        if expiry_warning:
            text += expiry_warning

        self._tg_cache.pop(user_id, None)
        self._tg_cache_type.pop(user_id, None)

        jpg_path = await self._download_and_convert(banner) if banner else None
        chain = self._send_cover_and_text(jpg_path, banner, text)
        yield event.chain_result(chain)

        if jpg_path and os.path.exists(jpg_path):
            try:
                os.remove(jpg_path)
            except Exception:
                pass

    # ============ /gal下载 ============
    @filter.command("gal下载")
    async def gal_download(self, event):
        if not self._cookie:
            yield event.plain_result("TouchGal Cookie 未配置，请联系管理员。")
            return

        keyword = self._parse_kw(event.message_str, "gal下载")
        if not keyword:
            yield event.plain_result("请输入游戏名称，例如：/gal下载 千恋万花")
            return

        if keyword.isdigit():
            async for result in self._tg_download_select(event, int(keyword)):
                yield result
            return

        games = await self._tg_search(keyword)
        if not games:
            yield event.plain_result(f"未找到与「{keyword}」相关的游戏。")
            return

        if len(games) == 1:
            game = games[0]
            resources = await self._tg_resources(game["id"], game["uniqueId"])
            if not resources:
                yield event.plain_result(f"「{game['name']}」暂无下载资源。")
                return

            lines = [f"{game['name']} 下载链接：\n"]
            for r in resources:
                ver = r.get("name") or "默认"
                plat = " ".join(r.get("platform", []))
                for lk in r.get("links", []):
                    size = lk.get("size", "")
                    url = lk.get("content", "")
                    lines.append(f"[{ver}] [{plat}] {size}\n{url}\n")

            yield event.plain_result("\n".join(lines))
        else:
            user_id = event.get_sender_id()
            self._tg_cache[user_id] = games
            self._tg_cache_type[user_id] = "download"

            lines = [f"TouchGal 找到 {len(games)} 个结果，回复数字查看下载链接：\n"]
            for i, g in enumerate(games):
                lines.append(f"{i+1}. {g.get('name', '')}")

            yield event.plain_result("\n".join(lines))

    async def _tg_download_select(self, event, index: int):
        async for result in self._tg_download_show(event, index - 1):
            yield result

    async def _tg_download_show(self, event, index: int):
        user_id = event.get_sender_id()
        results = self._tg_cache.get(user_id, [])

        if index < 0 or index >= len(results):
            yield event.plain_result("序号无效，请重新搜索。")
            return

        game = results[index]
        self._tg_cache.pop(user_id, None)
        self._tg_cache_type.pop(user_id, None)

        resources = await self._tg_resources(game["id"], game["uniqueId"])
        if not resources:
            yield event.plain_result(f"「{game['name']}」暂无下载资源。")
            return

        lines = [f"{game['name']} 下载链接：\n"]
        for r in resources:
            ver = r.get("name") or "默认"
            plat = " ".join(r.get("platform", []))
            for lk in r.get("links", []):
                size = lk.get("size", "")
                url = lk.get("content", "")
                lines.append(f"[{ver}] [{plat}] {size}\n{url}\n")

        yield event.plain_result("\n".join(lines))

    # ============ /b ============
    @filter.command("b")
    async def bangumi_search(self, event):
        if not self.bangumi_key:
            yield event.plain_result("Bangumi API Key 未配置，请联系管理员。")
            return

        keyword = self._parse_kw(event.message_str, "b")
        if not keyword:
            yield event.plain_result("请输入游戏名称，例如：/b 千恋万花")
            return

        if keyword.isdigit():
            async for result in self._bgm_select(event, int(keyword)):
                yield result
            return

        results = await self._bgm_search_list(keyword)
        if not results:
            yield event.plain_result(f"Bangumi 未找到与「{keyword}」相关的游戏。")
            return

        user_id = event.get_sender_id()
        self._bgm_cache[user_id] = results

        lines = [f"Bangumi 找到 {len(results)} 个结果，回复数字查看详情：\n"]
        for i, r in enumerate(results):
            name = r.get("name", "")
            name_cn = r.get("name_cn", "")
            display = f"{name} ({name_cn})" if name_cn else name
            lines.append(f"{i+1}. {display}")

        yield event.plain_result("\n".join(lines))

    async def _bgm_select(self, event, index: int):
        async for result in self._bgm_show_detail(event, index - 1):
            yield result

    async def _bgm_show_detail(self, event, index: int):
        if not self.bangumi_key:
            yield event.plain_result("Bangumi API Key 未配置。")
            return

        user_id = event.get_sender_id()
        results = self._bgm_cache.get(user_id, [])

        if index < 0 or index >= len(results):
            yield event.plain_result("序号无效，请重新搜索。")
            return

        subject_id = results[index]["id"]
        detail = await self._bgm_fetch_detail(subject_id)
        if not detail:
            yield event.plain_result("获取详情失败。")
            return

        self._bgm_cache.pop(user_id, None)

        name = detail.get("name", "")
        name_cn = detail.get("name_cn", "")
        display_name = f"{name} / {name_cn}" if name_cn else name
        date = detail.get("date", "未知")
        platform = detail.get("platform", "未知")
        rating = detail.get("rating", {}).get("score", "暂无")
        summary = (detail.get("summary") or "")[:300]
        images = detail.get("images", {})
        cover = images.get("large") or images.get("common") or ""

        developer = ""
        publisher = ""
        for item in detail.get("infobox", []):
            if isinstance(item, dict):
                k = item.get("key", "")
                v = item.get("value", "")
                if k == "开发":
                    developer = str(v)
                elif k == "发行":
                    publisher = str(v)

        text = f"{display_name}\n"
        if developer:
            text += f"开发：{developer}\n"
        if publisher:
            text += f"发行：{publisher}\n"
        text += (
            f"发行日期：{date}\n"
            f"平台：{platform}\n"
            f"评分：{rating}\n"
        )
        if summary:
            text += f"\n{summary}\n"

        jpg_path = await self._download_and_convert(cover) if cover else None
        chain = self._send_cover_and_text(jpg_path, cover, text)
        yield event.chain_result(chain)

        if jpg_path and os.path.exists(jpg_path):
            try:
                os.remove(jpg_path)
            except Exception:
                pass