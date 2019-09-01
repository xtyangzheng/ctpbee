from datetime import datetime
from typing import Set, List, AnyStr
from warnings import warn

from ctpbee.constant import EVENT_INIT_FINISHED, EVENT_TICK, EVENT_BAR, EVENT_ORDER, EVENT_SHARED, EVENT_TRADE, \
    EVENT_POSITION, EVENT_ACCOUNT, EVENT_CONTRACT, EVENT_LOG, OrderData, SharedData, BarData, TickData, TradeData, \
    PositionData, AccountData, ContractData, LogData, Offset, Direction, OrderType
from ctpbee.event_engine.engine import EVENT_TIMER, Event
from ctpbee.func import helper
from ctpbee.helpers import check


class Action(object):
    """
    自定义的操作模板
    此动作应该被CtpBee, CtpbeeApi, AsyncApi, RiskLevel调用
    """

    def __new__(cls, *args, **kwargs):
        instance = object.__new__(cls)
        setattr(instance, "__name__", cls.__name__)
        return instance

    def __getattr__(self, item):
        message = f"尝试在{self.__name__}中调用一个不存在的属性{item}"
        warn(message)
        return None

    def __init__(self, app):
        self.app = app

    def buy(self, price: float, volume: float, origin: [BarData, TickData, TradeData, OrderData, PositionData],
            price_type: OrderType = "LIMIT", stop: bool = False, lock: bool = False):
        """
        开仓 多头
        """
        req = helper.generate_order_req_by_var(volume=volume, price=price, offset=Offset.OPEN, direction=Direction.LONG,
                                               type=OrderType.LIMIT, exchange=origin.exchange, symbol=origin.symbol)
        return self.send_order(req)

    def short(self, price: float, volume: float, origin: [BarData, TickData, TradeData, OrderData, PositionData],
              stop: bool = False, lock: bool = False, **kwargs):
        """
         开仓 空头
        """

        req = helper.generate_order_req_by_var(volume=volume, price=price, offset=Offset.OPEN,
                                               direction=Direction.SHORT,
                                               type=OrderType.LIMIT, exchange=origin.exchange, symbol=origin.symbol)
        return self.send_order(req)

    def sell(self, price: float, volume: float, origin: [BarData, TickData, TradeData, OrderData] = None,
             stop: bool = False, lock: bool = False, **kwargs):
        """ 平空头 """
        # todo 根据exchange和symbol找到仓位， 判断当前仓位是否满足可以平仓，同时判断平今和平昨，优先平今

        req_list = [helper.generate_order_req_by_var(volume=x[1], price=price, offset=x[0], direction=Direction.LONG,
                                                     type=OrderType.LIMIT, exchange=origin.exchange,
                                                     symbol=origin.symbol) for x in
                    self.get_req(origin.symbol, Direction.SHORT, volume, self.app)]

        return [self.send_order(req) for req in req_list]

    def cover(self, price: float, volume: float, origin: [BarData, TickData, TradeData, OrderData, PositionData],
              stop: bool = False, lock: bool = False, **kwargs):
        """
        平多头
        """
        req_list = [helper.generate_order_req_by_var(volume=x[1], price=price, offset=x[0], direction=Direction.SHORT,
                                                     type=OrderType.LIMIT, exchange=origin.exchange,
                                                     symbol=origin.symbol) for x in
                    self.get_req(origin.local_symbol, Direction.LONG, volume, self.app)]

        return [self.send_order(req) for req in req_list]

    @staticmethod
    def get_req(local_symbol, direction, volume: int, app):
        """
        generate the offset and volume
        生成平仓所需要的offset和volume
         """
        position: PositionData = app.recorder.position_manager.get_position_by_ld(local_symbol, direction)
        if not position:
            warn(f"{local_symbol}在{direction.value}上无仓位")
            return []
        if position.volume < volume:
            warn(f"{local_symbol}在{direction.value}上仓位不足")
            return []
        else:
            # 判断是否为上期所或者能源交易所 / whether the exchange is SHFE or INE
            if position.exchange.value not in app.config["TODAY_EXCHANGE"]:
                return [[Offset.CLOSE, volume]]

            if app.config["CLOSE_PATTERN"] == "today":
                # 那么先判断今仓数量是否满足volume /
                td_volume = position.volume - position.yd_volume
                if td_volume >= volume:
                    return [[Offset.CLOSETODAY, volume]]
                else:
                    return [[Offset.CLOSETODAY, td_volume], [Offset.CLOSEYESTERDAY, volume - td_volume]]
            elif app.config["CLOSE_PATTERN"] == "yesterday":
                if position.yd_volume >= volume:
                    """如果昨仓数量要大于或者等于需要平仓数目 那么直接平昨"""
                    return [[Offset.CLOSEYESTERDAY, volume]]
                else:
                    """如果昨仓数量要小于需要平仓数目 那么优先平昨再平今"""
                    return [[Offset.CLOSETODAY, position.yd_volume],
                            [Offset.CLOSEYESTERDAY, volume - position.yd_volume]]

    # 默认四个提供API的封装, 买多卖空等快速函数应该基于send_order进行封装 / default to provide four function
    @check(type="trader")
    def send_order(self, order, **kwargs):
        # 发单 同时添加滑点
        # todo:可能对于多种基础操作 需要自定义各种滑点---->
        order.price = order.price + self.app.config['SLIPPAGE']
        return self.app.trader.send_order(order, **kwargs)

    @check(type="trader")
    def cancel_order(self, cancel_req, **kwargs):
        return self.app.trader.cancel_order(cancel_req, **kwargs)

    @check(type="trader")
    def query_position(self):
        return self.app.trader.query_position()

    @check(type="trader")
    def query_account(self):
        return self.app.trader.query_accont()

    @check(type="trader")
    def transfer(self, req, type):
        """
        req currency attribute
        ["USD", "HKD", "CNY"]
        :param req:
        :param type:
        :return:
        """
        return self.app.trader.transfer(req, type=type)

    @check(type="trader")
    def query_account_register(self, req):
        self.app.trader.query_account_register(req)

    @check(type="trader")
    def query_bank_account_money(self, req):
        self.app.trader.query_bank_account_money(req)

    @check(type="trader")
    def query_transfer_serial(self, req):
        self.trader.query_transfer_serial(req)

    @check(type="trader")
    def query_bank(self):
        pass

    @check(type="market")
    def subscribe(self, local_symbol: AnyStr):
        """订阅行情"""
        if "." in local_symbol:
            local_symbol = local_symbol.split(".")[0]
        return self.app.market.subscribe(local_symbol)

    def __repr__(self):
        return f"{self.__name__} "


class CtpbeeApi(object):
    """
    数据模块/策略模块 都是基于此实现的
        如果你要开发上述插件需要继承此抽象demo
        usage:
        ## coding:
            class Processor(CtpbeeApi):
                ...

            data_processor = Processor("data_processor", app)
                        or
            data_processor = Processor("data_processor")
            data_processor.init_app(app)
                        or
            app.add_extension(Process("data_processor"))
    """

    def __init__(self, extension_name, app=None):
        """
        init function
        :param name: extension name , 插件名字
        :param app: CtpBee 实例
        """
        self.instrument_set: List or Set = set()
        self.extension_name = extension_name
        self.app = app
        if self.app is not None:
            self.init_app(self.app)
        # 是否冻结
        self.frozen = False

    @property
    def action(self) -> Action:
        if self.app is None:
            raise ValueError("没有载入CtpBee，请尝试通过init_app载入app")
        return self.app.action

    def on_order(self, order: OrderData) -> None:
        raise NotImplemented

    def on_shared(self, shared: SharedData) -> None:
        raise NotImplemented

    def on_bar(self, bar: BarData) -> None:
        raise NotImplemented

    def on_tick(self, tick: TickData) -> None:
        raise NotImplemented

    def on_trade(self, trade: TradeData) -> None:
        raise NotImplemented

    def on_position(self, position: PositionData) -> None:
        raise NotImplemented

    def on_account(self, account: AccountData) -> None:
        raise NotImplemented

    def on_contract(self, contract: ContractData):
        raise NotImplemented

    def on_log(self, log: LogData):
        raise NotImplemented

    def on_init(self, init: bool):
        raise NotImplemented

    def on_realtime(self, timed: datetime):
        pass

    def init_app(self, app):
        if app is not None:
            self.app = app
            self.app.extensions[self.extension_name] = self

    def __call__(self, event: Event):
        func = self.map[event.type]
        if not self.frozen:
            func(self, event.data)

    def __init_subclass__(cls, **kwargs):
        map = {
            EVENT_TIMER: cls.on_realtime,
            EVENT_INIT_FINISHED: cls.on_init,
            EVENT_TICK: cls.on_tick,
            EVENT_BAR: cls.on_bar,
            EVENT_ORDER: cls.on_order,
            EVENT_SHARED: cls.on_shared,
            EVENT_TRADE: cls.on_trade,
            EVENT_POSITION: cls.on_position,
            EVENT_ACCOUNT: cls.on_account,
            EVENT_CONTRACT: cls.on_contract,
            EVENT_LOG: cls.on_log

        }
        parmeter = {
            EVENT_TIMER: EVENT_TIMER,
            EVENT_INIT_FINISHED: EVENT_INIT_FINISHED,
            EVENT_POSITION: EVENT_POSITION,
            EVENT_TRADE: EVENT_TRADE,
            EVENT_BAR: EVENT_BAR,
            EVENT_TICK: EVENT_TICK,
            EVENT_ORDER: EVENT_ORDER,
            EVENT_SHARED: EVENT_SHARED,
            EVENT_ACCOUNT: EVENT_ACCOUNT,
            EVENT_CONTRACT: EVENT_CONTRACT,
            EVENT_LOG: EVENT_LOG
        }
        setattr(cls, "map", map)
        setattr(cls, "parmeter", parmeter)


class AsyncApi(object):
    """
    数据模块
    策略模块
        如果你要开发上述插件需要继承此抽象demo
    AsyncApi ---> 性能优化
    """

    def __init__(self, extension_name, app=None):
        """
        init function
        :param name: extension name , 插件名字
        :param app: CtpBee 实例
        :param api_type 针对几种API实行不同的优化措施
        """
        self.extension_name = extension_name
        self.instrument_set: List or Set = set()
        self.app = app
        if self.app is not None:
            self.init_app(self.app)
        # 是否冻结
        self.fronzen = False

    @property
    def action(self):
        if self.app is None:
            raise ValueError("没有载入CtpBee，请尝试通过init_app载入app")
        return self.app.action

    async def on_order(self, order: OrderData) -> None:
        raise NotImplemented

    async def on_shared(self, shared: SharedData) -> None:
        raise NotImplemented

    async def on_bar(self, bar: BarData) -> None:
        raise NotImplemented

    async def on_tick(self, tick: TickData) -> None:
        raise NotImplemented

    async def on_trade(self, trade: TradeData) -> None:
        raise NotImplemented

    async def on_position(self, position: PositionData) -> None:
        raise NotImplemented

    async def on_account(self, account: AccountData) -> None:
        raise NotImplemented

    async def on_contract(self, contract: ContractData):
        raise NotImplemented

    async def on_log(self, log: LogData):
        raise NotImplemented

    async def on_init(self, init: bool):
        raise NotImplemented

    async def on_realtime(self, timed: datetime):
        pass

    def init_app(self, app):
        if app is not None:
            self.app = app
            self.app.extensions[self.extension_name] = self

    async def __call__(self, event: Event):
        func = self.map[event.type]
        if not self.fronzen:
            await func(self, event.data)

    def __init_subclass__(cls, **kwargs):
        map = {
            EVENT_TIMER: cls.on_realtime,
            EVENT_INIT_FINISHED: cls.on_init,
            EVENT_TICK: cls.on_tick,
            EVENT_BAR: cls.on_bar,
            EVENT_ORDER: cls.on_order,
            EVENT_SHARED: cls.on_shared,
            EVENT_TRADE: cls.on_trade,
            EVENT_POSITION: cls.on_position,
            EVENT_ACCOUNT: cls.on_account,
            EVENT_CONTRACT: cls.on_contract,
            EVENT_LOG: cls.on_log

        }
        parmeter = {
            EVENT_TIMER: EVENT_TIMER,
            EVENT_INIT_FINISHED: EVENT_INIT_FINISHED,
            EVENT_POSITION: EVENT_POSITION,
            EVENT_TRADE: EVENT_TRADE,
            EVENT_BAR: EVENT_BAR,
            EVENT_TICK: EVENT_TICK,
            EVENT_ORDER: EVENT_ORDER,
            EVENT_SHARED: EVENT_SHARED,
            EVENT_ACCOUNT: EVENT_ACCOUNT,
            EVENT_CONTRACT: EVENT_CONTRACT,
            EVENT_LOG: EVENT_LOG
        }
        setattr(cls, "map", map)
        setattr(cls, "parmeter", parmeter)
