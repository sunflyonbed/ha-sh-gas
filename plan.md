# 上海燃气 Home Assistant 集成开发计划

## 目标

参考 `ha-sh-water` 项目的结构，开发一个可通过 HACS 使用 GitHub 地址添加的 Home Assistant 自定义集成，用 Python 抓取上海燃气相关账单和用气数据，并在 Home Assistant 中以传感器实体展示。

本项目集成域名为 `sh_gas`，仓库名为 `ha-sh-gas`。当前账号密码模式用户输入项为：

- 手机号：上海燃气账号手机号
- 密码：上海燃气账号密码，配置验证时转换为 MD5 后保存
- 户号：接口字段 `customerId`
- `companyCode`：账单接口请求体字段，当前抓包为 `DZ`

## 当前接口

抓包文件 `Reqable.md` 已包含三个核心接口：

- 图形验证码：`GET https://web-api.shgas.com.cn/v1/thirdparty/common/img/getImgAuthCode`
- 登录：`POST https://web-api.shgas.com.cn/v1/user/common/doLogin`
- 账单：`POST https://mpshgas.huaqi-it.com.cn/v1/accountingService/queryBills`

账号密码登录请求使用：

```json
{
  "mobile": "<手机号>",
  "method": "PWD",
  "pwd": "<密码MD5>",
  "smsAuthCode": "",
  "imgid": "<验证码imgid>",
  "imgAuthCode": "<ddddocr识别结果>",
  "qrCode": "",
  "origin": "PC",
  "timestamp": 1783674357850
}
```

登录响应返回：

- 运行时 `token`
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
2. 输入手机号、密码、户号和 `companyCode`。
3. 集成获取图形验证码，使用本地 `ddddocr` 识别，调用账号密码登录接口获取 `token`。
4. 集成调用账单接口验证配置。
5. 创建 config entry 并生成传感器。

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

- `Reqable.md` 中仍包含真实个人信息、手机号和运行时 token，提交公开 GitHub 仓库前必须脱敏。
- 手机号、密码、密码 MD5、户号、运行时 token、openid、unionid、姓名、地址都必须视为敏感数据。
- diagnostics 已对配置项做脱敏。
- 登录状态失效后集成会用已保存的手机号和密码 MD5 自动重新登录。

## 验证命令

```bash
python3 -m compileall custom_components tests
python3 -m pytest
python3 -m ruff check .
```
