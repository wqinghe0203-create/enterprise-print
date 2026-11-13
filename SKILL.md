---
name: enterprise-print
description: 通过企业 Print Hub 在 WorkBuddy 中直接打印聊天正文、已生成的内容或附件，并打开内网打印后台、查询打印机和任务、查打印记录、取消任务或调整优先级。适用于公司 10.0.249.200 文印服务。
metadata:
  version: "1.0.11"
---

# 企业文印 Print Hub

**每次调用本技能，先运行 `scripts/print_hub.py preferences check`。** 即使用户只是问技能用途、使用方法或查询状态，也要在回答或处理原请求前执行检查。用户正在回答设置卡时，接着处理已有答案。

**收到 `setup.ask_user_question` 就立即把整个对象原样交给 WorkBuddy 原生工具 `AskUserQuestion`，一次弹出整张卡。直接弹卡，省去「是否现在配置」的确认。** 工具不可用或报错时，直接一次展示 `setup.prompt` 中的选项。检查无 `setup` 时正常处理原请求。若有 `setup_error`，说明无法加载设置；仍可处理原问题或查询。

用户完成配置后继续原请求。用户选「稍后配置」或关闭卡片时，本轮仍可回答说明类问题或查询；本轮到此暂停打印，下次调用再检查。若打印命令返回 `setup_required`，按同样流程直接弹卡，保留原文件、本次参数和返回的 `request_id`，保存后继续。

后台入口为 `https://10.0.249.200:8086/#history`。在本技能实际安装目录运行 `scripts/print_hub.py`，使用本机 Python 3.9+ 或 WorkBuddy 自带的 Python。Windows 使用 `py -3` 或 `python`，macOS 使用 `python3`。凭据和证书配置见 [导入与配置](导入与配置.md)。

CLI 已内置该后台当前证书的已确认指纹。只有 CLI 报证书指纹不符时才提示核对换证，使用管理员确认的新指纹或公司 CA 处理。

## 默认打印设置

首次配置使用四题卡。已有完整配置时，用户主动说「修改默认打印设置」就运行 `preferences setup` 并直接弹四题卡。旧设置只有前三项时，`preferences check` 会返回一张只问提交人的卡，并带有 `setup.existing_preferences`。对话省略 CLI 的 JSON 和错误代码。

1. **默认打印机。** 用 `setup.printers` 将选项字母映射到设备 ID。收到「提交后打开后台添加打印机」的答案后，执行 `open --add-printer --browser` 并提供设备页链接。设备添加后，执行 `preferences setup` 刷新列表，再请用户选新设备。选「更多打印机」时，从 `setup.device_options` 每页展示至多 3 台和一个分页选项。需要重新选设备时，保留同一张卡中已经提交的其他答案，只补问缺失项。
2. **单双面和任务优先级。** 「单面」「双面 · 长边翻页」「双面 · 短边翻页」依次映射为 `simplex`、`duplex_long`、`duplex_short`。优先级选项依次映射为 50、80、100。收到「其他补充」时，仅接受能明确对应到这些预设的答案。其余情况请用户重选该题。
3. **提交人。** 选当前系统用户名时使用 `--system-user`。自定义时在本题的「其他补充」填写姓名或工号，随整张卡提交。收到自定义文字时，用文件工具把它原样写到一行 UTF-8 临时文件，再用 `--user-file <文件路径>` 保存。删除为此创建的临时文件。选「稍后配置」时，暂不保存或打印。
4. 答案齐全后，执行一次 `preferences set --printer <设备ID> --duplex <模式> --priority <数值>`，并附上所选提交人的参数。补齐旧设置时改用 `preferences set-user` 和提交人参数，保留原有三项。用户取消时暂不保存或打印。若缺少答案、设备已移除或提交人无效，保留其他有效答案，只补问需要修正的项目。
5. 保存成功后，脚本会打开打印设备页同步设置。若返回 `preferences_sync_error`，告知用户如何补做同步。如果已有明确的待打印请求，使用原文件或正文、本次明确指定的参数和同一个提交标识继续提交。份数默认 1，本次参数优先于个人设置。

从对话打开后台时使用 `open --browser`，由脚本将已保存的四项设置交给当前浏览器。「打开打印设备页」使用 `open --page devices --browser`。对话只展示脚本返回的普通链接 `url`。

## 打印聊天正文或附件

1. 用户明确要求打印时，使用指定的正文、上一条相关回答或附件。只要求生成可打印文稿时，先在对话里交付文稿。引用对象不清楚时，请用户指定要出纸的内容。
2. WorkBuddy 刚生成 DOCX，用户说「打印这个」时，把该产物的真实本地路径交给 `print-file`，由中心服务转换。附件也使用 WorkBuddy 提供的真实本地路径。只有用户要打印的内容是聊天正文时，才把正文原样写入 UTF-8 文件交给 `print-text`。
3. 运行 `print-text` 或 `print-file`。每次新的打印请求生成一个 UUID 并随 `--request-id` 传入，便于调用中断后核对。指定设备时传型号、楼层或设备 ID。`--user` 填本次指定的提交人，省略时使用个人设置中的提交人。

```powershell
py -3 .\scripts\print_hub.py print-text --text-file "C:\实际路径\正文.txt" --title "会议通知" --printer "28楼" --user "张三" --copies 1
py -3 .\scripts\print_hub.py print-file --file "C:\实际路径\附件.docx" --printer "28楼" --user "张三"
```

省略打印机、单双面或优先级时，CLI 使用个人设置。首次打印按「默认打印设置」完成配置后再提交。份数默认 1，`--copies` 为 1–99，`--priority` 为 1–100。若返回 `preferred_printer_missing` 或 `invalid_preferences`，按「默认打印设置」重新配置后继续原任务。

上传超时、调用中断或响应不确定时，按原标识执行 `task --request-id <原标识> --verify`，使用返回的任务号和状态答复。结果仍未知时说明待核实，避免重复出纸。仅在需要进一步核对已接收的作业时执行 `task --job-id <编号> --verify`。

## 后台和任务管理

| 用户意图 | 命令参数 |
| --- | --- |
| 打开打印记录 | `open --browser` |
| 打开工作台、设备、队列或新建打印 | `open --page overview --browser`，页面参数也可用 `devices`、`queue`、`new-print` |
| 添加打印机 | `open --add-printer --browser`，在设备页填写 IP、检测并保存 |
| 列出打印机或查询转换服务 | `printers` 或 `converter` |
| 查看设备状态、实时作业或网络诊断 | `status --printer "28楼"`、`queue --printer "28楼"` 或 `diag --printer "28楼"` |
| 查询打印记录 | `history --printer "28楼" --search "会议通知" --user "张三" --start YYYY-MM-DD --end YYYY-MM-DD`，按需要添加筛选 |
| 核查某个任务 | `task --job-id 123 --verify` |
| 取消任务、加急或改优先级 | `cancel --job-id 123`、`cut-in --job-id 123` 或 `priority --job-id 123 --priority 80` |
| 修改个人默认打印设置 | 走「默认打印设置」一节的流程 |
| 修改后台全局默认打印机 | `set-default --printer "28楼"`，取决于后台权限 |

页面打不开时提供对应链接。网页的「打印设备」用于有权限的设备接入与管理，「打印记录」可切换查看设备作业。`history` 查的是该服务节点的提交历史。队列里设备作业号与平台任务编号分开使用，CLI 的取消和调度操作使用平台编号。只有用户明确要求时才修改任务或默认设备。缺少编号时先查询以定位唯一任务。取消、加急或调整超时后先查询该任务的实际状态。

## 对话回执

用一行中文状态和 Markdown 表格回复，表格列为「项目」「内容」，项目依次为「打印文件」「打印机」「打印设置」「提交人」「任务编号」。文件用实际任务名，打印机可附返回的楼层，设置显示已知页数、份数和单双面。数据尚未返回时写「待核实」。状态使用 `display.status_zh` 和实际任务记录，失败时简要说明 `error_msg`。仅在设备确认完成时回复「设备已确认完成」。对打印记录和任务管理使用简短中文结果，可附相应后台链接。

正文打印示例请求 `把下面这段会议通知打印到 28 楼，1 份，提交人张三：明天上午 9 点在 3 号会议室开会。`。用于打印的正文是冒号之后的通知，聊天中同时返回本次任务的状态与表格。
