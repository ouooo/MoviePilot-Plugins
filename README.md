## 插件介绍
自动检测动态公网IP并应用到企业微信应用可信IP  
默认使用MP官方CookieCloud同步登录cookie，配置好官方的CC就能自动导入已同步的企业微信cookie  
微信通知代理地址记得改回https://qyapi.weixin.qq.com/ 并重启MP  
docker用户使用PW版  
Windows用户推荐使用普通版  
[手动提取cookie流程](#手动获取cookie流程)  
[多WAN多IP注意事项](#多wan多公网ip环境答疑)  

## 内置登录流程  
默认开启插件内置登录功能，当插件检测到登录cookie失效时，会先从CC获取cookie(防止顶掉其他地方登录)  
如果cookie仍旧失效，则定期唤起内置浏览器登录企业微信  
登录二维码通过MP服务器发送到企业微信MP应用端，打开二维码长按识别登录即可  
偶尔会出现二维码获取失败的情况，等待下一次发送即可，通常为几十秒间隔。  
![QQ20241021-134822](https://github.com/user-attachments/assets/90034114-e3f6-49dd-9a5b-2d9fe84d961f)  


特殊情况下，比如登录缓存失效了，而又没有及时在企业微信MP应用扫描登录，刚好动态IP又刷新，MP应用就无法获取最新登录二维码  
此时可打开MP网页端，打开插件扫描二维码登录即可。  
![image](https://github.com/user-attachments/assets/a9638858-fac8-441b-920f-4b8255bedfdc)  
## 手动获取cookie流程
使用浏览器cookie插件(([Cookie Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm))导出HeaderString格式的cookie,
登录企业微信后按下图所示导出cookie  
如果只使用手动抓取填写的cookie，后续如果用浏览器扫码登录企业微信，则上次抓取的cookie会失效，需重新抓取  
![微信截图_20240605203353](https://github.com/suraxiuxiu/MoviePilot-Plugins/assets/41566282/6f107697-5e96-4cef-821e-bb3df5b6e7a9)

## 多WAN、多公网IP环境答疑
插件目前不考虑适配这种环境，插件端无论请求多少次IP检测网站，都无法保证会返回两个宽带的IP。  
因为这是路由端负责的，可能请求一百次也是分配A宽带去访问并返回A宽带的IP，所以在路由端设置可以很容易解决这个问题。  
可以在路由器多WAN设置静态路由分配，把企业微信网址和下面的ip检测网址都指定同一条宽带出口。  
保证插件检测到的公网IP、企业微信应用的可信IP、MP请求企业微信应用时走的IP是同一个即可解决。  
插件所使用的IP检测网址：
```text
https://myip.ipip.net
https://ddns.oray.com/checkip
https://ip.3322.net
https://4.ipw.cn
