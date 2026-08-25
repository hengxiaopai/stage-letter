# WECHAT-TEST-ACCOUNT.md — 微信小程序测试号注册指南

> **本指南给非微信小程序开发者**。Gate 0A 的前置条件:你必须注册一个**测试号**,申请一个**订阅消息模板**,然后才能跑实验脚本。
>
> 预计耗时:注册 10-15 分钟 + 模板审核 1-3 工作日。

---

## 1. 注册测试号(10-15 分钟)

### 1.1 打开注册页

浏览器访问: <https://mp.weixin.qq.com/wxamp/registration?action=personal>

或者:微信公众平台首页 → 立即注册 → 小程序

### 1.2 选择"个人"类型

测试阶段选个人类型即可,不需要企业认证。

> 如果你后续要正式上线,需要企业主体。Gate 0A 阶段**不影响**。

### 1.3 填写资料

- **邮箱**:未注册过微信公众平台的邮箱(每个邮箱只能注册一个小程序)
- **密码**:自己设
- **验证码**:邮箱收到的

### 1.4 登录后台

注册成功后登录: <https://mp.weixin.qq.com>

记下两个重要字段(后续要填到 `.env`):

- **APPID**:在"开发管理" → "开发设置" → "开发者ID"
  形如 `wx1234567890abcdef`

- **AppSecret**:同一页面,需要"生成"(只有生成时能完整看到,丢失需重置)
  形如 `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`

> ⚠️ **AppSecret 必须立刻保存**,关闭弹窗就再也看不到完整值了。丢失只能重置。

---

## 2. 申请订阅消息模板(审核 1-3 工作日)

### 2.1 进入订阅消息

后台 → 订阅消息 → 公共模板库

### 2.2 搜索或新建模板

搜索"开播提醒"或"通知",找一个接近的。

如果没有,选择**"新建模板"**(个人测试号通常允许自定义)。

### 2.3 建议的模板字段

```
模板标题: 开播提醒
模板内容:
  {{thing1.DATA}}
  开播平台:{{thing2.DATA}}
  开播时间:{{time3.DATA}}
```

字段说明:
- `thing1`:20 字内,**放主播名**(例:小杨哥)
- `thing2`:20 字内,**放平台**(例:抖音)
- `time3`:**必须** yyyy-MM-dd HH:mm 格式,放开播时间

### 2.4 记录模板 ID

申请通过后,在"我的模板"里能看到模板 ID。

形如:`aBcD-eFgHiJkLmNoPqRsT-1234567890`

> 模板审核未通过时,Gate 0A 的实验 1/2/3 跑不通。T2 / T4 / T5 等不依赖真实发送的测试可以先跑。

---

## 3. 配置 `experiments/.env`

```bash
# 在 stage-letter/experiments/ 目录下
cp .env.example .env

# 编辑 .env,填入实际值
```

内容示例:

```bash
# 微信小程序测试号
WX_APPID=wx1234567890abcdef
WX_SECRET=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

# 订阅消息模板 ID(申请通过后填)
WX_TEMPLATE_LIVE_START=aBcD-eFgHiJkLmNoPqRsT-1234567890
```

**注意**:
- `.env` 已 gitignore,**禁止提交到 git**
- 不要把 AppSecret 发到群里或贴到 issue

---

## 4. 用 wx.login 拿 code(每次运行都需要新 code)

### 4.1 下载微信开发者工具

<https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html>

### 4.2 创建项目

1. 打开开发者工具,扫码登录(用你注册时绑定的微信号)
2. 新建项目 → 选"小程序"
3. 填入你的 **APPID**(不是测试号)
4. 后端服务选"不使用云服务"
5. 项目名随便,例:`stage-letter-test`

### 4.3 加 wx.login 代码

打开项目里的 `app.js`,**完全替换**为:

```js
App({
  onLaunch() {
    wx.login({
      success: (res) => {
        console.log('=== CODE START ===')
        console.log(res.code)
        console.log('=== CODE END ===')
        console.log('复制 CODE START 和 CODE END 之间的内容')
      }
    })
  }
})
```

### 4.4 拿 code

1. 在开发者工具左侧"模拟器"或"真机调试"中,点击"编译"
2. 右侧"控制台"里会显示 `=== CODE START ===` 和 `=== CODE END ===`
3. **复制中间那串**(类似 `0c3b...一长串...xyz`)
4. **5 分钟内**粘贴到 `wechat_grant_demo.py` 的提示里

> ⚠️ code 5 分钟过期 + 一次性使用。每次跑实验都要重新拿。

---

## 5. 运行 Gate 0A 脚本

```bash
cd stage-letter/experiments
pip install httpx

# 跑主实验(交互式,需要手机配合)
python wechat_grant_demo.py

# 跑信任测试(部分场景可自动化)
python wechat_trust_test.py
```

跟着提示走完,把结果填到 [`reports/wechat_grant.md`](./reports/wechat_grant.md)。

---

## 6. 常见问题

### Q: 个人测试号能发订阅消息吗?

A: 测试号的订阅消息功能**通常需要类目**。
- 如果提示"该类目不允许申请订阅消息",可能是个人主体限制
- 替代方案:
  - 用朋友的企业主体(用他的 APPID,AppSecret 自己拿)
  - 选"工具 > 效率"类目(订阅消息模板可申请)

### Q: 模板审核要多久?

A: 通常 1-3 个工作日。审核期间:
- Gate 0A 实验 1/2/3 阻塞
- 但 T2 / T4 / T5 不依赖真实发送,可以先跑
- WorkBuddy 可以同时开 Gate 0B 的 adapter 代码

### Q: AppSecret 忘了怎么办?

A: 在"开发管理 → 开发设置"里**重新生成**。
注意每次重新生成会导致旧的 access_token 全部失效。

### Q: 报错 `errcode 40001` / `42001` / `40014`?

A: 通常是:
- AppSecret 错了 → 检查 `.env`
- access_token 已过期 → 脚本会自动刷新,但若持续报,可能 AppSecret 错了

### Q: 报错 `errcode 43101` / `43102`?

A: 用户拒收或未订阅。属于正常业务错误,不算技术故障。

### Q: 我跑了一半想接着跑?

A: 重跑同一个脚本即可,会从已有 state 继续。但实验 1 之前必须 reset grant(脚本会自动)。

### Q: 我想重置实验从头来?

A: 删除 `experiments/data/grant_state.json` 即可。

### Q: 实验结果怎么记录?

A: 每个实验都会打印到控制台 + 写入 `data/grant_state.json`。
最终手动把关键结果填到 [`reports/wechat_grant.md`](./reports/wechat_grant.md) 的对应表格里。

---

## 7. 安全 checklist

- [ ] AppSecret 已保存到密码管理器 / 私密位置
- [ ] `.env` 文件已加入 `.gitignore`(默认已配置)
- [ ] 不在群里、issue、commit message 里贴 AppSecret
- [ ] 实验完成后,不需要清 `.env`(它只是测试号)
- [ ] 微信公众平台的"IP 白名单"先关(Gate 0 阶段用宽松策略)

---

## 8. 时间预估

| 步骤 | 耗时 | 阻塞? |
|------|------|--------|
| 注册测试号 | 10-15 min | 是(必须先有 APPID) |
| 申请模板 | 5 min 提交 + 1-3 天审核 | **是**(实验 1/2/3 阻塞) |
| 配 `.env` | 1 min | 否 |
| 装开发者工具 + wx.login | 10 min | 否 |
| 跑主实验 | 30 min | 取决于人配合速度 |
| 跑信任测试 | 5 min | 否 |
| 填报告 | 30 min | 否 |

**Gate 0A 阻塞总时长**:1-3 个工作日(等模板审核)。

**这段时间 WorkBuddy 可以并行**:写 Gate 0B 单平台 adapter prototype(不依赖微信)。