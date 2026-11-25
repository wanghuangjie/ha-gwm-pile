# 长城家充桩 for Home Assistant

将长城汽车 App 中国大陆账号下的家用充电桩接入 Home Assistant。集成通过长城云读取状态，提供启动和停止充电按钮。

## 支持范围

- 使用长城汽车 App 的中国大陆手机号和短信验证码登录。
- 账号需具备目标家充桩的使用权限。已在一台通过长城 App 分享的家充桩上验证状态读取和远程启停。
- 当前版本为 **0.1.1**，已在 Home Assistant Core **2026.9.3** 上验证。

## 安装与更新

1. 将 [`custom_components/gwm_pile`](custom_components/gwm_pile) 复制到 Home Assistant 的 `/config/custom_components/gwm_pile`。使用 ZIP 时，把包内的 `custom_components` 解压合并到 `/config`。
2. 重启 Home Assistant Core。
3. 首次安装时，打开 **设置 → 设备与服务 → 添加集成**，搜索 **长城家充桩**。

更新时覆盖集成文件并重启 Core。已有的集成配置、实体和有效登录会话可以继续使用。

## 登录与选择充电桩

1. 输入长城账号手机号，收到短信后在 Home Assistant 填写验证码。
2. 集成会从近期充电记录提取充电桩编号。只查到一台时会预选，确认后继续。查到多台时请选择目标桩。
3. 如果列表里没有目标桩，可以输入长城 App 上显示的充电桩编号。集成会读取该桩状态，验证账号是否有权访问。

近期充电记录可能缺少从未充电或近期未使用的桩。目标桩通过分享获得时，请先在长城 App 里接受分享并确认能看到该桩。

## Home Assistant 实体

| 类型 | 实体 |
| --- | --- |
| 二值传感器 | 已插枪、正在充电 |
| 传感器 | 充电电流、充电电压、本次充电量、本次充电时长、故障代码、账号充电记录数 |
| 按钮 | 启动充电、停止充电 |

充电桩状态每 30 秒查询一次，充电记录约每 5 分钟更新一次。长城云拒绝当前令牌时，集成会尝试自动续期。需要重新认证时，按 Home Assistant 的提示完成短信验证。备份恢复后如果缺少本地会话，可以在原集成上重新输入手机号和验证码。

## 提交问题

请附上 Home Assistant 版本、集成版本、充电桩型号、账号是否通过分享获得使用权限，以及脱敏后的报错。提交前请移除手机号、短信验证码、访问令牌、完整桩编号和位置。

## 致谢与第三方材料

云端认证客户端来自 [moryoav/ha-gwm-ev](https://github.com/moryoav/ha-gwm-ev)。上游版权和许可文本保留在 [vendor/LICENSE](custom_components/gwm_pile/vendor/LICENSE)。中国区签名与协议材料的来源和再分发说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
