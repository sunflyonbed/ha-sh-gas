# 上海燃气 Home Assistant 集成开发计划

## 目标

参考 `ha-sh-water` 项目的结构，开发一个可通过 HACS 使用 GitHub 地址添加的 Home Assistant 自定义集成，用 Python 抓取上海燃气相关账单和用气数据，并在 Home Assistant 中以传感器实体展示。

本项目集成域名为 `sh_gas`，仓库名为 `ha-sh-gas`。当前 token 模式用户输入项为：

- `token`：账单接口请求头里的 `token`
- 户号：接口字段 `customerId`
- `companyCode`：账单接口请求体字段，当前抓包为 `DZ`

## 当前接口

抓包文件 `Reqable.md` 已包含两个核心接口。当前集成暂时只使用账单接口，登录接口因为验证码问题后续再接入：

- 登录：`POST https://mpshgas.huaqi-it.com.cn/v1/user/common/doLogin`
- 账单：`POST https://mpshgas.huaqi-it.com.cn/v1/accountingService/queryBills`

旧 qrcode 登录请求使用：

```json
{
  "method": "JSCODE",
  "qrCode": "<qrcode>",
  "origin": "MiniPro",
  "timestamp": 1783671186813
}
```

旧 qrcode 登录响应返回：

- `token`
- `accountList[]`
- `accountList[].customerId`
- `accountList[].companyCode`

账单请求使用：

```json
{
  "companyCode": "DZ",
  "customerId": "<户号>",
  "origin": "MiniPro",
  "timestamp": 1783671190649
}
```

## 最小可用版本

已实现 Home Assistant 自定义集成骨架：

```text
custom_components/sh_gas/
├── __init__.py
├── api.py
├── config_flow.py
├── const.py
├── coordinator.py
├── diagnostics.py
├── entity.py
├── manifest.json
├── sensor.py
├── strings.json
└── translations/
    ├── en.json
    └── zh-Hans.json
```

配置流程：

1. 用户通过 UI 添加 `Shanghai Gas`。
2. 输入 `token`、户号和 `companyCode`。
3. 集成调用账单接口验证配置。
4. 创建 config entry 并生成传感器。

## 传感器

- 本次用气量：`consumption`，单位 `m³`
- 最近账单金额：`money`，单位 `CNY`
- 余额：`gasBillExt.balance`，单位 `CNY`
- 待缴金额：`gasBillExt.money`，单位 `CNY`
- 本次抄表读数：`currentReading`，单位 `m³`
- 最近账期：`billYM`
- 下次抄表日期：`gasBillExt.nextReadDate` 或账单 `nextReadDate`

历史账单作为账单金额实体的属性输出，不为每期账单创建大量实体。

## 隐私与风险

- `Reqable.md` 中仍包含真实个人信息和 token，提交公开 GitHub 仓库前必须脱敏。
- 户号、token、openid、unionid、姓名、地址都必须视为敏感数据。
- diagnostics 已对配置项做脱敏。
- `token` 过期后需要用户更新配置。后续需要继续抓包确认 pwd 登录验证码接口、token 有效期，以及是否存在 refresh token 或其他持久登录凭据。

## 验证命令

```bash
python3 -m compileall custom_components tests
python3 -m pytest
python3 -m ruff check .
```
