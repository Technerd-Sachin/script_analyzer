"""LangGraph wiring: a fixed dependency graph with a per-episode fan-out (Send)."""

import operator
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from bsa.domain.enums import Feature
from bsa.pipeline.context import RunContext, timer
from bsa.pipeline.nodes import alternatives, analysis_extra, core, localization, market, rating

log = structlog.get_logger()


class State(TypedDict):
    done: Annotated[list[str], operator.add]


class EpisodeState(TypedDict):
    episode: int


def build_graph(ctx: RunContext) -> Any:
    g: StateGraph[Any] = StateGraph(State)

    def wrap(
        name: str, fn: Callable[[], Awaitable[None]], feature: Feature | None
    ) -> Callable[..., Awaitable[dict[str, Any]]]:
        async def run(_state: State) -> dict[str, Any]:
            await guarded(ctx, name, fn, feature)
            return {"done": [name]}

        return run

    def add(name: str, fn: Callable[[RunContext], Awaitable[None]], feature: Feature | None = "core") -> None:
        g.add_node(name, wrap(name, lambda: fn(ctx), feature))  # type: ignore[call-overload]

    async def episode_node(state: EpisodeState) -> dict[str, Any]:
        n = state["episode"]
        await guarded(ctx, f"episode_map[{n}]", lambda: core.episode_map(ctx, n), "core")
        return {"done": [f"episode_map[{n}]"]}

    add("story_map", core.story_map)
    add("analytics", analysis_extra.analytics, "analytics")
    add("continuity", analysis_extra.continuity, "analytics")
    add("rating", rating.rating, "rating")
    add("summary", core.summary)
    add("emotion", core.emotion)
    add("market", market.market, "market")
    add("engagement", core.engagement)
    add("cliffhanger", core.cliffhanger)
    add("localization", localization.localization, "localization")
    add("suggestions", core.suggestions)
    add("alternatives", alternatives.alternatives, "alternatives")
    g.add_node("episode_map", episode_node)  # type: ignore[call-overload]

    def fan_out(_state: State) -> list[Send]:
        return [Send("episode_map", {"episode": ep.number}) for ep in ctx.ir.episodes]

    for n in ("story_map", "continuity", "rating"):
        g.add_edge(START, n)
    g.add_conditional_edges("story_map", fan_out, ["episode_map"])
    for n in ("summary", "emotion", "analytics"):
        g.add_edge("story_map", n)
    g.add_edge("summary", "market")  # comps query uses the plot-like summary
    g.add_edge("episode_map", "engagement")
    g.add_edge("episode_map", "cliffhanger")
    g.add_edge("cliffhanger", "localization")
    g.add_edge(["engagement", "cliffhanger"], "suggestions")
    g.add_edge(["engagement", "cliffhanger"], "alternatives")
    for n in (
        "analytics",
        "continuity",
        "rating",
        "summary",
        "emotion",
        "market",
        "localization",
        "suggestions",
        "alternatives",
    ):
        g.add_edge(n, END)
    return g.compile()


async def guarded(
    ctx: RunContext, name: str, fn: Callable[[], Awaitable[None]], feature: Feature | None
) -> None:
    """Run one node; a failure marks its section and never fails the job."""
    if feature and not ctx.opts.has(feature):
        return
    if ctx.not_script and name != "story_map":
        return
    elapsed = timer()
    ctx.emit(name, "started")
    try:
        await fn()
    except Exception as exc:  # noqa: BLE001 - graceful degradation is the contract
        log.exception("node_failed", node=name, error=type(exc).__name__)
        ctx.parts.setdefault("failed", []).append(f"{name}: {type(exc).__name__}")
        ctx.emit(name, "failed", elapsed())
        return
    ctx.emit(name, "done", elapsed())
