# 字幕校正、位置规划、阅读负荷与专名统一工具

基于 **Python + FastAPI** 的轻量 Web 工具，包含四个功能页面：

1. **字幕时间漂移校正**：粘贴 SRT 字幕，填入多组人工确认的「原时间 / 正确时间」
   锚点，按分段线性映射校正字幕时间，在网页预览并下载校正后的 SRT。
2. **字幕位置规划**（<http://localhost:8000/placement>）：粘贴 SRT，填写画面上方 /
   下方被遮挡（台标、弹幕条、滚动新闻等）的时间段与相邻字幕上下换位代价，自动为
   每条字幕选择总遮挡与换位代价最小的位置，并导出带 `line` 位置设置的 WebVTT。
3. **阅读负荷热区**（<http://localhost:8000/reading-load>）：粘贴 SRT，输入阅读
   速率阈值（字/秒）与热区最短持续时长（毫秒），按起止事件精确扫描时间轴，找出
   重叠字幕合计速率严格超标的热区，页面高亮并下载同一份结果 JSON。
4. **字幕专名统一**（<http://localhost:8000/terms>）：粘贴 SRT，逐行填写「标准
   写法 + 别名」，按规则把字幕正文中的别名统一替换为标准写法，页面列出替换清单
   并下载修订后的 SRT。

## 功能与校正规则（时间漂移）

- 粘贴标准 SRT，字幕**序号与文本原样保留**，仅校正开始/结束时间。
- **无损导出**：直接在原始 SRT 文本上逐条替换时间轴行的起止时间码，
  序号、字幕正文、箭头前后空格、`X1:`/`X2:`/`Y1:`/`Y2:`/`Position:` 等行尾
  定位参数、空行、原有换行（CRLF/LF 原样保留，不统一改写）以及文件开头的
  UTF-8 BOM 均保持不变；原文件无 BOM 时结果也不添加 BOM。
- 至少 **2 组**锚点（建议在片头、片中、片尾各取一组，越多越精确）。
- **相邻锚点之间做分段线性插值**；早于第一个锚点或晚于最后一个锚点的字幕，
  沿用最近一个区段（首段 / 末段）的斜率外推。
- 锚点**不自动排序**：原时间列必须严格递增，正确时间列也必须严格递增；
  任一侧出现相等或倒退时，拒绝生成并返回具体原因（指出是第几组锚点）。
- 时间格式 `HH:MM:SS,mmm`（毫秒分隔符逗号、句点均可，毫秒允许 1–3 位）。
- 校正后早于 `00:00:00,000` 的时间会截断为 0，并给出警告。
- 结果可在页面预览、逐条对比，并一键下载 `corrected.srt`：页面预览与下载
  使用接口返回的同一份 `corrected_srt`，下载文件开头**最多一个 BOM**
  （仅当原 SRT 带 BOM 时保留），为 UTF-8 编码。
- SRT 无法解析时接口仍返回 `422` 错误，并在 `detail.message` 中说明原因。

## 功能与规划规则（字幕位置）

- 输入 SRT（复用同一套字幕解析器）、画面**上方 / 下方各自的遮挡时间段**
  （`start` / `end`，`HH:MM:SS,mmm`，结束必须严格晚于开始）以及
  **相邻字幕上下换位代价** `switch_cost_ms`（非负整数，单位毫秒）。
- **同侧重叠遮挡时段先求并集**（首尾相接也合并），再按并集时段与每条字幕
  时间区间的交集累计该侧遮挡时长（毫秒）。
- 以 **总遮挡时长 + 相邻字幕上下换位代价最小** 为目标做动态规划；
  总代价完全相同时**按字幕顺序逐条优先选择下方**（避免字幕无必要地出现在上方）。
- 换位代价越大，规划越倾向让整段字幕保持同侧、减少上下跳动；填 `0` 表示
  换位零成本，每条字幕都选遮挡更短的一侧（同分时下方）。
- 导出 **WebVTT**（`WEBVTT` 文件头、时间码用句点 `.`），并在每条 cue 的
  设置中写入行位置：上方 `line:10%`、下方 `line:90%`，可直接用于支持 WebVTT
  `line` 设置的播放器。
- 返回逐条的上 / 下选择、两侧遮挡时长、所选位置的遮挡时长，以及
  **所选位置仍被遮挡的字幕列表** `still_occluded_cues`（两侧同时遮挡时出现），
  页面中高亮提示并可一键下载 `placement.vtt`。
- 遮挡时间段起止无效（格式错误或结束不晚于开始）、换位代价不是非负整数、
  SRT 无法解析时，接口均返回 `422`，并在 `detail.message` 中给出中文原因。

## 功能与分析规则（阅读负荷热区）

- 输入 SRT（复用同一套字幕解析器）、**正数阅读速率阈值** `rate_threshold`
  （字/秒，如 `5`、`4.5`）与**非负整数** `min_duration_ms`（热区最短持续毫秒数）。
- 每条字幕的阅读速率 = **去掉所有 Unicode 空白字符**（换行、制表符、全角空格
  `　` 等）后的字符数 ÷ 显示秒数（结束 − 开始）。
- 按每个字幕的开始 / 结束事件扫描**半开时间轴** `[start, end)`：区间内各活跃
  字幕的速率相加得到该区间合计速率；首尾相接（一条结束恰为另一条开始）**不算
  重叠**。全程使用毫秒整数与精确分数比较，**不做整秒采样**，毫秒级峰值也能检出。
- 找出合计速率**严格超过**阈值（等于阈值不算）的时间段，**首尾相接的超阈值
  分段自动合并**为热区，再保留连续时长达到 `min_duration_ms` 的热区（先合并、
  再按总时长过滤）。
- 逐段返回热区的起止时间（`HH:MM:SS,mmm`）、持续毫秒数、**峰值速率**（该热区
  内合计速率的最大值，字/秒）以及**参与字幕的输入顺序号**（按粘贴 SRT 中字幕
  出现位置从 1 开始编号，与字幕自身的 SRT 序号无关；多分段合并后升序去重）。
- 页面以时间轴色块、热区明细表展示结果，并在逐条字幕表中**高亮参与热区的字幕**；
  「下载结果 JSON」保存的就是接口返回的**同一份 JSON**（`reading-load.json`）。
- 阈值不是正数（含 `0`、负数、`NaN` / `Infinity`、布尔值、字符串）、最短时长
  不是非负整数、SRT 无法解析时，接口均返回 `422`（`detail.field` 指出字段，
  `detail.message` 给出中文原因；SRT 解析错误的 `detail.type` 为 `srt`）。

## 功能与统一规则（字幕专名）

- 输入 SRT（复用同一套字幕解析器）与至少 **1 条**专名规则；每条规则为一个
  **标准写法**（替换目标）加 **1 个或多个别名**（页面上用 `|` 分隔多个别名，
  前后空格自动忽略）。
- **规则校验**：标准写法不能为空、别名不能为空（含只填空白、多出分隔符产生的
  空项）；**同一别名不得指向不同的标准写法**（重复指向同一标准写法时以先输入的
  规则为准）。违反时接口返回 `422`（`detail.type` 为 `terms`，`detail.message`
  指出第几条规则及原因）。
- **匹配范围**：只扫描字幕**正文的各个物理行**（逐行独立匹配，不跨行），序号行、
  时间轴行及其行尾定位参数一律不参与；匹配**区分大小写**。
- **匹配顺序**：每行从左到右一次扫描，同一位置优先匹配**最长**的别名，等长时按
  **规则输入顺序**（同一条规则内按别名输入顺序）取先出现者；命中后从该片段之后
  继续扫描，**替换文本不再参与匹配**（标准写法里即使包含别名也不会连锁替换）。
- **替换清单**：逐处命中返回字幕的**输入顺序号**（按粘贴 SRT 中字幕出现位置从 1
  开始，与 SRT 序号无关）、SRT 序号、**原文**（命中的别名）、**标准写法**与
  **行内位置**（1 起始的物理行号 `line` + 0 起始的字符偏移 `offset`），并附所在行
  内容 `line_text` 便于核对；页面表格按此列出并在行内高亮命中片段。
- **无损导出**：修订 SRT 只替换正文行内的命中片段，序号、时间轴、
  `X1:`/`Position:` 等排版参数、空行、原有换行（CRLF/LF 原样保留）与开头 BOM
  均保持不变；**未命中任何别名时原文原样返回**。页面预览与下载使用接口返回的
  同一份 `unified_srt`，下载文件为 `unified.srt`（UTF-8）。
- SRT 无法解析时接口返回 `422`（`detail.type` 为 `srt`）。

## 一条命令启动（Docker Compose）

```bash
docker compose up -d --build
```

启动后访问：

- 时间漂移校正界面：<http://localhost:8000/>
- 字幕位置规划界面：<http://localhost:8000/placement>
- 阅读负荷热区界面：<http://localhost:8000/reading-load>
- 阅读负荷热区接口：`POST` <http://localhost:8000/api/reading-load>
- 字幕专名统一界面：<http://localhost:8000/terms>
- 字幕专名统一接口：`POST` <http://localhost:8000/api/terms>
- 健康检查：<http://localhost:8000/health>
- 接口文档（FastAPI 自带）：<http://localhost:8000/docs>

停止：`docker compose down`

### 配置

必要配置只有宿主机映射端口（容器内固定监听 8000，无需其它环境变量）：

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| 端口 | 通过环境变量 `HOST_PORT` 修改宿主机映射端口；容器内固定监听 8000 | `8000` |
| 重启策略 | `restart: unless-stopped`（见 `docker-compose.yml`） | — |

例如改用宿主机 9000 端口：

```bash
HOST_PORT=9000 docker compose up -d --build
# 访问 http://localhost:9000/ 、http://localhost:9000/placement
# 、http://localhost:9000/reading-load 与 http://localhost:9000/terms
```

## 不用 Docker，直接运行（Python 3.10+）

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

同样访问 <http://localhost:8000/>、<http://localhost:8000/placement>、
<http://localhost:8000/reading-load> 与 <http://localhost:8000/terms>。

## HTTP 接口

### `POST /api/correct`

```json
{
  "srt": "1\n00:00:05,000 --> 00:00:08,000\n你好\n",
  "anchors": [
    {"original": "00:00:10,000", "corrected": "00:00:08,000"},
    {"original": "00:02:40,000", "corrected": "00:02:35,000"}
  ]
}
```

成功返回 `corrected_srt`（与输入同构的完整 SRT 文本：只替换各时间轴行的起止
时间码，序号、正文、定位参数、空行、CRLF/LF 换行及 BOM 原样保留）、`cues`
（逐条前后时间对照）与 `warnings`（如时间截断等提示）。SRT 解析失败或锚点不
满足严格递增时返回 `422`，并在 `detail.message` 中给出中文原因。

### `POST /api/placement`

```json
{
  "srt": "1\n00:00:05,000 --> 00:00:09,000\n第一句\n\n2\n00:00:14,000 --> 00:00:18,000\n第二句\n",
  "top_blocks": [
    {"start": "00:00:12,000", "end": "00:00:20,000"}
  ],
  "bottom_blocks": [
    {"start": "00:00:24,000", "end": "00:00:32,000"}
  ],
  "switch_cost_ms": 2000
}
```

`top_blocks` / `bottom_blocks` 均可省略或传空数组（表示该侧全程无遮挡）。
成功返回：

- `vtt`：带 `line:10%` / `line:90%` 行位置设置的完整 WebVTT 文本；
- `cues`：逐条字幕的 `position`（`top` / `bottom`）、`top_occluded_ms`、
  `bottom_occluded_ms`、所选位置遮挡 `occluded_ms` 及 `still_occluded` 标记；
- `still_occluded_cues`：所选位置仍被遮挡的字幕（两侧同时遮挡时才可能出现）；
- `merged_top_blocks` / `merged_bottom_blocks`：两侧遮挡求并集后的时间段
  （`HH:MM:SS,mmm`），便于页面核对；
- `total_occluded_ms`：所选位置的遮挡总毫秒数；`switch_count`：上下换位次数。

时间段起止无效或 `switch_cost_ms` 不是非负整数时返回 `422`
（后者为请求体校验错误，前者与 SRT 解析错误在 `detail.message` 中给出中文原因）。

### `POST /api/reading-load`

```json
{
  "srt": "1\n00:00:00,000 --> 00:00:02,000\n一二三四五六\n\n2\n00:00:01,000 --> 00:00:03,000\n四五六\n",
  "rate_threshold": 4,
  "min_duration_ms": 500
}
```

`rate_threshold` 为字/秒正数（整数或小数均可，按十进制精确比较），
`min_duration_ms` 为非负整数毫秒。成功返回：

- `cues`：逐条字幕的输入顺序号 `order`、SRT 序号 `index`、起止时间、
  `char_count`（去 Unicode 空白后的字符数）、`duration_ms` 与 `rate`（字/秒）；
- `zones`：热区列表，每项包含 `start` / `end`（`HH:MM:SS,mmm`）、
  `duration_ms`、`peak_rate`（峰值合计速率，字/秒）与 `cue_orders`
  （参与字幕的输入顺序号，升序去重）；
- `rate_threshold` / `min_duration_ms`（回显参数）、`cue_count`、`zone_count`。

合计速率**严格超过**阈值的相接分段先合并，再按 `duration_ms >= min_duration_ms`
过滤；没有热区时 `zones` 为空数组。参数不合法或 SRT 解析失败返回 `422`。

### `POST /api/terms`

```json
{
  "srt": "1\n00:00:01,000 --> 00:00:04,000\nNASA announced it\nand nasa too\n",
  "rules": [
    {"standard": "NASA（美国国家航空航天局）", "aliases": ["NASA", "nasa"]},
    {"standard": "中国国家航天局", "aliases": ["CNSA", "中国国家航天局"]}
  ]
}
```

`rules` 至少 1 条；每条规则的 `standard` 为替换目标，`aliases` 为参与匹配的
别名列表（至少 1 个，接口侧逐项去首尾空白）。成功返回：

- `unified_srt`：与输入同构的完整 SRT 文本，只替换正文命中片段（序号、时间轴、
  定位参数、空行、CRLF/LF 换行及 BOM 原样保留；无命中时与输入逐字符一致）；
- `hit_count` / `hits`：逐处命中，含 `cue_order`（字幕输入顺序号）、`cue_index`
  （SRT 序号）、`line`（1 起始物理行号）、`offset`（0 起始行内字符偏移）、
  `matched`（原文，即命中的别名）、`standard`（标准写法）与 `line_text`
  （所在正文行内容）。

标准写法为空、别名为空、规则为空或同一别名指向不同标准写法时返回 `422`
（`detail.type` 为 `terms`，`detail.message` 给出中文原因）；SRT 解析失败时
`detail.type` 为 `srt`。

## 目录结构

```
.
├── app/
│   ├── main.py           # FastAPI 应用与各 /api/* 接口
│   ├── mapping.py        # 锚点校验与分段线性映射
│   ├── placement.py      # 遮挡时段并集、遮挡时长统计、位置规划 DP、WebVTT 导出
│   ├── reading_load.py   # 字 / 秒速率、半开时间轴事件扫描、热区合并与最短时长过滤
│   ├── terms.py          # 专名规则校验、正文逐行最长优先扫描与替换清单
│   ├── srt.py            # SRT 解析与无损重写（时间码 / 正文区间替换，保留原格式）
│   ├── timecode.py       # 时间码解析与格式化（SRT / WebVTT）
│   └── static/
│       ├── index.html         # 时间漂移校正页面（原生 HTML/CSS/JS）
│       ├── placement.html     # 字幕位置规划页面（原生 HTML/CSS/JS）
│       ├── reading_load.html  # 阅读负荷热区页面（原生 HTML/CSS/JS）
│       └── terms.html         # 字幕专名统一页面（原生 HTML/CSS/JS）
├── tests/               # 核心算法与接口测试
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
