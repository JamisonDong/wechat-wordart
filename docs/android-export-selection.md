# Android 聊天记录导出选型（待定）

> 状态：`TODO` — 回家后实测再定案，当前保留选型不阻塞主流程。
> 更新：2026-08-31

## 背景
项目已打通 `Mac mini/NAS → pipeline → eink.bmp → ESP32` 链路（`pipeline.py:33` / `wechat_wordart/renderer/eink_renderer.py:1` / `wechat_wordart/server/http_server.py:65`），
唯一卡点是 Android 微信本地数据库为 `SQLCipher` 加密，需先导出为 `wechat_wordart/parser/txt_parser.py:31` / `csv_parser.py:14` 可识别的 `TXT/CSV`。

## 候选方案（GitHub 社区）

| 方案 | 仓库 | 核心原理 | Android 路径 | 输出 | 适配成本 | 备注 |
|------|------|----------|--------------|------|----------|------|
| A | `93857536-pixel/WeChatExporter` | LLDB 内存抓 key，解密 `xwechat_files` | Android → Mac/Win 微信同步后在电脑端导出 | `TXT/CSV/JSON` | 低，TXT 零改动 | 新版，适配微信 4.1.7-4.1.11，推荐 Mac 用户首选 |
| B | `chang-xinhai/WxEcho` | Mach VM 抓 key，纯 CLI | 同 A，读 Mac `xwechat_files` | `TXT/CSV/JSON` | 低，`wxecho export -n` | Apple Silicon 原生，适合放 NAS 定时 |
| C | `shixiaogaoya/MemoTrace` (`LC044/WeChatMsg`) | PC 数据库解密+年报 | Win 微信同步后导出 | `HTML/Word/CSV/TXT` | 中，CSV 已兼容 | 老牌，需 Windows |
| D | `1eeBoom/WeFlow` | 实时抓取+HTTP API | Win 同步 | `JSON/HTML/TXT/CSV` | 中 | 功能多，含朋友圈 |
| E | `ppwwyyxx/wechat-dump` | root 拉 `EnMicroMsg.db` + IMEI+UIN 解密 | 需 root | `html` | 高 | 经典但不适合小白，仅作兜底 |

> 已知失效：`xaoyaoo/PyWxDump` 原库于 2025-10-20 因微信律师函删库，仅保留声明页，请勿再用原地址。

## 参考决策
- 用户环境：`Android 主力 + Mac mini 可作服务器`
- 倾向：方案 A 或 B（Mac 本地解密，无需 root，无需借 iPhone）
- 待验证：回家后实测 `A` 的 DMG（`WeChatExporter-macOS-arm64.dmg`）与 `B` 的 `wxecho doctor` 在当前微信版本下的抓 key 成功率。

## 下一步
- [ ] 在 Mac 上安装微信 4.x 并完成 Android 聊天迁移同步
- [ ] 分别试跑 A / B 各导出一次 `TXT`，对比 `pipeline.py --input` 词频是否正常
- [ ] 若导出为 `HTML/JSON`，新增 `wechat_wordart/parser/html_parser.py` 或 `sqlite_parser.py` 做一键转换
- [ ] 选定后更新 `README.md` 的“导出微信聊天记录”章节，并固化到 `config.example.yaml:input.path`

## 暂不交付
- ESP32 固件 `firmware/esp32_wordart/`（等导出格式定案后再联调，避免重复适配）
