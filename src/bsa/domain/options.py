from pydantic import BaseModel, Field

from bsa.domain.enums import ALL_FEATURES, Feature, LangCode


class AnalysisOptions(BaseModel):
    features: list[Feature] = Field(default_factory=lambda: list(ALL_FEATURES))
    mode: str = "local"  # Amendment 1: open-source only, everything runs on the VM
    localization_targets: list[LangCode] | None = None
    engagement_runs: int = 3

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def cache_dict(self) -> dict[str, object]:
        return {
            "features": sorted(self.features),
            "mode": self.mode,
            "localization_targets": self.localization_targets,
            "engagement_runs": self.engagement_runs,
        }
