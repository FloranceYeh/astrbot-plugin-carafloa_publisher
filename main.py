import base64
import json
import mimetypes
import re
import shlex
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import File, Image


GITHUB_API = "https://api.github.com"
MAX_FILE_SIZE = 10 * 1024 * 1024
SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")


@register(
    "carafloa_publisher",
    "FloranceYeh",
    "将消息附件、图片、本地文件或 URL 发布到 CaraFloa 内容仓库。",
    "1.0.0",
)
class CaraFloaPublisher(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.token = str(config.get("github_token", ""))
        self.repository = str(
            config.get("github_repository", "FloranceYeh/CaraFloa-content")
        )
        self.branch = str(config.get("github_branch", "main"))

    @filter.command("cf_publish")
    async def publish(self, event: AstrMessageEvent):
        """发布文件到 CaraFloa 内容仓库。用法：/cf_publish <article|image|file> <目标路径> [来源]"""
        if not self.token:
            yield event.plain_result("发布失败：插件设置中未配置 GitHub Token。")
            return

        args = event.message_str.strip().split(maxsplit=3)
        if len(args) < 3 or args[1] not in {"article", "image", "file"}:
            yield event.plain_result(
                "用法：/cf_publish <article|image|file> <目标路径> [本地路径或 URL]\n"
                "例如：/cf_publish image images/covers/demo.png"
            )
            return

        file_type, target_path = args[1], args[2]
        source = args[3] if len(args) == 4 else None
        try:
            self._validate_target(file_type, target_path)
            commit_url = await self._publish_file(file_type, target_path, source, event)
            yield event.plain_result(f"发布成功：{target_path}\n{commit_url}")
        except ValueError as exc:
            yield event.plain_result(f"发布失败：{exc}")
        except Exception:
            logger.exception("CaraFloa 文件发布失败")
            yield event.plain_result("发布失败：远程仓库请求或文件读取出错，请查看日志。")

    @filter.command("cf_new_article")
    async def new_article(self, event: AstrMessageEvent):
        """创建并发布文章。用法：/cf_new_article --section <栏目> --title <标题> [选项]"""
        if not self.token:
            yield event.plain_result("创建失败：插件设置中未配置 GitHub Token。")
            return

        try:
            options = self._parse_options(event.message_str)
            target_path, data = self._build_article(options)
            commit_url = self._publish_to_github(target_path, data)
            yield event.plain_result(f"文章创建成功：{target_path}\n{commit_url}")
        except ValueError as exc:
            yield event.plain_result(f"创建失败：{exc}")
        except Exception:
            logger.exception("CaraFloa 创建文章失败")
            yield event.plain_result("创建失败：远程仓库请求出错，请查看日志。")

    @filter.llm_tool(name="carafloa_publish")
    async def carafloa_publish(
        self,
        event: AstrMessageEvent,
        file_type: str,
        target_path: str,
        source: str,
    ) -> str:
        """发布文件到 CaraFloa 内容仓库。

        Args:
            file_type(string): 文件类型，只能是 article、image 或 file。
            target_path(string): 内容仓库中的目标相对路径。article 必须位于 articles/，image 必须位于 images/。
            source(string): 本地文件路径或 HTTP/HTTPS 下载地址。LLM 工具不能直接读取当前消息附件。
        """
        if not self.token:
            return "发布失败：插件设置中未配置 GitHub Token。"
        try:
            commit_url = await self._publish_file(file_type, target_path, source, event)
            return f"发布成功：{target_path}\n{commit_url}"
        except ValueError as exc:
            return f"发布失败：{exc}"
        except Exception:
            logger.exception("CaraFloa LLM 文件发布失败")
            return "发布失败：远程仓库请求或文件读取出错，请查看日志。"

    @filter.llm_tool(name="carafloa_create_article")
    async def carafloa_create_article(
        self,
        event: AstrMessageEvent,
        section: str,
        title: str,
        article_id: str = "",
        summary: str = "",
        period: str = "",
        cover: str = "",
        tags: list[str] | None = None,
        published_at: str = "",
        content: str = "",
    ) -> str:
        """按照 CaraFloa 文章格式创建并发布一篇 Markdown 文章。

        Args:
            section(string): 文章栏目，只能使用字母、数字和短横线。
            title(string): 文章标题。
            article_id(string): 可选的文章 ID 和文件名，不填写时根据英文标题生成。
            summary(string): 可选的文章摘要。
            period(string): 可选的文章周期，例如 p1。
            cover(string): 可选的封面路径，例如 /images/cover.jpg。
            tags(array[string]): 可选的文章标签列表。
            published_at(string): 可选的发布时间，必须是有效 ISO 日期，不填写时使用当前时间。
            content(string): 可选的 Markdown 正文，不填写时使用默认正文。
        """
        if not self.token:
            return "创建失败：插件设置中未配置 GitHub Token。"
        try:
            target_path, data = self._build_article(
                {
                    "section": section,
                    "title": title,
                    "id": article_id or None,
                    "summary": summary,
                    "period": period or None,
                    "cover": cover or None,
                    "tags": tags,
                    "published-at": published_at or None,
                    "content": content,
                }
            )
            commit_url = self._publish_to_github(target_path, data)
            return f"文章创建成功：{target_path}\n{commit_url}"
        except ValueError as exc:
            return f"创建失败：{exc}"
        except Exception:
            logger.exception("CaraFloa LLM 创建文章失败")
            return "创建失败：远程仓库请求出错，请查看日志。"

    async def _publish_file(
        self,
        file_type: str,
        target_path: str,
        source: str | None,
        event: AstrMessageEvent,
    ):
        if file_type not in {"article", "image", "file"}:
            raise ValueError("文件类型必须是 article、image 或 file。")
        self._validate_target(file_type, target_path)
        data, filename = await self._read_source(event, source)
        self._validate_size(data)
        if file_type == "article" and not filename.lower().endswith(".md"):
            raise ValueError("文章文件必须是 Markdown（.md）文件。")
        if file_type == "image" and not (
            mimetypes.guess_type(filename)[0] or ""
        ).startswith("image/"):
            raise ValueError("图片发布要求来源是常见图片文件。")
        return self._publish_to_github(target_path, data)

    async def _read_source(self, event: AstrMessageEvent, source: str | None):
        if source:
            if source.startswith(("http://", "https://")):
                return self._read_url(source)
            path = Path(source).expanduser().resolve()
            if not path.is_file():
                raise ValueError("本地文件不存在。")
            return path.read_bytes(), path.name

        for component in event.get_messages():
            if isinstance(component, (Image, File)):
                path = component.file or component.url
                if path:
                    return self._read_local_or_url(path)
        raise ValueError("未找到消息附件或图片，请附加文件或填写来源。")

    def _read_local_or_url(self, source: str):
        if source.startswith(("http://", "https://")):
            return self._read_url(source)
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise ValueError("消息附件路径不可读。")
        return path.read_bytes(), path.name

    def _read_url(self, source: str):
        parsed = urlparse(source)
        filename = Path(parsed.path).name or "downloaded-file"
        request = Request(source, headers={"User-Agent": "CaraFloa-AstrBot-Plugin/1.0"})
        with urlopen(request, timeout=30) as response:
            data = response.read(MAX_FILE_SIZE + 1)
        return data, filename

    @staticmethod
    def _parse_options(message: str):
        tokens = shlex.split(message, posix=True)
        options = {}
        index = 1
        while index < len(tokens):
            key = tokens[index]
            if not key.startswith("--"):
                raise ValueError(f"无法识别参数：{key}")
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                raise ValueError(f"参数 {key} 需要一个值")
            options[key[2:]] = tokens[index + 1]
            index += 2
        return options

    @staticmethod
    def _build_article(options):
        section = options.get("section", "")
        title = options.get("title", "")
        if not section:
            raise ValueError("缺少必填参数：--section")
        if not title:
            raise ValueError("缺少必填参数：--title")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", section, re.IGNORECASE):
            raise ValueError("section 只能包含字母、数字和短横线")

        article_id = options.get("id") or CaraFloaPublisher._slugify(title)
        if not article_id:
            article_id = f"article-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", article_id, re.IGNORECASE):
            raise ValueError("id 只能包含字母、数字和短横线")

        published_at = options.get("published-at") or datetime.now().astimezone().isoformat()
        try:
            datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"publishedAt 不是有效日期：{published_at}") from exc

        raw_tags = options.get("tags")
        if isinstance(raw_tags, str):
            tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
        elif raw_tags is None:
            tags = None
        else:
            tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]

        fields = [
            ("id", article_id),
            ("section", section),
            ("period", options.get("period")),
            ("title", title),
            ("summary", options.get("summary", "")),
            ("cover", options.get("cover")),
            ("tags", tags),
            ("publishedAt", published_at),
        ]
        frontmatter = "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in fields
            if value is not None
        )
        body = options.get("content") or options.get("body") or f"# {title}\n\n在这里开始写文章。\n"
        data = f"---\n{frontmatter}\n---\n\n{body.strip()}\n".encode("utf-8")
        return f"articles/{section}/{article_id}.md", data

    @staticmethod
    def _slugify(value):
        value = re.sub(r"[^a-z0-9\s-]", "", value.lower())
        return re.sub(r"^-+|-+$", "", re.sub(r"[\s-]+", "-", value))

    def _publish_to_github(self, target_path: str, data: bytes):
        import json

        import urllib.error

        url = f"{GITHUB_API}/repos/{self.repository}/contents/{target_path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "CaraFloa-AstrBot-Plugin/1.0",
        }
        encoded = base64.b64encode(data).decode("ascii")
        payload = {
            "message": f"content: publish {target_path}",
            "content": encoded,
            "branch": self.branch,
        }

        try:
            with urlopen(
                Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={**headers, "Content-Type": "application/json"},
                    method="PUT",
                ),
                timeout=30,
            ) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ValueError(f"GitHub API 返回 HTTP {exc.code}：{detail}") from exc

        return result.get("commit", {}).get("html_url", url)

    @staticmethod
    def _validate_target(file_type: str, target_path: str):
        if (
            not target_path
            or not SAFE_PATH.fullmatch(target_path)
            or target_path.startswith(("/", "."))
            or ".." in Path(target_path).parts
        ):
            raise ValueError("目标路径包含非法字符或目录穿越。")
        if file_type == "article" and not target_path.startswith("articles/"):
            raise ValueError("文章目标路径必须位于 articles/ 下。")
        if file_type == "image" and not target_path.startswith("images/"):
            raise ValueError("图片目标路径必须位于 images/ 下。")

    @staticmethod
    def _validate_size(data: bytes):
        if len(data) > MAX_FILE_SIZE:
            raise ValueError(f"文件不能超过 {MAX_FILE_SIZE // 1024 // 1024} MB。")
