# Yushu-OS Windows 便携版

解压完整 ZIP 后，在 PowerShell 中运行 `./Yushu.exe init`，然后运行
`./Yushu.exe run capture "记得明天写周报" --kind task` 和
`./Yushu.exe run today "今天做什么"`。加入 `--json` 可获得版本化机器输出。

数据默认放在当前 Windows 用户的 `%LOCALAPPDATA%\YushuOS\profiles\default`，
不写入程序解压目录。可用全局参数 `--home <目录>`、`--profile <名称>` 改变位置。
备份、恢复与迁移请先执行 `./Yushu.exe --help` 查看命令；恢复与迁移执行都需要
显式 `--confirm`。

Agent 可执行 `./Yushu.exe agent-handoff` 查看无凭证的接手信息，配置本地 stdio
MCP 命令为 `Yushu.exe mcp`。MCP 不开放审批工具；主人在 CLI 中通过
`approvals` 查看待审动作，再用 `approve <id> --confirm` 执行。

知识库只接 IMA。设置 `IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY` 和
`YUSHU_IMA_KB_IDS`（逗号分隔）后，可用 `diagnose --live` 做只读探测。
缺失凭证或 IMA 故障时，本地任务仍可运行；仅先前授权的摘要缓存可离线显示，
并标记时间及“部分结果”。旧 Markdown 目录不会自动检索、修改或上传。

文件 Capture 仅接收 Profile 的 `imports` 目录内 `.txt`／`.md` 文件，使用
`run capture "标题" --file idea.md`；网页 Capture 只接受事先列入
`YUSHU_WEB_ALLOWED_HOSTS` 的公开 HTTPS 域名，使用 `--url`，并限制大小和跳转。

当前发布门槛：飞书、Garmin 的新运行入口尚未装配；外部写入默认关闭。
不要把未装配能力的“可发现”误认为“可执行”。
