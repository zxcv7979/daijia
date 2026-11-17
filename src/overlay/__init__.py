"""画面质量决策。特效页按同一套阈值执行。"""

from src.overlay.quality import QualityState, admit_fx, particle_budget, step_quality

__all__ = ["QualityState", "admit_fx", "particle_budget", "step_quality"]
