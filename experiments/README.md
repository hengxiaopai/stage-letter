# experiments/ — Gate 0 实验代码

> 每个脚本独立运行,有自己的输入输出。
> 跑完把结果填到 `../reports/` 对应的模板里。

## 当前实验(Gate 0A)

| 脚本 | 用途 | 状态 |
|------|------|------|
| `wechat_grant_demo.py` | 主实验:6 个 grant 模型场景 | 待用户准备 |
| `wechat_trust_test.py` | 信任测试:5 个服务端边界场景 | 待用户准备 |

## 前置条件

详见 [`../WECHAT-TEST-ACCOUNT.md`](../WECHAT-TEST-ACCOUNT.md):

1. 注册微信小程序**测试号**(个人类型即可,10-15 分钟)
2. 申请**订阅消息模板**(1-3 工作日审核)
3. 创建 `.env` 文件(参考 `.env.example`)
4. 用微信开发者工具触发 `wx.login` 拿 `code`

## 安装与运行

```bash
# 安装依赖
pip install httpx

# 跑主实验(交互式,需要手机配合)
python wechat_grant_demo.py

# 跑信任测试(部分场景可自动化)
python wechat_trust_test.py
```

## 输出

- `data/grant_state.json`:所有实验的状态(自动生成,可手动查看)
- 控制台:实时输出
- 报告:实验完成后填入 `../reports/wechat_grant.md`

## 安全注意

- `.env` 含真实 appid/secret,**禁止提交到 git**(`.gitignore` 已配置)
- `data/` 目录含测试数据,含 openid,默认 gitignore
- AppSecret 若误提交,立即在微信公众平台重置

## 重置实验

```bash
# 删 state 重新开始(慎用,会丢失所有 grant 历史)
rm data/grant_state.json
```

## 常见问题

### Q: code 报错

A: code 5 分钟内有效,且只能使用一次。每次都重新拿。

### Q: 模板审核中,代码能跑吗?

A: 实验 1-3 必须有模板。T2 / T5 不需要真实模板(测试错误响应)。

### Q: 个人测试号能发订阅消息吗?

A: 大多数情况可以,但需要类目支持。若报错 43101 持续,需要换企业主体。

### Q: 我跑了一半想接着跑?

A: 重新运行同一个脚本即可,会读已有 state 继续。但**实验 1 之前必须 reset grant**(脚本会自动)。