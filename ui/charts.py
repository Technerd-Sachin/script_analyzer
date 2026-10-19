"""Plotly figures for the UI. Single-series charts use one colour; identity is always labelled."""

import math
from typing import Any

import plotly.graph_objects as go

PRIMARY = "#e81a3b"
INK = "#333333"
MUTED = "#5b6e7f"
GRID = "#e7e7e7"
SERIES = ["#e81a3b", "#008fd2", "#d67900", "#009966"]  # validated order (dataviz validator, light and dark)
FONT = dict(family="Trebuchet MS, sans-serif", color=INK, size=13)


def _layout(fig: go.Figure, title: str, height: int = 340) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        font=FONT,
        height=height,
        margin=dict(l=40, r=20, t=50, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        hoverlabel=dict(font_family="Trebuchet MS"),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def factor_radar(factors: list[dict[str, Any]]) -> go.Figure:
    names = [f["name"].replace("_", " ") for f in factors]
    scores = [f["score"] for f in factors]
    fig = go.Figure(
        go.Scatterpolar(
            r=scores + scores[:1],
            theta=names + names[:1],
            fill="toself",
            line=dict(color=PRIMARY, width=2),
            fillcolor="rgba(232,26,59,0.15)",
            marker=dict(size=8),
            hovertemplate="%{theta}: %{r}/5<extra></extra>",
        )
    )
    fig.update_polars(
        radialaxis=dict(range=[0, 5], tickvals=[1, 2, 3, 4, 5], gridcolor=GRID),
        angularaxis=dict(gridcolor=GRID),
    )
    return _layout(fig, "Engagement factors (median of runs, 1 to 5)", 380)


def valence_arc(arc: list[dict[str, Any]]) -> go.Figure:
    x = [a["beat_id"] for a in arc]
    fig = go.Figure(
        go.Scatter(
            x=x,
            y=[a["valence"] for a in arc],
            mode="lines+markers+text",
            text=[a["emotion"] for a in arc],
            textposition="top center",
            line=dict(color=PRIMARY, width=2),
            marker=dict(
                size=[8 + 10 * a["intensity"] for a in arc], color=PRIMARY, line=dict(color="white", width=2)
            ),
            customdata=[
                [a["line_ids"][0], a["line_ids"][-1], a.get("secondary") or "-", a["intensity"]] for a in arc
            ],
            hovertemplate="%{x} (%{customdata[0]}..%{customdata[1]})<br>%{text}, secondary %{customdata[2]}<br>valence %{y:+.2f}, intensity %{customdata[3]:.2f}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line=dict(color=GRID, width=1))
    fig.update_yaxes(range=[-1.15, 1.15], title="valence")
    return _layout(fig, "Emotional arc by beat (marker size = intensity)")


def tension_line(episodes: list[dict[str, Any]]) -> go.Figure:
    xs: list[str] = []
    ys: list[int] = []
    for ep in episodes:
        for st in ep["scene_tension"]:
            xs.append(f"E{ep['number']} {st['scene_id']}")
            ys.append(st["tension"])
    fig = go.Figure(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers",
            line=dict(color=PRIMARY, width=2),
            marker=dict(size=8),
            hovertemplate="%{x}: tension %{y}/10<extra></extra>",
        )
    )
    fig.update_yaxes(range=[0, 10.5], title="tension")
    return _layout(fig, "Tension per scene")


def dominant_bars(dominant: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=[d["share"] for d in dominant],
            y=[d["emotion"] for d in dominant],
            orientation="h",
            marker=dict(color=PRIMARY, cornerradius=4),
            text=[f"{d['share']:.0%}" for d in dominant],
            textposition="outside",
            hovertemplate="%{y}: %{x:.0%}<extra></extra>",
        )
    )
    fig.update_xaxes(range=[0, 1.15], tickformat=".0%")
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, "Dominant emotions", 240)


def network(nodes: list[str], edges: list[dict[str, Any]], shares: dict[str, float]) -> go.Figure:
    n = max(1, len(nodes))
    pos = {
        name: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)) for i, name in enumerate(nodes)
    }
    fig = go.Figure()
    top = max((e["weight"] for e in edges), default=1)
    for e in edges:
        if e["a"] in pos and e["b"] in pos:
            (x0, y0), (x1, y1) = pos[e["a"]], pos[e["b"]]
            fig.add_trace(
                go.Scatter(
                    x=[x0, x1],
                    y=[y0, y1],
                    mode="lines",
                    line=dict(color=MUTED, width=1 + 5 * e["weight"] / top),
                    hoverinfo="skip",
                )
            )
    fig.add_trace(
        go.Scatter(
            x=[pos[k][0] for k in nodes],
            y=[pos[k][1] for k in nodes],
            mode="markers+text",
            text=nodes,
            textposition="top center",
            marker=dict(
                size=[14 + 50 * shares.get(k, 0) for k in nodes],
                color=PRIMARY,
                line=dict(color="white", width=2),
            ),
            hovertemplate="%{text}<extra></extra>",
        )
    )
    fig.update_xaxes(visible=False, range=[-1.4, 1.4])
    fig.update_yaxes(visible=False, range=[-1.4, 1.4])
    return _layout(fig, "Character network (node size = dialogue share, edge width = exchanges)", 380)
