# ==============================================================================
# BRAND THEME — one palette, one layout function, used by every chart.
# Blue family = brand/identity. Green/red/amber are reserved as STATUS colors
# (good / bad / caution) and are never used decoratively.
# ==============================================================================

NAVY = "#0b2540"        # primary ink / headline bars
BLUE_DEEP = "#1c4e80"   # primary series
BLUE_MID = "#5b8fc2"    # secondary series / context
BLUE_SOFT = "#9dc0e0"   # tertiary / receding context
BLUE_PALE = "#cfe0f2"   # fills, light context bars
BLUE_WASH = "#f4f8fc"   # panel / plot background

POS = "#1a8a4a"   # favourable (status only)
NEG = "#c23b34"   # adverse (status only)
WARN = "#e0a527"  # caution band (status only)
GREY = "#8a97a6"  # muted ink / gridlines

FONT = "Inter, -apple-system, 'Segoe UI', sans-serif"

TREND_THRESHOLD = 0.10


def status_color(value, base=BLUE_DEEP, threshold=TREND_THRESHOLD * 100):
    """Green/red only when a month-over-month move is materially good or bad."""
    if value is None:
        return base
    try:
        if value != value:  # NaN
            return base
    except TypeError:
        return base
    if value > threshold:
        return POS
    if value < -threshold:
        return NEG
    return base


def trend_colors(growth_pct, base=BLUE_DEEP):
    return [status_color(v, base) for v in growth_pct]


def brand_layout(fig, title: str, subtitle: str = "", height: int = 420):
    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b>" + (
                f"<br><span style='font-size:12px;color:{GREY}'>{subtitle}</span>" if subtitle else ""
            ),
            x=0.01, xanchor="left", font=dict(size=17, color=NAVY, family=FONT),
        ),
        font=dict(family=FONT, size=12, color=NAVY),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=BLUE_WASH,
        margin=dict(l=60, r=30, t=70, b=50),
        height=height,
        legend=dict(orientation="h", y=-0.16, x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=11, color=GREY)),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", font=dict(color=NAVY, family=FONT)),
    )
    fig.update_xaxes(showgrid=False, linecolor=BLUE_PALE, tickfont=dict(color=GREY, size=11))
    fig.update_yaxes(gridcolor="white", gridwidth=1.5, zeroline=True,
                      zerolinecolor=BLUE_SOFT, linecolor=BLUE_PALE,
                      tickfont=dict(color=GREY, size=11))
    return fig
