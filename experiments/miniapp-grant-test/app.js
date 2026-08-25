// StageLetter Gate 0A 测试小程序
// 用途:在真机上触发 wx.requestSubscribeMessage 授权弹窗,配合实验脚本验证 grant 模型
App({
  onLaunch() {
    // Step 0: wx.login 拿 code(给后端换 openid)
    wx.login({
      success: (r) => {
        console.log('LOGIN_CODE:', r.code)
        if (r.code) {
          // 把 code 显示在页面上,方便用户复制给后端
          const pages = getCurrentPages()
          if (pages.length > 0) {
            const page = pages[pages.length - 1]
            page && page.setData && page.setData({ loginCode: r.code })
          }
        }
      },
      fail: (e) => console.error('wx.login failed', e),
    })
  },
})
