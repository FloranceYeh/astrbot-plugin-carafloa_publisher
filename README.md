# CaraFloa Publisher

AstrBot 插件：将消息附件、图片、本地文件或 URL 发布到
[FloranceYeh/CaraFloa-content](https://github.com/FloranceYeh/CaraFloa-content)。

## 配置

安装插件并重启 AstrBot 后，AstrBot 会根据 `_conf_schema.json` 自动生成插件设置，
在插件设置面板中填写：

```text
GitHub Token：你的 GitHub Fine-grained Token
GitHub 仓库：FloranceYeh/CaraFloa-content
GitHub 分支：main
```

Token 只需要对内容仓库拥有：

```text
Contents: Read and write
```

不要把 Token 写进插件文件或公开仓库。

## 创建文章

插件提供与站点 `new:article` 脚本对应的命令：

```text
/cf_new_article --section tech-news --title "文章标题" --summary "文章摘要" --tags "Astro,前端"
```

支持的参数：

```text
--section       栏目，必填
--title         标题，必填
--id            文章 ID，默认根据英文标题生成
--summary       摘要
--period        周期，例如 p1
--cover         封面路径
--tags          逗号分隔的多个标签
--published-at  发布时间，默认当前时间
--content       Markdown 正文
```

同时提供 `carafloa_create_article` LLM Tool，参数与上述字段一致。创建的文章会发布到：

```text
articles/<section>/<id>.md
```

并使用与站点创建脚本一致的 frontmatter 格式和默认正文。


## 发布命令

```text
/cf_publish article <目标路径> [来源]
/cf_publish image <目标路径> [来源]
/cf_publish file <目标路径> [来源]
```

### 使用消息附件

将 Markdown 文件、图片或其他文件附加在消息中：

```text
/cf_publish article articles/tech-news/new.md
/cf_publish image images/covers/new.png
/cf_publish file images/assets/demo.zip
```

### 使用本地路径或 URL

```text
/cf_publish article articles/tech-news/new.md D:\drafts\new.md
/cf_publish image images/covers/new.png https://example.com/new.png
```

文章只能发布到 `articles/`，图片只能发布到 `images/`，其他文件可以发布到内容
仓库允许的相对路径中。单个文件最大 10 MB，每次命令产生一个独立 GitHub commit。

插件使用 GitHub Contents API 直接写入仓库，不需要在 AstrBot 服务器上 clone
内容仓库。内容仓库的 Actions 会在推送后触发 Netlify 重新构建。

## LLM Tool

插件提供 `carafloa_publish` 工具。模型可以在确认用户发布意图后调用：

- `file_type`：`article`、`image` 或 `file`
- `target_path`：内容仓库中的目标路径
- `source`：AstrBot 服务器上的本地路径或 HTTP/HTTPS URL

例如：

```text
carafloa_publish(
  file_type="article",
  target_path="articles/tech-news/new.md",
  source="D:/drafts/new.md"
)
```

LLM Tool 不读取当前消息附件。发布消息附件时，请使用 `/cf_publish` 命令显式指定
目标路径，避免模型误判文件用途。