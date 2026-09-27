from __future__ import annotations

from typing import Any

from .contracts import ExperienceItem, ExperienceResponse, thaw_snapshot


class ExperiencePresenter:
    """Render only user-facing logic-chain concepts by default."""

    def present(
        self, response: ExperienceResponse, *, diagnostic: bool = False
    ) -> dict[str, Any]:
        if not isinstance(response, ExperienceResponse):
            raise TypeError("response must be an ExperienceResponse")
        if type(diagnostic) is not bool:
            raise TypeError("diagnostic must be a bool")
        rendered = {
            "flow": response.flow.value if response.flow is not None else None,
            "status": response.status,
            "understood": self._items(response.understood),
            "recorded": self._items(response.recorded),
            "hard_constraints": self._items(response.hard_constraints),
            "suggestions": self._items(response.suggestions),
            "automatic_adjustments": self._items(response.automatic_adjustments),
            "confirmations": self._items(response.confirmations),
            "uncertainties": self._items(response.uncertainties),
        }
        if diagnostic:
            rendered["diagnostics"] = [
                thaw_snapshot(item) for item in response.diagnostics
            ]
        return rendered

    @staticmethod
    def _items(items: tuple[ExperienceItem, ...]) -> list[dict[str, Any]]:
        rendered = []
        for item in items:
            value: dict[str, Any] = {
                "title": item.title,
                "reason_code": item.reason_code,
                "requires_confirmation": item.requires_confirmation,
            }
            if item.before is not None:
                value["before"] = thaw_snapshot(item.before)
            if item.after is not None:
                value["after"] = thaw_snapshot(item.after)
            rendered.append(value)
        return rendered
