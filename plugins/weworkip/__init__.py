import base64
import re
import os
import time
from urllib.parse import urljoin
import requests
from datetime import datetime, timedelta
import pytz
from typing import Any, List, Dict, Tuple, Optional
from app.core.event import eventmanager, Event
from app.schemas.types import EventType, MessageChannel, NotificationType
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.log import logger
from app.plugins import _PluginBase
from app.core.config import settings
from app.helper.cookiecloud import CookieCloudHelper

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

class WeWorkIP(_PluginBase):
    # 插件名称
    plugin_name = "企微配置IP"
    # 插件描述
    plugin_desc = "!!Docker用户请使用Docker版!!定时获取最新动态公网IP，配置到企业微信应用的可信IP列表里。"
    # 插件图标
    plugin_icon = "https://github.com/suraxiuxiu/MoviePilot-Plugins/blob/main/icons/micon.png?raw=true"
    # 插件版本
    plugin_version = "2.4.4"
    # 插件作者
    plugin_author = "suraxiuxiu"
    # 作者主页
    author_url = "https://github.com/suraxiuxiu/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "weworkip_"
    # 加载顺序
    plugin_order = 20
    # 可使用的用户级别
    auth_level = 2

    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    qr_path = 'QR.png'
    qr_path = os.path.join(script_dir, qr_path)
    if os.path.exists(qr_path):
        os.remove(qr_path)
    # 匹配ip地址的正则
    _ip_pattern = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
    # 获取ip地址的网址列表
    _ip_urls = [
        "https://myip.ipip.net",
        "https://ddns.oray.com/checkip",
        "https://ip.3322.net",
        "https://4.ipw.cn",
    ]
    # 当前ip地址
    _current_ip_address = "192.168.1.1"
    # 企业微信应用管理地址
    _wechatUrl = (
        f"https://work.weixin.qq.com/wework_admin/frame#/apps/modApiApp/00000000000"
    )
    _urls = []
    # 登录cookie
    _cookie_header = ""
    # 从CookieCloud或内置登录获取的cookie
    _cookie_from_CC = ""
    # 发送二维码给指定成员,为空则发送给全部成员
    _qr_send_users = ""
    # 覆盖已填写的IP,设置FALSE则添加新IP到已有IP列表里
    _overwrite = True
    # 使用旧无头模式
    _use_old_headless = False
    # 使用CookieCloud开关
    _use_cookiecloud = True
    # cookie有效检测
    _cookie_valid = False
    # IP更改成功状态,防止检测IP改动但cookie失效的时候_current_ip_address已经更新成新IP导致后面刷新cookie也没有更改企微IP
    _ip_changed = False
    # 刷新cookie间隔时间,默认5分钟,太久会导致cookie失效
    _refresh_cron = "*/5 * * * *"
    # 状态通知时间 
    _status_cron = "0 * * * *"
    #检测IP时间
    _check_cron = "*/11 * * * *"
    _enabled = False
    _onlyonce = False
    _cookiecloud = CookieCloudHelper()
    _code = 0
    _pattern = r"^#\d{6}$"
    #cookie失效后定时唤起登录  如果关闭则手动调用登录
    _schedule_login = False
    _driver = None
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 清空配置
        self._wechatUrl = ""
        self._cookie_header = ""
        self._qr_send_users = ""
        self._cookie_from_CC = ""
        self._overwrite = True
        self._use_old_headless = False
        self._use_cookiecloud = True
        self._cookie_valid = False
        self._ip_changed = True
        self._urls = []
        if config:
            self._enabled = config.get("enabled")
            self._check_cron = config.get("cron")
            self._status_cron = config.get("status_cron")
            self._onlyonce = config.get("onlyonce")
            self._wechatUrl = config.get("wechatUrl")
            self._cookie_header = config.get("cookie_header")
            self._qr_send_users = config.get("qr_send_users")
            self._cookie_from_CC = config.get("cookie_from_CC")
            self._overwrite = config.get("overwrite")
            self._use_old_headless = config.get("use_old_headless")
            self._current_ip_address = config.get("current_ip_address")
            self._use_cookiecloud = config.get("use_cookiecloud")
            self._schedule_login = config.get("schedule_login")
            self._cookie_valid = config.get("cookie_valid")
            self._ip_changed = config.get("ip_changed")
        self._urls = self._wechatUrl.split(",")
        if self._ip_changed == None:
            self._ip_changed = True
        if self._cookie_valid == None:
            self._cookie_valid = False
        if self._use_cookiecloud == None:
            self._use_cookiecloud = True
        if self._overwrite == None:
            self._overwrite = True
        if self._use_old_headless == None:
            self._use_old_headless = False
        if self._schedule_login == None:
            self._schedule_login = False
        if self._status_cron == None:
            self._status_cron = "0 * * * *"
        if self._check_cron == None:
           self._check_cron = "*/11 * * * *"
        # 停止现有任务
        self.stop_service()

        if self._enabled or self._onlyonce:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 运行一次定时服务
            if self._onlyonce:
                logger.info("立即检测公网IP")
                self._scheduler.add_job(
                    func=self.check,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                    + timedelta(seconds=3),
                    name="检测公网IP",
                )
                # 关闭一次性开关
                self._onlyonce = False

            if not self._cookie_valid:
                    self._scheduler.add_job(
                        func=self.refresh_cookie,
                        trigger="date",
                        run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                        + timedelta(seconds=1),
                        name="插件初始化检测到缓存失效"
                    )
            else:
                self.create_refresh_job()
                
            if not self._schedule_login:
                self._scheduler.add_job(
                            func=self.send_cookie_status,
                            trigger=CronTrigger.from_crontab(self._status_cron),
                            name="cookie失效通知",
                            id="send_status"
                        )
                if not self._cookie_valid:
                    self._scheduler.add_job(
                    func=self.send_cookie_status,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                    + timedelta(seconds=3),
                    name="初始化检测失效通知",
                )
            
            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()
        self.__update_config()

    @eventmanager.register(EventType.PluginAction)
    def check(self, event: Event = None):
        """
        检测函数
        """
        if not self._enabled:
            logger.error("插件未开启")
            return

        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "weworkip":
                return
            logger.info("收到命令，开始检测公网IP ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始检测公网IP ...",
                              userid=event.event_data.get("user"))

        logger.info("开始检测公网IP")
        if self.CheckIP():
            self.ChangeIP()
            self.__update_config()

        logger.info("检测公网IP完毕")
        if event:
            self.post_message(channel=event.event_data.get("channel"),
                              title="检测公网IP完毕",
                              userid=event.event_data.get("user"))
        
    def CheckIP(self):
        if not self._cookie_valid:
            logger.error("cookie以过期,跳过IP检测")
            return False
        if not self._ip_changed:  # 上次IP变更没有改动到企微 再次请求该IP
            return True
        for url in self._ip_urls:
            ip_address = self.get_ip_from_url(url)
            if ip_address != "获取IP失败":
                logger.info(f"IP获取成功: {url}: {ip_address}")
                break
            else:
                logger.error(f"请求网址失败: {url}")
        if ip_address == "获取IP失败":
            logger.error("获取IP失败") 
            return False      
        if ip_address != self._current_ip_address:
            logger.info("检测到IP变化")
            self._current_ip_address = ip_address
            self._ip_changed = False
            return True
        else:
            # logger.info("公网IP未变化")
            return False

    def get_ip_from_url(self, url):
        try:
            # 发送 GET 请求
            response = requests.get(url)

            # 检查响应状态码是否为 200
            if response.status_code == 200:
                # 解析响应 JSON 数据并获取 IP 地址
                ip_address = re.search(self._ip_pattern, response.text)
                if ip_address:
                    return ip_address.group()
                else:
                    return "获取IP失败"
            else:
                return "获取IP失败"
        except Exception as e:
            logger.warning(f"{url}获取IP失败,Error: {e}")
            return "获取IP失败"

    def ChangeIP(self):
        logger.info("开始请求企业微信管理更改可信IP")
        if not self.check_connect():
            logger.error("网络连接失败,跳过本次缓存保活")
        options = webdriver.EdgeOptions()
        if(self._use_old_headless):
            options.add_argument("--headless=old")
        else:
            options.add_argument("--headless")
        driver = webdriver.Edge(options=options)
        time.sleep(2)#旧版无头模式似乎会出问题,尝试等待解决
        driver.get(self._urls[0])
        time.sleep(1)
        driver.delete_all_cookies()
        cookies = self.get_cookie()
        if cookies == '':
                logger.error('cookie为空,请检查CC配置和插件手动填写项')
                driver.quit()
                return
        for cookie in cookies:
            name, value = cookie.split("=")
            driver.add_cookie({"name": name, "value": value})
        driver.get(self._urls[0])
        try:
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CLASS_NAME, "login_stage_title_text"))
            )
            logger.info("cookie有效校验成功")
            self._cookie_valid = True    
            self.__update_config()
        except Exception as e:
            logger.error("cookie失效,请重新获取")
            self._cookie_valid = False
            driver.quit()
            self.__update_config()
            return
        # 开始更改ip地址
        try:
            for index, url in enumerate(self._urls):
                driver.get(url)
                logger.info(f"正在更改第{index+1}个应用的可信IP")
                try:
                    setip = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH,'//div[contains(@class, "app_card_operate") and contains(@class, "js_show_ipConfig_dialog")]'))
                    )
                    setip.click()
                    inputArea = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, '//textarea[@class="js_ipConfig_textarea"]'))
                    )
                    confirm = driver.find_element(
                        By.XPATH,
                        '//a[@class="qui_btn ww_btn ww_btn_Blue js_ipConfig_confirmBtn"]'
                    )
                    if self._overwrite:
                        inputArea.clear()
                        inputArea.send_keys(self._current_ip_address)
                    inputArea.send_keys(f";{self._current_ip_address}")
                    confirm.click()
                    time.sleep(1)
                    logger.info(f"更改第{index+1}个应用的可信IP成功")
                except Exception as e:
                    logger.error(f"更改可信IP失败:{e}")
            self._ip_changed = True
        except Exception as e:
            logger.error(f"更改可信IP失败: {e}")
        self.__update_config()
        driver.quit()

    def refresh_cookie(self,_login=True):
        logger.info("开始刷新企业微信缓存")
        if not self.check_connect():
            logger.error("网络连接失败,跳过本次缓存保活")
            return
        try:
            options = webdriver.EdgeOptions()
            if(self._use_old_headless):
                options.add_argument("--headless=old")
            else:
                options.add_argument("--headless")
            driver = webdriver.Edge(options=options)
            time.sleep(2)#旧版无头模式似乎会出问题,尝试等待解决
            driver.get(self._urls[0])
            WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'login_qrcode')]"))
                )
            driver.delete_all_cookies()
            cookies = self.get_cookie()
            if cookies == '' or cookies == ['']:
                    logger.error('cookie为空,请检查CC配置和插件手动填写项')
                    driver.quit()
                    self._cookie_valid = False
                    if self._schedule_login:
                        if self._scheduler.get_job("refresh_cookie"):
                            self._scheduler.remove_job("refresh_cookie")
                        if not self._scheduler.get_job("wwlogin") and _login:
                            self.create_login_job()
                    else:
                        if not self._scheduler.get_job("refresh_cookie"):
                            self.create_refresh_job()
                    return
            for cookie in cookies:
                name, value = cookie.split("=")
                driver.add_cookie({"name": name, "value": value})
            driver.get(self._urls[0])
            try:
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CLASS_NAME, "login_stage_title_text"))
                )
                logger.info("cookie有效校验成功")
                self._cookie_valid = True
            except Exception as e:
                logger.error("cookie失效,请重新获取")
                self._cookie_valid = False
                if self._schedule_login:
                    if self._scheduler.get_job("refresh_cookie"):
                        self._scheduler.remove_job("refresh_cookie")
                    if not self._scheduler.get_job("wwlogin") and _login:
                        self.create_login_job()
                else:
                    if not self._scheduler.get_job("refresh_cookie"):
                        self.create_refresh_job()
            driver.quit()
            self.__update_config()
        except Exception as e:
            logger.error(f"cookie校验失败:{e}")
            if "session not created" in str(e):
                logger.info("浏览器启动失败,跳过本次刷新")
            elif isinstance(e, TimeoutException) or "Timeout" in str(e):
                logger.info("检测可能连接超时,跳过本次刷新") 
            else:
                self._cookie_valid = False
            self.__update_config()
        finally:
            if 'driver' in locals():
                driver.quit()

    def get_cookie(self):
        cookie_header = ""
        try:
            if self._cookie_valid:
                return self._cookie_from_CC
            if self._use_cookiecloud:
                logger.info("尝试从CookieCloud同步企微cookie ...")
                cookies, msg = self._cookiecloud.download()
                if not cookies:
                    logger.error(
                        f"CookieCloud获取cookie失败,将使用手动配置cookie,失败原因：{msg}"
                    )
                    cookie_header = self._cookie_header.split(";")
                else:
                    for domain, cookie in cookies.items():
                        if domain == ".work.weixin.qq.com":
                            cookie_header = cookie.split(";")
                            break
                    if cookie_header == "":
                        cookie_header = self._cookie_header.split(";")
            else:
                cookie_header = self._cookie_header.split(";")
            self._cookie_from_CC = cookie_header
            self.__update_config()
            return cookie_header
        except Exception as e:
            logger.error(f"获取cookie失败:{e}")
            return cookie_header

    def login(self):
        logger.info("开始登录企业微信")
        self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "开始登录企业微信",userid=self._qr_send_users)
        logger.info("进行一次缓存检测")
        self.refresh_cookie(_login = False)
        if self._cookie_valid:
            logger.info("已使用其他有效缓存,跳过登录")
            if not self._scheduler.get_job("refresh_cookie"):
                self.create_refresh_job()
            if self._scheduler.get_job("wwlogin"):
                self._scheduler.remove_job("wwlogin")
            return
        try:
            options = webdriver.EdgeOptions()
            if(self._use_old_headless):
                options.add_argument("--headless=old")
            else:
                options.add_argument("--headless")
            driver = webdriver.Edge(options=options)
            self._driver = driver
            try:
                driver.get(self._urls[0])
                iframe_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'login_qrcode')]"))
                )
                driver.switch_to.frame(iframe_element)
                qr_img_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "qrcode_login_img"))
                )
                time.sleep(1)
                qr_img_relative_url = qr_img_element.get_attribute("src")
                base_url = driver.current_url
                absolute_url = urljoin(base_url, qr_img_relative_url)
                self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "点击扫描二维码登录企业微信",image=absolute_url,link=absolute_url,userid=self._qr_send_users)
                response = requests.get(absolute_url)
                if response.status_code == 200:
                    with open(self.qr_path, "wb") as file:
                        file.write(response.content)
                    logger.info("打开插件详情扫描二维码登录企业微信")
                else:
                    logger.info("无法下载二维码图片：", response.status_code)
                current_url = driver.current_url
                try:
                    WebDriverWait(driver, 90).until(EC.url_changes(current_url))
                    if 'mobile_confirm' in driver.current_url:
                        driver.switch_to.default_content()
                        #检测到验证页面  进入验证码流
                        self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "检测到登录验证，请以 #123456 的格式回复验证码，两分钟后超时",userid=self._qr_send_users)
                        logger.info("检测到登录验证，进入验证流程")
                        _wait_time = 0
                        while 'mobile_confirm' in driver.current_url:
                            self._code = 0
                            while self._code == 0:
                                time.sleep(2)
                                _wait_time += 2
                                if _wait_time > 120:
                                    raise ValueError("验证超时,终止本次登录")
                            input_element = WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "input.inner_input"))
                            )
                            input_element.send_keys(self._code)
                            WebDriverWait(driver, 10).until(
                                lambda driver: 
                                    # 检查登录失败提示是否显示
                                    driver.find_elements(By.XPATH, "//div[contains(@class, 't-is-error') and contains(text(), '验证码错误')]") or
                                    'mobile_confirm' not in driver.current_url
                            )
                            if 'mobile_confirm' in driver.current_url:
                                self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "登录失败,请检查验证码并重新发送",userid=self._qr_send_users)
                                logger.info("登录失败,请检查验证码并重新发送")
                    cookies = driver.get_cookies()
                    self._cookie_from_CC = [f"{cookie['name']}={cookie['value']}" for cookie in cookies]
                    self._cookie_valid = True
                    self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "登录企业微信成功",userid=self._qr_send_users)
                    logger.info("登录企业微信成功")
                    if not self._scheduler.get_job("refresh_cookie"):
                        self.create_refresh_job()
                    if self._scheduler.get_job("wwlogin"):
                        self._scheduler.remove_job("wwlogin")
                except Exception as e:
                    logger.error(f"登录超时:{e}")
                    self.login_fail()
            except Exception as e:
                logger.error(f"登录失败:{e}")
                self.login_fail()
            driver.quit()
            self._driver = None
            self.__update_config()
            if os.path.exists(self.qr_path):
                os.remove(self.qr_path)
        except Exception as e:
            logger.error(f"登录失败:{e}")
            self.login_fail()
        finally:
            if 'driver' in locals():
                driver.quit()
    
    def create_refresh_job(self):
        logger.info("创建定时刷新企业微信缓存任务")
        try:
                self._scheduler.add_job(
                    func=self.refresh_cookie,
                    trigger=CronTrigger.from_crontab(self._refresh_cron),
                    name="延续企业微信cookie有效时间",
                    id="refresh_cookie"
                )
        except Exception as err:
                logger.error(f"定时刷新企业微信缓存任务配置错误：{err}")
                self.systemmessage.put(f"定时刷新企业微信缓存任务配置错误：{err}")
        
    def create_login_job(self):
        logger.info("唤起企业微信登录任务")
        try:
                self._scheduler.add_job(
                    func=self.login,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                    + timedelta(seconds=5),
                    name="唤起企业微信登录"
                    #id="wwlogin"
                )
        except Exception as err:
                logger.error(f"唤起企业登录任务配置错误：{err}")
                self.systemmessage.put(f"唤起企业登录配置错误：{err}")

    def login_fail(self):
        self._cookie_valid = False
        if self._schedule_login:
            self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "登录失败",text = "已开启自动登录，即将开始下一轮登录。",userid=self._qr_send_users)
            self.create_login_job()
        else:
            self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "登录失败",text = "如需再次登录，请回复\n#登录企业微信",userid=self._qr_send_users)    

    def check_connect(self):
        try:
            response = requests.get(self._urls[0], timeout=10)
            if response.status_code == 200:
                return True
            else:
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"连接失败: {e}")
            return False

    def __update_config(self):
        """
        更新配置
        """
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "cron": self._check_cron,
                "wechatUrl": self._wechatUrl,
                "cookie_header": self._cookie_header,
                "qr_send_users": self._qr_send_users,
                "cookie_from_CC": self._cookie_from_CC,
                "overwrite": self._overwrite,
                "use_old_headless": self._use_old_headless,
                "current_ip_address": self._current_ip_address,
                "use_cookiecloud": self._use_cookiecloud,
                "cookie_valid": self._cookie_valid,
                "ip_changed": self._ip_changed,
                "schedule_login": self._schedule_login,
                "status_cron":self._status_cron
            }
        )

    @eventmanager.register(EventType.UserMessage)
    def receive_message(self, event: Event):
        if not self._enabled:
            return
        text = event.event_data.get("text")
        if re.match(self._pattern, text):
            self._code = text[1:]
            logger.info(f"从MP应用收到验证码：{self._code}")
            return
        if text == "#登录企业微信":
            if self._cookie_valid:
                self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "缓存有效，无需登录",userid=self._qr_send_users)
                return
            self._scheduler.add_job(
                    func=self.login,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                    + timedelta(seconds=3),
                    name="登录企业微信",
                )
    
    def send_cookie_status(self):
        if not self._cookie_valid:
            self.post_message(channel=MessageChannel.Wechat,mtype=NotificationType.Plugin,title = "企业微信Cookie失效",text = "回复下述指令唤起一次登录\n#登录企业微信",userid=self._qr_send_users)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/weworkip",
                "event": EventType.PluginAction,
                "desc": "微信应用检测动态IP",
                "category": "",
                "data": {"action": "weworkip"},
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._check_cron:
            return [
                {
                    "id": "WeWorkIP",
                    "name": "微信应用自动配置动态公网IP",
                    "trigger": CronTrigger.from_crontab(self._check_cron),
                    "func": self.check,
                    "kwargs": {},
                }
            ]
        return []
            
    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即检测一次IP",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "overwrite",
                                            "label": "覆盖模式",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "use_cookiecloud",
                                            "label": "使用CookieCloud获取cookie",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "schedule_login",
                                            "label": "自动登录",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "use_old_headless",
                                            "label": "使用旧无头模式",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "检测IP周期",
                                            "placeholder": "*/11 * * * *",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "status_cron",
                                            "label": "Cookie失效通知周期 仅在关闭自动登录时生效",
                                            "placeholder": "0 * * * *",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookie_header",
                                            "label": "非必填项:COOKIE",
                                            "rows": 1,
                                            "placeholder": "非必须填写项。手动提取HeaderString格式的Cookie，仅在未使用CC和内置登录的情况下使用。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "wechatUrl",
                                            "label": "必填项:MP应用网址",
                                            "rows": 2,
                                            "placeholder": "企业微信应用的管理网址 多个地址用,分隔 地址类似于https://work.weixin.qq.com/wework_admin/frame#/apps/modApiApp/00000000000",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "qr_send_users",
                                            "label": "非必填项:指定企业微信成员ID接收登录二维码,不填则发送给所有成员",
                                            "rows": 2,
                                            "placeholder": "ID查看路径: 企业微信-工作台-管理企业-成员与部门管理-单击成员-账号的值",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "默认关闭自动登录，发送 #登录企业微信 至MP应用则可以唤起一次登录操作。如果需要验证手机，把验证码按照格式 #123456 发送到MP应用。",
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "若开启自动登录，Cookie失效后会自动循环登录流程。若未及时登录会导致MP应用聊天框被塞满二维码。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "默认开启CookieCloud，会优先从CC同步cookie使用，建议开启。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "覆盖模式: 开启后新IP会直接覆写到已填写的IP列表，关闭则把新IP添加到已有列表里。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "检测IP周期：获取动态公网IP的间隔，推荐几分钟检测一次，有新IP才会请求企业微信管理更改。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "旧无头模式：正常运行无需开启。如果出现无法启动浏览器，或者每次刷新缓存时桌面会出现白框，可尝试打开此开关。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "微信通知代理地址记得改回官方地址https://qyapi.weixin.qq.com/并重启MP。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "具体介绍和其他问题在项目主页，推荐先看一次:https://github.com/suraxiuxiu/MoviePilot-Plugins",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ], {
            "enabled": False,
            "cron": "",
            "overwrite": False,
            "use_old_headless": False,
            "use_cookiecloud": True,
            "onlyonce": False,
            "cookie_header": "",
            "wechatUrl": "",
            "qr_send_users":"",
            "schedule_login": False,
            "status_cron" : "0 * * * *"
        }

    def get_page(self) -> List[dict]:
        if not self._enabled:
            vaild_text = "插件未启用"
            color =  "#F0E68C"
        elif self._cookie_valid:
            vaild_text = "缓存有效"
            color =  "#32CD32"
        else:
            vaild_text = "缓存失效"
            color =  "#ff0000"
            
        base_content = [
                            {
                                "component": "div",
                                "props": {
                                    "style": {
                                        "textAlign": "center" 
                                    }
                                },
                                "content": [
                                    {
                                        "component": "div",
                                        "text": vaild_text,
                                        "props": {
                                            "style": {
                                                "fontSize": "22px",
                                                "fontWeight": "bold",
                                                "color": "#ffffff",
                                                "backgroundColor": color,
                                                "padding": "8px",
                                                "borderRadius": "5px",
                                                "display": "inline-block", 
                                                "textAlign": "center",
                                                "marginBottom": "40px"
                                            }
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                        },
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {
                                                    "type": "info",
                                                    "variant": "tonal",
                                                    "text": "展示缓存状态。缓存失效后，在登录期间会展示登录二维码。",
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                        },
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {
                                                    "type": "info",
                                                    "variant": "tonal",
                                                    "text": "登录二维码也会发送到企业微信MP应用上，点开图片后可长按识别登录，此处二维码做备用登录。",
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                        },
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {
                                                    "type": "info",
                                                    "variant": "tonal",
                                                    "text": "二维码获取会有间隔，如果不显示二维码，关闭窗口等一会再进即可。",
                                                },
                                            }
                                        ],
                                    }
                                ],
                            }
                        ]
        img_src = "https://gitee.com/suraxiuxiu/image/raw/master/loading-M.gif"
        if self._cookie_valid or not self._enabled:
            qr_tip = ""
        elif os.path.exists(self.qr_path):
            qr_tip = "扫描二维码登录"
        else:
            qr_tip = "二维码被玛露希尔爆破了,等一会再来吧"
        
        if os.path.exists(self.qr_path) and self._enabled and not self._cookie_valid:
            with open(self.qr_path, 'rb') as image_file:
                image_data = image_file.read()
                base64_image = base64.b64encode(image_data).decode('utf-8')
                img_src = f"data:image/png;base64,{base64_image}"
        
        # 如果开启了内置登录，插入二维码的组件
        if not self._cookie_valid:
            base_content[1:1] = [ 
                                    {
                                        "component": "div",
                                        "text": qr_tip,
                                        "props": {
                                            "class": "text-center"
                                        }
                                    },
                                    {
                                        "component": "img",
                                        "props": {
                                            "src": img_src,
                                            "style": {
                                                "width": "auto",
                                                "height": "auto",
                                                "maxWidth": "100%",
                                                "maxHeight": "100%",
                                                "display": "block",
                                                "margin": "0 auto"
                                            }
                                        }
                                    }
                                ]
        return base_content

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._driver:
                self._driver.quit()
            if self._scheduler:
                if self._scheduler.running:
                    self._scheduler.shutdown()                 
                    self._scheduler.remove_all_jobs()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))