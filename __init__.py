from http.cookies import SimpleCookie
from typing import Any, List, Dict, Tuple, Optional
from app.core.config import settings
from apscheduler.schedulers.background import BackgroundScheduler

from app.schemas.types import SystemConfigKey
from app.utils.timer import TimerUtils
from app.plugins import _PluginBase
from app.log import logger
import pytz
from datetime import datetime, timedelta
from apscheduler.triggers.cron import CronTrigger
from app.core.event import EventManager
from p115 import P115Client


class UserSign115(_PluginBase):
    """
    插件模块基类，通过继续该类实现插件功能
    除内置属性外，还有以下方法可以扩展或调用：
    - stop_service() 停止插件服务
    - get_config() 获取配置信息
    - update_config() 更新配置信息
    - init_plugin() 生效配置信息
    - get_data_path() 获取插件数据保存目录
    """
    # 插件名称
    plugin_name: str = "115签到"
    # 插件描述
    plugin_desc: str = "115自动签到"
    # 插件版本
    plugin_version = "1.4"
    # 插件图标
    plugin_icon = "https://115.com/web_icon.jpg"
    # 插件顺序
    plugin_order: int = 100
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    event: EventManager = None

    _enabled: bool = False
    _cron: str = ""
    _onlyonce: bool = False
    _notify: bool = False
    _start_time: int = None
    _end_time: int = None
    _cookie: str = ""
    _updateSys115Cookie: bool = False
    _client: P115Client = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()
        if config:
            self.event = EventManager()
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify")
            self._cookie = config.get("cookie") or ""
            self._updateSys115Cookie = config.get(
                "updateSys115Cookie") or False
            # 保存配置
            self.__update_config()
        if self._cookie is None:
            self._cookie = ""
        # 链接 115
        if len(self._cookie) != 0:
            self._client = P115Client(self._cookie)
            if self._updateSys115Cookie:
                self.systemconfig.set(
                    SystemConfigKey.User115Params, UserSign115.__cookie_string_to_dict(self._cookie))
                logger.info("更新 sys  115的 cookie")

        # 加载模块
        if self._enabled or self._onlyonce:
            # 立即运行一次
            if self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info("115签到立即运行一次，立即运行一次")
                self._scheduler.add_job(func=self.sign_in, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(
                                            settings.TZ)) + timedelta(seconds=3),
                                        name="115自动签到")

                # 关闭一次性开关
                self._onlyonce = False
                # 保存配置
                self.__update_config()

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def sign_in(self):
        if len(self._cookie) == 0 or self._client is None:
            logger.warn("115签到失败，cookie必须设置")
            return
        sign_result = self._client.user_points_sign()
        logger.info(f"signStatus: {sign_result}")
        if sign_result["code"] != 0 or not isinstance(sign_result['data'], dict):
            logger.warn(f"查询签到状态不正确: {sign_result}")
            return
        sign_status = sign_result['data']['is_sign_today']
        logger.info(f"当前签到状态{sign_status}")
        if sign_status == 1:
            logger.info("115当天已经签到过，无需再次签到")
            self.post_message(title="115当天已经签到过，无需再次签到")
            return

        result = self._client.user_points_sign_post()
        if result is not None:
            if result["code"] == 0:
                logger.info(f"115签到成功: {result}")
                self.post_message(title="115签到成功！")
            else:
                logger.error(f"115签到失败: {result}")
                self.post_message(title="115签到失败！")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    @staticmethod
    def __cookie_string_to_dict(cookie_string: str):
        cookie = SimpleCookie()
        cookie.load(cookie_string)
        cookie_dict = {key: morsel.value for key, morsel in cookie.items()}
        return cookie_dict

    def __update_config(self):
        # 保存配置
        self.update_config(
            {
                "enabled": self._enabled,
                "notify": self._notify,
                "cron": self._cron,
                "onlyonce": self._onlyonce,
                "cookie": self._cookie,
                "updateSys115Cookie": self._updateSys115Cookie
            }
        )

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
        if self._enabled and self._cron:
            try:
                if str(self._cron).strip().count(" ") == 4:
                    return [{
                        "id": "UserSign115",
                        "name": "115自动签到",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "func": self.sign_in,
                        "kwargs": {}
                    }]
                else:
                    # 2.3/9-23
                    crons = str(self._cron).strip().split("/")
                    if len(crons) == 2:
                        # 2.3
                        cron = crons[0]
                        # 9-23
                        times = crons[1].split("-")
                        if len(times) == 2:
                            # 9
                            self._start_time = int(times[0])
                            # 23
                            self._end_time = int(times[1])
                        if self._start_time and self._end_time:
                            return [{
                                "id": "UserSign115",
                                "name": "115自动签到",
                                "trigger": "interval",
                                "func": self.sign_in,
                                "kwargs": {
                                    "hours": float(str(cron).strip()),
                                }
                            }]
                        else:
                            logger.error("115自动签到启动失败，周期格式错误")
                    else:
                        # 默认0-24 按照周期运行
                        return [{
                            "id": "UserSign115",
                            "name": "115自动签到",
                            "trigger": "interval",
                            "func": self.sign_in,
                            "kwargs": {
                                "hours": float(str(self._cron).strip()),
                            }
                        }]
            except Exception as err:
                logger.error(f"定时任务配置错误：{str(err)}")
        elif self._enabled:
            start = 10
            end = 23
            # 随机时间
            triggers = TimerUtils.random_scheduler(num_executions=1,
                                                   begin_hour=start,
                                                   end_hour=end,
                                                   max_interval=int(
                                                       (end - start) * 60 / 2),
                                                   min_interval=int((end - start) * 60 / 3))
            ret_jobs = []
            for trigger in triggers:
                ret_jobs.append({
                    "id": f"UserSign115|{trigger.hour}:{trigger.minute}",
                    "name": "115自动签到",
                    "trigger": "cron",
                    "func": self.sign_in,
                    "kwargs": {
                        "hour": trigger.hour,
                        "minute": trigger.minute
                    }
                })
            return ret_jobs
        return []

    def get_page(self) -> List[dict]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            },                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'updateSys115Cookie',
                                            'label': '更新系统cookie',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cookie',
                                            'label': '115客户端Cookie'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': 'cookie：'
                                                    '115客户端抓取的 cookie'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "cron": "",
            "auto_cf": 0,
            "onlyonce": False,
            "clean": False,
            "queue_cnt": 5,
            "sign_sites": [],
            "login_sites": [],
            "retry_keyword": "错误|失败"
        }

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
