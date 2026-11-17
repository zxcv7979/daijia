"""YAML 配置加载、校验与热更新。

非法内容会抛 ConfigError，调用方必须保留上一份有效配置。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from src.models import AvatarType, EmotionName, EventType, PrintStyle


class ConfigError(Exception):
    """配置文本无法解析或不符合 P1 约束。"""


class LiveCfg(BaseModel):
    collection_enabled: bool = False
    real_source: bool = False


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)


class SimReplayCfg(BaseModel):
    enabled: bool = True
    samples_dir: str = "data/samples"
    default_replay: str = "replay.jsonl"
    default_speed: int = 1
    speeds: list[int] = Field(default_factory=lambda: [1, 5, 20])
    loop: bool = False

    @field_validator("speeds")
    @classmethod
    def _speeds(cls, value: list[int]) -> list[int]:
        if value != [1, 5, 20]:
            raise ValueError("回放速度只允许 1、5、20")
        return value

    @field_validator("default_speed")
    @classmethod
    def _default_speed(cls, value: int) -> int:
        if value not in (1, 5, 20):
            raise ValueError("默认速度只允许 1、5、20")
        return value


class GovernanceCfg(BaseModel):
    queue_max: int = Field(default=4000, ge=1, le=100_000)
    dedup_window_sec: int = Field(default=30, ge=1, le=600)
    heartbeat_interval_sec: float = Field(default=1, gt=0, le=30)
    heartbeat_timeout_sec: float = Field(default=3, gt=0, le=60)
    backoff_base_sec: float = Field(default=0.2, gt=0, le=5)
    backoff_factor: float = Field(default=2, ge=1, le=8)
    backoff_cap_sec: float = Field(default=5, gt=0, le=5)
    stable_after_sec: float = Field(default=2, gt=0, le=60)
    drop_policy: str = "drop_oldest"

    @field_validator("drop_policy")
    @classmethod
    def _policy(cls, value: str) -> str:
        if value != "drop_oldest":
            raise ValueError("P2 背压策略只允许 drop_oldest")
        return value


class OfficialCfg(BaseModel):
    enabled: bool = False
    mode: str = "stub"
    # 占位。空字符串表示还没有用户提供的官方合同或 SDK 名称。
    contract: str = ""
    credential_env: str = ""

    @field_validator("enabled")
    @classmethod
    def _must_stay_off(cls, value: bool) -> bool:
        if value:
            raise ValueError("P1 官方适配器必须保持 enabled: false")
        return value

    @field_validator("mode")
    @classmethod
    def _stub_only(cls, value: str) -> str:
        if value != "stub":
            raise ValueError("P1 官方适配器模式只能是 stub")
        return value


class AdaptersCfg(BaseModel):
    sim_replay: SimReplayCfg = Field(default_factory=SimReplayCfg)
    official: OfficialCfg = Field(default_factory=OfficialCfg)
    governance: GovernanceCfg = Field(default_factory=GovernanceCfg)


class NormalizeCfg(BaseModel):
    dedup_window_sec: int = Field(default=30, ge=1, le=600)
    combo_merge_window_ms: int = Field(default=800, ge=50, le=10_000)
    # 产品要求同文弹幕聚合就是 200ms，不能配成 2 秒。
    danmaku_aggregate_window_ms: int = 200
    ts_bucket_ms: int = Field(default=100, ge=10, le=5_000)

    @field_validator("danmaku_aggregate_window_ms")
    @classmethod
    def _window_fixed(cls, value: int) -> int:
        if value != 200:
            raise ValueError("弹幕同文聚合窗口必须为 200ms")
        return value


class DuckingCfg(BaseModel):
    enabled: bool = True


class EmotionCfg(BaseModel):
    rise_ms: int = Field(default=220, ge=150, le=300)
    hold_ms: int = Field(default=1200, ge=200, le=8_000)
    decay_half_life_s: float = Field(default=6, ge=4, le=8)
    max_on_screen: int = Field(default=8, ge=1, le=50)
    ducking: DuckingCfg = Field(default_factory=DuckingCfg)
    cooldowns_ms: dict[str, int] = Field(
        default_factory=lambda: {"L0": 200, "L1": 300, "L2": 1000, "L3": 3000, "L4": 6000}
    )

    @field_validator("cooldowns_ms")
    @classmethod
    def _cooldowns(cls, value: dict[str, int]) -> dict[str, int]:
        for key in ("L0", "L1", "L2", "L3", "L4"):
            if key not in value:
                raise ValueError(f"缺少冷却 {key}")
            if value[key] < 0 or value[key] > 60_000:
                raise ValueError(f"冷却 {key} 超出范围")
        return value


class PrintCueCfg(BaseModel):
    emotion: EmotionName
    intensity: float = Field(ge=0, le=1)
    fx: str = Field(min_length=1, max_length=64)
    beat: str = ""
    hold_ms: int | None = Field(default=None, ge=100, le=8_000)


class PrintShowCfg(BaseModel):
    default_duration_sec: float = Field(default=45, gt=0, le=600)
    show_min_sec: float = Field(default=30, gt=0, le=120)
    show_max_sec: float = Field(default=60, gt=0, le=180)
    progress_cues: list[int] = Field(default_factory=lambda: [25, 50, 75, 90, 100])
    cue_priority: int = Field(default=6, ge=0, le=100)
    cue_hold_ms: int = Field(default=800, ge=100, le=8_000)
    cue_table: dict[int, PrintCueCfg]
    grain: float = Field(default=0.45, ge=0, le=1)
    camera_orbit: float = Field(default=1.0, ge=0, le=2)
    reveal_lights: float = Field(default=1.0, ge=0, le=2)
    queue_jump: bool = True
    jump_min_style: PrintStyle = PrintStyle.hologram

    @field_validator("progress_cues")
    @classmethod
    def _cues(cls, value: list[int]) -> list[int]:
        if value != [25, 50, 75, 90, 100]:
            raise ValueError("打印进度提示点必须是 25/50/75/90/100")
        return value


class AvatarCfg(BaseModel):
    photo_retention_days: int = Field(default=7, ge=1, le=3650)
    seed: int = Field(default=42, ge=0, le=2_000_000_000)
    gpu_enabled: bool = False
    # 云端重建接口默认关闭，本仓库也不调用它。
    cloud_api: bool = False

    @field_validator("cloud_api")
    @classmethod
    def _cloud_off(cls, value: bool) -> bool:
        if value:
            raise ValueError("照片不能发到云端接口，cloud_api 必须为 false")
        return value


class OverlayCfg(BaseModel):
    width: int = Field(default=1920, ge=16, le=7680)
    height: int = Field(default=1080, ge=16, le=4320)
    transparent: bool = True
    target_fps: int = Field(default=60, ge=30, le=120)
    frame_budget_ms: float = Field(default=12, gt=0, le=33)
    max_fx: int = Field(default=8, ge=1, le=8)
    max_particles: int = Field(default=20_000, ge=1, le=20_000)
    downshift_after_frames: int = Field(default=8, ge=1, le=120)
    recover_after_frames: int = Field(default=45, ge=1, le=600)
    recover_under_ms: float = Field(default=10, gt=0, le=20)
    mute: bool = False
    # 特效名 → 本地音频路径。空字符串表示静音，不自动发声。
    sfx: dict[str, str] = Field(default_factory=dict)
    # 循环背景音乐路径（overlay 静态资源前缀），空字符串表示不播放。
    bgm: str = ""
    bgm_volume: float = Field(default=0.3, gt=0, le=1)


class BusCfg(BaseModel):
    reconnect_buffer_sec: int = 30

    @field_validator("reconnect_buffer_sec")
    @classmethod
    def _buffer(cls, value: int) -> int:
        if value != 30:
            raise ValueError("重连事件缓冲必须为 30 秒")
        return value


class DefaultConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    live: LiveCfg = Field(default_factory=LiveCfg)
    server: ServerCfg = Field(default_factory=ServerCfg)
    adapters: AdaptersCfg = Field(default_factory=AdaptersCfg)
    normalize: NormalizeCfg = Field(default_factory=NormalizeCfg)
    emotion: EmotionCfg
    print_show: PrintShowCfg
    bus: BusCfg = Field(default_factory=BusCfg)
    overlay: OverlayCfg = Field(default_factory=OverlayCfg)
    avatar: AvatarCfg = Field(default_factory=AvatarCfg)


class TriggerSpec(BaseModel):
    type: EventType
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    combo_min: int | None = Field(default=None, ge=1)
    highlight: str | None = None
    keywords: list[str] = Field(default_factory=list)
    fx: str | None = None


class PrintSpec(BaseModel):
    style: PrintStyle
    avatar_type: AvatarType


class TierSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    priority: int = Field(ge=0, le=100)
    emotion: EmotionName
    intensity: float = Field(ge=0, le=1)
    fx: str = Field(min_length=1, max_length=64)
    triggers: list[TriggerSpec] = Field(min_length=1)
    atmosphere_only: bool = False
    hold_ms: int | None = Field(default=None, ge=0, le=10_000)
    particles: int = Field(default=24, ge=0, le=20_000)
    secondary: bool = False
    print_spec: PrintSpec | None = Field(default=None, alias="print")


class MappingsSpec(BaseModel):
    tiers: dict[str, TierSpec]

    @model_validator(mode="after")
    def _required_tiers(self) -> MappingsSpec:
        missing = [name for name in ("L0", "L1", "L2", "L3", "L4") if name not in self.tiers]
        if missing:
            raise ValueError("缺少档位 " + ", ".join(missing))
        extra = [name for name in self.tiers if name not in {"L0", "L1", "L2", "L3", "L4"}]
        if extra:
            raise ValueError("P1 只允许档位 L0-L4，多余：" + ", ".join(extra))
        if self.tiers["L1"].atmosphere_only is not True:
            raise ValueError("L1 弹幕档必须是 atmosphere_only，不能抢走礼物主秀")
        return self


class RetentionCfg(BaseModel):
    model_config = ConfigDict(extra="ignore")

    retention_days: int = Field(default=7, ge=1, le=3650)


class ComplianceSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pii: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
    live_collection: dict[str, Any] = Field(default_factory=dict)
    retention: RetentionCfg = Field(default_factory=RetentionCfg)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_yaml(text: str) -> Any:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 无法解析：{exc}") from exc
    if data is None:
        raise ConfigError("YAML 内容为空")
    if not isinstance(data, dict):
        raise ConfigError("YAML 根节点必须是映射")
    return data


def _validate(model_cls: type[BaseModel], data: Any, label: str) -> Any:
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{label} 不符合约束：{exc}") from exc


class Settings:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config_dir = root / "config"
        self.data_dir = root / "data"
        self.default_model: DefaultConfig
        self.mappings_model: MappingsSpec
        self.compliance_model: ComplianceSpec
        self.mappings_text: str = ""
        self.salt: str = ""
        self.last_error: str | None = None
        self._mtimes: dict[Path, int] = {}
        self.load_all()

    def load_all(self) -> None:
        self._load_default(initial=True)
        self._load_mappings(initial=True)
        self._load_compliance(initial=True)
        self._load_salt(initial=True)

    def collection_enabled(self) -> bool:
        return bool(self.default_model.live.collection_enabled)

    def real_source_configured(self) -> bool:
        return bool(self.default_model.live.real_source)

    def samples_dir(self) -> Path:
        raw = Path(self.default_model.adapters.sim_replay.samples_dir)
        if not raw.is_absolute():
            raw = self.root / raw
        return raw

    def retention_days(self) -> int:
        return int(self.compliance_model.retention.retention_days)

    def audit_path(self) -> Path:
        rel = str(self.compliance_model.audit.get("path") or "data/audit/audit.jsonl")
        path = Path(rel)
        if not path.is_absolute():
            path = self.root / path
        return path

    def apply_mappings_text(self, text: str) -> MappingsSpec:
        """校验通过后才替换内存并写回文件。失败时原配置继续生效。"""

        data = parse_yaml(text)
        model = _validate(MappingsSpec, data, "映射表")
        path = self.config_dir / "mappings.yaml"
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        self.mappings_model = model
        self.mappings_text = path.read_text(encoding="utf-8")
        self._note(path)
        self.last_error = None
        return model

    def update_collection_enabled(self, enabled: bool) -> bool:
        """改默认配置中的开关。返回修改前的值。不启动任何平台连接。"""

        previous = self.collection_enabled()
        path = self.config_dir / "default.yaml"
        file_text = _read_text(path)
        updated, count = re.subn(
            r"(collection_enabled:\s*)(true|false)",
            r"\g<1>" + ("true" if enabled else "false"),
            file_text,
            count=1,
        )
        if count != 1:
            raise ConfigError("找不到 live.collection_enabled，拒绝写入")
        path.write_text(updated, encoding="utf-8")
        self.default_model.live.collection_enabled = enabled
        self._note(path)
        return previous

    def update_real_source(self, enabled: bool) -> bool:
        """只改配置文件。运行时是否生效由二次确认决定。"""

        previous = self.real_source_configured()
        path = self.config_dir / "default.yaml"
        file_text = _read_text(path)
        updated, count = re.subn(
            r"(real_source:\s*)(true|false)",
            r"\g<1>" + ("true" if enabled else "false"),
            file_text,
            count=1,
        )
        if count != 1:
            raise ConfigError("找不到 live.real_source，拒绝写入")
        path.write_text(updated, encoding="utf-8")
        self.default_model.live.real_source = enabled
        self._note(path)
        return previous

    def poll_once(self) -> list[str]:
        """检查配置文件是否变化。坏文件只记录 last_error，不替换内存。"""

        changed: list[str] = []
        for name, loader in (
            ("default.yaml", self._load_default),
            ("mappings.yaml", self._load_mappings),
            ("compliance.yaml", self._load_compliance),
            ("secrets.yaml", self._load_salt),
        ):
            path = self.config_dir / name
            if not path.exists():
                if name == "secrets.yaml":
                    continue
                self.last_error = f"缺少配置文件 {name}"
                continue
            mtime = path.stat().st_mtime_ns
            if self._mtimes.get(path) == mtime:
                continue
            try:
                loader(initial=False)
            except ConfigError as exc:
                self.last_error = str(exc)
                # 失败也记下 mtime，避免每个轮询都刷同一条错误；文件再改会重新尝试。
                self._mtimes[path] = mtime
                continue
            changed.append(name)
            self.last_error = None
        return changed

    def _load_default(self, initial: bool = False) -> None:
        path = self.config_dir / "default.yaml"
        model = _validate(DefaultConfig, parse_yaml(_read_text(path)), "default.yaml")
        self.default_model = model
        self._note(path)
        if not initial:
            return

    def _load_mappings(self, initial: bool = False) -> None:
        del initial
        path = self.config_dir / "mappings.yaml"
        text = _read_text(path)
        model = _validate(MappingsSpec, parse_yaml(text), "mappings.yaml")
        self.mappings_model = model
        self.mappings_text = text
        self._note(path)

    def _load_compliance(self, initial: bool = False) -> None:
        del initial
        path = self.config_dir / "compliance.yaml"
        model = _validate(ComplianceSpec, parse_yaml(_read_text(path)), "compliance.yaml")
        self.compliance_model = model
        self._note(path)

    def _load_salt(self, initial: bool = False) -> None:
        del initial
        self.salt = resolve_salt(self.config_dir, self.compliance_model)
        path = self.config_dir / "secrets.yaml"
        if path.exists():
            # 先解析，坏文件不能把盐换成空。
            data = parse_yaml(_read_text(path))
            if not isinstance(data, dict) or not str(data.get("pii_salt") or "").strip():
                raise ConfigError("secrets.yaml 需要非空的 pii_salt")
            self._note(path)
            self.salt = resolve_salt(self.config_dir, self.compliance_model)

    def _note(self, path: Path) -> None:
        if path.exists():
            self._mtimes[path] = path.stat().st_mtime_ns


def resolve_salt(config_dir: Path, compliance: ComplianceSpec) -> str:
    env_name = str(compliance.pii.get("salt_env") or "LIVE_SHOW_SALT")
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return env_value
    secrets_path = config_dir / "secrets.yaml"
    if secrets_path.exists():
        data = parse_yaml(_read_text(secrets_path))
        salt = str((data or {}).get("pii_salt") or "").strip()
        if salt:
            return salt
    demo = str(compliance.pii.get("demo_salt") or "").strip()
    if not demo:
        raise ConfigError("没有可用的 PII 盐：请设置环境变量或 secrets.yaml")
    return demo
