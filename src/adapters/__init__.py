"""事件源适配器。模拟源可直接跑；官方源是禁用桩。"""

from src.adapters.official import OfficialAdapterStub
from src.adapters.sim_replay import SCENES, SimReplay

__all__ = ["OfficialAdapterStub", "SCENES", "SimReplay"]
