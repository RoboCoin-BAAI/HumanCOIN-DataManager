# HumanCOIN DataManager

HumanCOIN 数据门户：浏览、筛选、预览和下载 Hugging Face 与 ModelScope 上的数据集。

[English documentation](README.md) · [HumanCOIN 项目介绍](https://koorye.github.io/HumanCOIN-dev/)

## 本地运行

需要 Python 3.10+ 和 Node.js 20+；前端无需安装依赖。

```bash
npm run dev
```

访问 http://127.0.0.1:8000/ 。右上角可切换中英文，`?lang=zh` 可直接进入中文版。数据集名称、任务、场景值、元数据和下载命令保持英文。

## 数据目录

页面先读取 `docs/data/catalog.json` 的汇总与等级索引引用，再按所选等级加载索引。筛选、统计和分页在 Web Worker 内完成，详情按需加载。L1、L2、L3 分别统计，默认每页 20 条。

场景遵循 `HUMANCOIN_SCENES_V1.md`，分为 category 和 area；任务支持搜索候选。时长使用小时，按仓库累加，同一记录的不同版本可能重复计算。

卡片封面和短视频保存在网站自身的 `docs/data/media/`。完整视频目前优先读取 Hugging Face；底部的平台选择影响下载命令，不改变预览来源。

## 同步与验证

```bash
npm run sync
npm test
npm run check
```

同步脚本读取两个平台的公开元数据，生成内容哈希索引、详情和媒体资源，验证后原子切换目录。生成视频预览需要 FFmpeg。`sync-state/` 保存增量同步状态，不存放访问令牌。网页加载不会主动运行同步。

## GitHub Pages

在仓库 Settings → Pages 中选择 **GitHub Actions**。推送到 main 后，Pages 工作流检查并发布 `docs/`。目录同步工作流每日 01:00 UTC（北京时间 09:00）执行，也可在 Actions 中手动触发。

预期地址：https://robocoin-baai.github.io/HumanCOIN-DataManager/

下载命令使用 HumanCOIN-LeRobot 工具，门户自身不代理下载。申请权限由数据平台的仓库设置控制，网页提示不会启用权限限制。

完整架构、同步参数及限制见 [README.md](README.md)。

## 安装下载工具

使用 Python 3.10–3.13，可直接安装 PyPI 包，无需克隆源码：

```bash
pip install humancoin-lerobot
# 使用 ModelScope 时：
pip install "humancoin-lerobot[modelscope]"
```

网页按下载平台显示对应安装命令；随后执行生成的 `humancoin-download` 命令。
