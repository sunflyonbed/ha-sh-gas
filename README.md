# Shanghai Gas for Home Assistant

上海燃气 Home Assistant 自定义集成。当前基于上海燃气网站/微信小程序接口实现，支持使用账号密码登录，自动获取图形验证码并通过外部 OCR API 识别，然后查询燃气账单/用气记录并在 Home Assistant 中生成传感器实体。

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

- 手机号：上海燃气账号手机号。
- 密码：上海燃气账号密码。集成会在配置验证时转换为 MD5 后保存。
- 户号：抓包和返回数据中的 `customerId`。
- OCR API 地址：完整验证码识别接口地址，例如 `http://127.0.0.1:9898/ocr`。集成会以 `multipart/form-data` POST 到该地址，只提交 `image` 字段，值为上海燃气接口返回的 `base64Image` 原始字符串，并从响应中的 `data`、`result`、`text`、`captcha`、`captcha_code` 或字符串类型的 `code` 字段读取验证码文本。`{"code": 0, "data": "AB12"}` 会被视为成功响应。
- `companyCode`：账单接口请求体里的 `companyCode`，当前抓包为 `DZ`。

OCR 服务可以在 Home Assistant 中安装 [sml2h3/ddddocr-fastapi](https://github.com/sml2h3/ddddocr-fastapi)。安装并启动后，先访问 `http://HAIP:8000/docs` 检查是否能看到 Swagger 页面；如果能打开，集成中的 OCR API 地址通常填写 `http://HAIP:8000/ocr`。

集成会调用 `/v1/thirdparty/common/img/getImgAuthCode` 获取图形验证码，把验证码图片发送到配置的 OCR API，然后调用 `/v1/user/common/doLogin` 登录。登录返回的运行时 `token` 用于调用 `/v1/accountingService/queryBills` 查询账单；如果后续刷新时登录状态失效，集成会自动重新登录。

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

默认刷新间隔为 1 天，避免对上海燃气接口产生不必要的高频请求。

## 隐私

手机号、密码、密码 MD5、运行时 `token`、户号、姓名、地址、openid、unionid 都属于敏感信息。集成不会主动把这些字段写入实体属性，diagnostics 也会脱敏。

提交 issue 或分享日志时，请先移除：

- 户号
- 手机号
- 密码 / 密码 MD5
- 姓名
- 地址
- 运行时 token
- openid / unionid
- cookie

`Reqable.md` 中的抓包内容也应在提交到公开 GitHub 仓库前完成脱敏。

## 当前限制

- 当前只实现了账号密码登录、外部 OCR API 图形验证码识别和账单查询接口。
- 图形验证码识别由外部 OCR API 服务负责；HA 集成只传递验证码图片并读取返回文本。
- 暂不支持自动绑定户号、解绑银行卡、缴费或短信验证码流程。
- 如果上海燃气调整小程序接口、请求头或风控策略，需要重新抓包并更新 API 客户端。

## 开发

不经过 Home Assistant，直接验证上海燃气接口：

```bash
python3 scripts/query_sh_gas.py
```

也可以通过 stdin 传 JSON：

```bash
printf '%s\n' '{"mobile":"手机号","password":"原始密码","customer_id":"户号","company_code":"DZ","ocr_api_url":"http://127.0.0.1:9898/ocr"}' | python3 scripts/query_sh_gas.py
```

脚本会获取图形验证码，调用外部 OCR API 识别并登录，然后打印接近 Home Assistant 实体结构的 JSON，方便确认接口请求和字段解析是否正确。

基础检查：

```bash
python3 -m compileall custom_components tests
python3 -m pytest
python3 -m ruff check .
```
