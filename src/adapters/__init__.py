"""事件源适配器。P1 只有本地回放，官方源是禁用桩。"""

from src.adapters.official import OfficialAdapterStub
from src.adapters.sim_replay import SCENES, SimReplay

__all__ = ["OfficialAdapterStub", "SCENES", "SimReplay"]
