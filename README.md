# Shanghai Gas for Home Assistant

上海燃气 Home Assistant 自定义集成。当前基于上海燃气微信小程序接口实现，支持通过抓包得到的 `token`、户号和 `companyCode` 查询燃气账单/用气记录，并在 Home Assistant 中生成传感器实体。

## 功能

- 本次用气量，单位 `m³`，来自接口字段 `consumption`
- 最近账单金额，单位 `CNY`
- 余额和待缴金额，来自接口 `gasBillExt`
- 本次抄表读数，单位 `m³`，来自接口字段 `currentReading`
- 最近账期和下次抄表日期
- 历史账单/用气记录作为脱敏属性附加在账单金额实体上

## 安装

### HACS 自定义仓库

1. 打开 HACS。
2. 进入 `Integrations`。
3. 点击右上角菜单，选择 `Custom repositories`。
4. 填入本仓库 GitHub 地址。
5. Category 选择 `Integration`。
6. 添加后搜索 `Shanghai Gas` 并安装。
7. 重启 Home Assistant。

### 手动安装

把 `custom_components/sh_gas` 复制到 Home Assistant 配置目录：

```text
/config/custom_components/sh_gas
```

然后重启 Home Assistant。

## 配置

在 Home Assistant 中进入：

```text
设置 -> 设备与服务 -> 添加集成 -> Shanghai Gas
```

需要填写：

- `token`：抓包中账单接口请求头里的 `token`。
- 户号：抓包和返回数据中的 `customerId`。
- `companyCode`：账单接口请求体里的 `companyCode`，当前抓包为 `DZ`。

集成不会主动登录，只会使用配置的 `token` 调用 `/v1/accountingService/queryBills` 查询账单。

同一个户号只能添加一次。

## 实体

默认生成以下实体：

- `sensor.*_latest_consumption`
- `sensor.*_latest_amount`
- `sensor.*_balance`
- `sensor.*_pending_amount`
- `sensor.*_current_reading`
- `sensor.*_latest_period`
- `sensor.*_next_read_date`

默认刷新间隔为 6 小时，避免对上海燃气接口产生不必要的高频请求。

## 隐私

`token`、户号、姓名、地址、openid、unionid 都属于敏感信息。集成不会主动把这些字段写入实体属性，diagnostics 也会脱敏。

提交 issue 或分享日志时，请先移除：

- 户号
- 姓名
- 地址
- token
- openid / unionid
- cookie

`Reqable.md` 中的抓包内容也应在提交到公开 GitHub 仓库前完成脱敏。

## 当前限制

- 当前只实现了抓包中已有的账单查询接口。
- `token` 过期后需要重新抓包并更新配置；后续可以补充验证码登录和 reauth 流程。
- 暂不支持自动绑定户号、解绑银行卡、缴费或短信验证码流程。
- 如果上海燃气调整小程序接口、请求头或风控策略，需要重新抓包并更新 API 客户端。

## 开发

不经过 Home Assistant，直接验证上海燃气接口：

```bash
python3 scripts/query_sh_gas.py
```

也可以通过 stdin 传 JSON：

```bash
printf '%s\n' '{"token":"抓包里的token","customer_id":"户号","company_code":"DZ"}' | python3 scripts/query_sh_gas.py
```

脚本会打印接近 Home Assistant 实体结构的 JSON，方便确认接口请求和字段解析是否正确。

基础检查：

```bash
python3 -m compileall custom_components tests
python3 -m pytest
python3 -m ruff check .
```
