---
name: enterprise-print
description: 通过企业 Print Hub 在 WorkBuddy 中直接打印聊天正文、已生成的内容或附件，并打开内网打印后台、查询打印机和任务、查打印记录、取消任务或调整优先级。适用于公司 10.0.249.200 文印服务。
metadata:
  version: "1.0.1"
---

# 企业文印 Print Hub

后台入口为 `https://10.0.249.200:8086/#history`。在本技能实际安装目录运行 `scripts/print_hub.py`，使用本机 Python 3.9+ 或 WorkBuddy 自带的 Python。Windows 使用 `py -3` 或 `python`，macOS 使用 `python3`。凭据和证书配置见 [导入与配置](导入与配置.md)。

CLI 已内置该后台当前证书的已确认指纹。首次使用直接执行用户请求。只有 CLI 报证书指纹不符时才提示核对换证，使用管理员确认的新指纹或公司 CA 处理。

## 打印聊天正文或附件

1. 用户明确要求打印时，使用指定的正文、上一条相关回答或附件。只要求生成可打印文稿时，先在对话里交付文稿。引用对象不清楚时，请用户指定要出纸的内容。
2. 聊天正文用文件工具写入临时 UTF-8 文件，保留换行和中文。对于“原文打印”，保持正文原样。正文通过文件交给命令，避免将多行文本或特殊字符插入 shell 命令。附件使用 WorkBuddy 提供的真实本地路径。
3. 运行 `print-text` 或 `print-file` 一次。每次新的打印请求可生成一个 UUID 并随 `--request-id` 传入，便于调用中断后核对。指定设备时传型号、楼层或设备 ID。`--user` 填用户指定的姓名或工号，省略时使用配置的默认提交人或系统用户名。

```powershell
py -3 .\scripts\print_hub.py print-text --text-file "C:\实际路径\正文.txt" --title "会议通知" --printer "28楼" --user "张三" --copies 1
py -3 .\scripts\print_hub.py print-file --file "C:\实际路径\附件.docx" --printer "28楼" --user "张三"
```

默认使用后台默认打印机、1 份、设备默认单双面、普通优先级 50。明确要求时，使用 `--duplex simplex` 单面、`duplex_long` 长边双面或 `duplex_short` 短边双面。`--copies` 为 1–99，`--priority` 为 1–100。

上传超时、调用中断或响应不确定时，按原标识执行 `task --request-id <原标识> --verify`，使用返回的任务号和状态答复。结果仍未知时说明待核实，避免重复出纸。仅在需要进一步核对已接收的作业时执行 `task --job-id <编号> --verify`。

## 后台和任务管理

| 用户意图 | 命令参数 |
| --- | --- |
| 打开打印记录 | `open --browser` |
| 打开工作台、设备、队列或新建打印 | `open --page overview --browser`，页面参数也可用 `devices`、`queue`、`new-print` |
| 列出打印机或查询转换服务 | `printers` 或 `converter` |
| 查看设备状态、实时作业或网络诊断 | `status --printer "28楼"`、`queue --printer "28楼"` 或 `diag --printer "28楼"` |
| 查询打印记录 | `history --printer "28楼" --search "会议通知" --user "张三" --start YYYY-MM-DD --end YYYY-MM-DD`，按需要添加筛选 |
| 核查某个任务 | `task --job-id 123 --verify` |
| 取消任务、加急或改优先级 | `cancel --job-id 123`、`cut-in --job-id 123` 或 `priority --job-id 123 --priority 80` |
| 设为默认打印机 | `set-default --printer "28楼"`，取决于后台权限 |

页面打不开时提供对应链接。网页的「打印设备」用于有权限的设备接入与管理，「打印记录」可切换查看设备作业。`history` 查的是该服务节点的提交历史。队列里设备作业号与平台任务编号分开使用，CLI 的取消和调度操作使用平台编号。只有用户明确要求时才修改任务或默认设备。缺少编号时先查询以定位唯一任务。取消、加急或调整超时后先查询该任务的实际状态。

## 对话回执

用一行中文状态和 Markdown 表格回复，表格列为「项目」「内容」，项目依次为「打印文件」「打印机」「打印设置」「提交人」「任务编号」。文件用实际任务名，打印机可附返回的楼层，设置显示已知页数、份数和单双面。数据尚未返回时写「待核实」。状态使用 `display.status_zh` 和实际任务记录，失败时简要说明 `error_msg`。仅在设备确认完成时回复「设备已确认完成」。对打印记录和任务管理使用简短中文结果，可附相应后台链接。

正文打印示例请求 `把下面这段会议通知打印到 28 楼，1 份，提交人张三：明天上午 9 点在 3 号会议室开会。`。用于打印的正文是冒号之后的通知，聊天中同时返回本次任务的状态与表格。
