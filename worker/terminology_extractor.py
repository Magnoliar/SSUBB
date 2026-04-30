"""SSUBB Worker - 术语提取器

两阶段术语获取:
1. SRT 提取 — 从字幕文本中用 LLM 提取专有名词（兜底）
2. 网搜译名 — 根据 media_title 搜索豆瓣/维基百科已有译名（高优先级）

最终合并: 网搜结果覆盖 SRT 提取（更可靠），SRT 补充网搜未覆盖的词。
"""

import logging
import re
from typing import Optional

import httpx

from .llm_client import LLMClient

logger = logging.getLogger("ssubb.terminology")

EXTRACT_SYSTEM_PROMPT = """You are a terminology extraction specialist for subtitle translation.
Your task is to extract all proper nouns and specialized terms from the given subtitle text.

Extract these categories:
1. Character names (people, nicknames, titles)
2. Place names (cities, countries, planets, fictional locations)
3. Organizations (companies, groups, factions)
4. Special items (weapons, artifacts, magical objects)
5. Skills/Abilities (magic spells, techniques, powers)
6. Species/Races (aliens, fantasy races)
7. Other proper nouns (brands, events, etc.)

Rules:
- Only extract terms that actually appear in the subtitles
- Keep the original term exactly as it appears
- Provide a natural Chinese translation for each term
- If a term has no standard Chinese translation, transliterate it phonetically
- Do NOT include common words or generic terms
- Output ONLY a valid JSON dictionary mapping original term to Chinese translation
- Example: {"Tony Stark": "托尼·斯塔克", "Mjolnir": "妙尔尼尔", "Hogwarts": "霍格沃茨"}
"""

WEB_SEARCH_PROMPT = """You are a media terminology specialist.
Given a list of proper nouns extracted from subtitles, and reference text from web pages about this media,
map each term to its commonly accepted Chinese translation.

Rules:
- Use official or widely-accepted translations from the reference text
- If a term appears in multiple translation forms, use the most common one
- If no translation is found in the reference, leave it as-is (do NOT guess)
- Output ONLY a valid JSON dictionary mapping original term to Chinese translation
"""


class TerminologyExtractor:
    """术语提取器（SRT 提取 + 网搜译名）"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def extract(
        self,
        srt_content: str,
        target_lang: str = "zh",
        media_title: Optional[str] = None,
    ) -> Optional[dict]:
        """两阶段术语获取

        Args:
            srt_content: SRT 字幕文本
            target_lang: 目标语言代码
            media_title: 媒体标题 (用于网搜译名)

        Returns:
            术语字典 {原文: 译文}，失败返回空 dict
        """
        # ═══════════════════════════════════════════════════════
        # Phase 1: SRT 提取（兜底）
        # ═══════════════════════════════════════════════════════
        srt_glossary = await self._extract_from_srt(srt_content, target_lang)
        if srt_glossary is None:
            srt_glossary = {}

        # ═══════════════════════════════════════════════════════
        # Phase 2: 网搜译名（高优先级，失败不影响）
        # ═══════════════════════════════════════════════════════
        if media_title and srt_glossary:
            web_glossary = await self._search_web_terms(
                media_title, list(srt_glossary.keys()), target_lang
            )
            if web_glossary:
                # 网搜结果覆盖 SRT 提取（更可靠）
                merged = {**srt_glossary, **web_glossary}
                logger.info(
                    f"术语合并: SRT={len(srt_glossary)}, 网搜={len(web_glossary)}, "
                    f"最终={len(merged)}"
                )
                return merged
            else:
                logger.info(f"网搜未找到译名，使用 SRT 提取结果 ({len(srt_glossary)} 个)")

        return srt_glossary if srt_glossary else None

    async def _extract_from_srt(
        self, srt_content: str, target_lang: str
    ) -> Optional[dict]:
        """Phase 1: 从 SRT 文本提取术语"""
        if not srt_content or not srt_content.strip():
            return None

        text = self._strip_srt(srt_content)
        if len(text) < 50:
            logger.info("字幕文本过短，跳过术语提取")
            return {}

        if len(text) > 3000:
            text = text[:3000]

        lang_name = self._get_language_name(target_lang)
        user_prompt = (
            f"Target Language: {lang_name}\n\n"
            f"Subtitle text to extract terminology from:\n\n{text}"
        )
        messages = [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        result = await self.llm.call_with_json_validation(
            messages=messages, expected_keys=set(), max_retries=2,
        )

        if result is None:
            logger.warning("SRT 术语提取失败")
            return None

        glossary = {
            k: v for k, v in result.items()
            if v and k.strip() and v.strip() and k.strip() != v.strip()
        }
        logger.info(f"SRT 术语提取完成: {len(glossary)} 个术语")
        return glossary

    async def _search_web_terms(
        self,
        media_title: str,
        srt_terms: list[str],
        target_lang: str,
    ) -> Optional[dict]:
        """Phase 2: 根据 media_title 网搜已有译名

        搜索策略: 豆瓣 → 维基百科中文
        用 LLM 从网页内容中匹配 SRT 提取出的术语。
        """
        if not media_title or not srt_terms:
            return None

        # 尝试多个来源
        web_texts = []

        # 来源 1: 豆瓣搜索
        try:
            douban_text = await self._fetch_douban(media_title)
            if douban_text:
                web_texts.append(("豆瓣", douban_text))
        except Exception as e:
            logger.debug(f"豆瓣搜索失败: {e}")

        # 来源 2: 维基百科中文
        try:
            wiki_text = await self._fetch_wikipedia_zh(media_title)
            if wiki_text:
                web_texts.append(("维基百科", wiki_text))
        except Exception as e:
            logger.debug(f"维基百科搜索失败: {e}")

        if not web_texts:
            return None

        # 合并所有网页文本
        combined_ref = ""
        for source, text in web_texts:
            combined_ref += f"\n\n--- 来源: {source} ---\n{text[:2000]}"

        # 用 LLM 从参考文本中匹配术语
        terms_str = ", ".join(srt_terms[:50])  # 限制术语数量
        user_prompt = (
            f"Media Title: {media_title}\n\n"
            f"Terms to translate (from subtitles):\n{terms_str}\n\n"
            f"Reference text from web:\n{combined_ref}"
        )
        messages = [
            {"role": "system", "content": WEB_SEARCH_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        result = await self.llm.call_with_json_validation(
            messages=messages, expected_keys=set(), max_retries=2,
        )

        if not result:
            return None

        glossary = {
            k: v for k, v in result.items()
            if v and k.strip() and v.strip() and k.strip() != v.strip()
        }
        logger.info(f"网搜译名匹配: {len(glossary)} 个术语")
        return glossary

    async def _fetch_douban(self, title: str) -> Optional[str]:
        """从豆瓣搜索影视条目，返回简介文本"""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                # 豆瓣搜索 API
                resp = await client.get(
                    "https://www.douban.com/search",
                    params={"cat": "1002", "q": title},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                if resp.status_code != 200:
                    return None

                text = resp.text
                # 提取第一个搜索结果的链接
                match = re.search(r'href="(https://movie\.douban\.com/subject/\d+/)"', text)
                if not match:
                    return None

                # 抓取条目页
                detail_resp = await client.get(
                    match.group(1),
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                if detail_resp.status_code == 200:
                    # 提取简介和标题信息
                    page = detail_resp.text
                    # 提取标题
                    title_match = re.search(r'<title>(.*?)</title>', page)
                    title_info = title_match.group(1) if title_match else ""
                    # 提取简介
                    summary_match = re.search(
                        r'<span class="all hidden">(.*?)</span>|<span property="v:summary">(.*?)</span>',
                        page, re.DOTALL
                    )
                    summary = ""
                    if summary_match:
                        summary = summary_match.group(1) or summary_match.group(2) or ""
                        summary = re.sub(r'<[^>]+>', '', summary).strip()
                    # 提取导演/演员
                    celebrity = re.findall(r'celebrity/\d+/">(.*?)</a>', page)

                    parts = [f"标题: {title_info}"]
                    if celebrity:
                        parts.append(f"演职: {', '.join(celebrity[:10])}")
                    if summary:
                        parts.append(f"简介: {summary[:500]}")
                    return "\n".join(parts)
        except Exception as e:
            logger.debug(f"豆瓣抓取异常: {e}")
        return None

    async def _fetch_wikipedia_zh(self, title: str) -> Optional[str]:
        """从中文维基百科搜索条目，返回摘要"""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                # 维基百科 API 搜索
                resp = await client.get(
                    "https://zh.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": title,
                        "srlimit": 1,
                        "format": "json",
                    },
                )
                if resp.status_code != 200:
                    return None

                data = resp.json()
                results = data.get("query", {}).get("search", [])
                if not results:
                    return None

                page_title = results[0]["title"]

                # 获取页面摘要
                summary_resp = await client.get(
                    "https://zh.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": page_title,
                        "prop": "extracts",
                        "exintro": True,
                        "explaintext": True,
                        "format": "json",
                    },
                )
                if summary_resp.status_code == 200:
                    pages = summary_resp.json().get("query", {}).get("pages", {})
                    for page in pages.values():
                        extract = page.get("extract", "")
                        if extract:
                            return f"条目: {page_title}\n{extract[:1500]}"
        except Exception as e:
            logger.debug(f"维基百科抓取异常: {e}")
        return None

    @staticmethod
    def _strip_srt(srt_content: str) -> str:
        """去掉 SRT 序号和时间码，只保留纯文本"""
        lines = []
        for line in srt_content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.isdigit():
                continue
            if "-->" in line:
                continue
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _get_language_name(code: str) -> str:
        lang_map = {
            "zh": "Simplified Chinese", "en": "English", "ja": "Japanese",
            "fr": "French", "de": "German", "ko": "Korean",
            "es": "Spanish", "ru": "Russian", "pt": "Portuguese",
        }
        return lang_map.get(code, code)
