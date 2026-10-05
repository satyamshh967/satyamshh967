import datetime
import hashlib
import html
import json
import math
import os
import pathlib
import sys
import urllib.request

CYAN, MAGENTA, GREEN = "#00d9ff", "#ff2bd6", "#3fb950"
W, M = 880, 16            # slice width, transparent side margin (room for the glow)
FL, FR = M, W - M         # frame left / right
X = 52                    # text left edge
e = html.escape

ROOFS = ["#0c2d6b", "#1554c0", "#2f81f7", "#1fd5ff"]
WIN_ON, WIN_ON_SIDE, WIN_OFF = "#7df9ff", "#4cc9f0", "#111827"

# Widescreen Panoramic Dimensions for rectangular aspect ratio (occupies much less height!)
CITY_TW, CITY_TH = 24.0, 7.2                 # flatter isometric perspective for rectangular footprint
CITY_OX, CITY_OY = 120.0, 140.0              # origin placing the grid neatly inside 360px height
CITY_HMAX = 68.0                             # balanced building height

BASE_CSS = f"""text{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,'Fira Code',monospace;font-size:15px}}
.dim{{fill:#8b949e}}.cy{{fill:{CYAN}}}.fg{{fill:#c9d1d9}}.gr{{fill:{GREEN}}}.wh{{fill:#f0fbff}}
@keyframes fadein{{from{{opacity:0;transform:translateX(-6px)}}to{{opacity:1;transform:none}}}}
@keyframes blink{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.35}}}}
.ln{{animation:fadein .35s ease-out both}}
.cursor{{animation:blink 1.05s step-end infinite}}
.dot{{animation:pulse 2s ease-in-out infinite}}"""

DEFS = f"""<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="{CYAN}" stroke-opacity=".06"/></pattern>
<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>
<filter id="g" x="-20%" y="-60%" width="140%" height="220%"><feGaussianBlur stdDeviation="4"/></filter>"""

def _p(x, y):
    return f"{x:.1f},{y:.1f}"

def _rng(seed):
    state = int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16)
    while True:
        state = (state * 6364136223846793005 + 1442695040888963407) % 2**64
        yield (state >> 11) / 2**53

def _levels(counts):
    nz = sorted(c for c in counts if c > 0)
    if not nz:
        return [1, 1, 1]
    q = lambda f: nz[min(len(nz) - 1, int(len(nz) * f))]
    return [q(.25), q(.5), q(.75)]

def heading(y, name, counter):
    return f'''<text x="{X}" y="{y}" font-weight="700" fill="{CYAN}" filter="url(#g)" opacity=".8" style="font-size:20px">~/</text>
<text x="{X}" y="{y}" font-weight="700" style="font-size:20px"><tspan class="cy">~/</tspan><tspan class="wh">{e(name)}</tspan></text>
<text x="{FR-36}" y="{y}" text-anchor="end" letter-spacing="2" fill="#6e7681" style="font-size:12px">{e(counter)}</text>
<line x1="{X}" y1="{y+14}" x2="{FR-36}" y2="{y+14}" stroke="{CYAN}" stroke-opacity=".4"/>
<line x1="{X}" y1="{y+14}" x2="{X+120}" y2="{y+14}" stroke="{CYAN}" stroke-width="2"/>
<line x1="{X}" y1="{y+14}" x2="{X+120}" y2="{y+14}" stroke="{CYAN}" stroke-width="3" filter="url(#g)"/>'''

def slice_svg(h, body, *, title, desc, top=True, bottom=True, css="", defs=""):
    y0 = M if top else 0
    y1 = h - M if bottom else h
    rails = f"M{FL} {y0}V{y1}M{FR} {y0}V{y1}"
    if top:
        rails += f"M{FL} {y0}H{FR}"
    if bottom:
        rails += f"M{FL} {y1}H{FR}"
    gy0 = y0 if top else -40
    gy1 = y1 if bottom else h + 40
    glow = f"M{FL} {gy0}V{gy1}M{FR} {gy0}V{gy1}" + (f"M{FL} {y0}H{FR}" if top else "") + (f"M{FL} {y1}H{FR}" if bottom else "")
    corners = ""
    if top:
        corners += f'<path d="M{FL-7} {y0+18}V{y0-7}H{FL+18}"/><path d="M{FR-18} {y0-7}H{FR+7}V{y0+18}"/>'
    if bottom:
        corners += f'<path d="M{FL-7} {y1-18}V{y1+7}H{FL+18}"/><path d="M{FR-18} {y1+7}H{FR+7}V{y1-18}"/>'
    
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" role="img" aria-labelledby="t d">
<title id="t">{e(title)}</title>
<desc id="d">{e(desc)}</desc>
<style>
{BASE_CSS}
{css}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
</style>
<defs>
{DEFS}
{defs}
</defs>
<path d="{glow}" fill="none" stroke="{CYAN}" stroke-width="3" opacity=".55" filter="url(#glow)"/>
<rect x="{FL}" y="{y0}" width="{FR-FL}" height="{y1-y0}" fill="#03040a"/>
<rect x="{FL}" y="{y0}" width="{FR-FL}" height="{y1-y0}" fill="url(#grid)"/>
{body}
<path d="{rails}" fill="none" stroke="{CYAN}" stroke-width="1.2"/>
<g fill="none" stroke="{CYAN}" stroke-width="2">{corners}</g>
</svg>
'''

def build_panoramic_city(calendar, updated):
    days = [(datetime.date.fromisoformat(d), n) for d, n in calendar]
    counts = [n for _, n in days]
    total, peak = sum(counts), max(counts) if counts else 0
    lv = _levels(counts)
    rnd = _rng(f"{updated}-{total}")
    start = days[0][0]

    cells = []
    for d, n in days:
        idx = (d - start).days
        cells.append((idx // 7, (d.weekday() + 1) % 7, n, d))
    cells.sort(key=lambda c: (c[0] + c[1], c[0]))

    shapes, flick = [], 0
    for w, dow, n, d in cells:
        cx = CITY_OX + (w - dow) * CITY_TW / 2
        cy = CITY_OY + (w + dow) * CITY_TH / 2
        L, R = (cx - CITY_TW / 2, cy), (cx + CITY_TW / 2, cy)
        T, B = (cx, cy - CITY_TH / 2), (cx, cy + CITY_TH / 2)
        if n == 0:
            shapes.append(f'<path class="tile" d="M{_p(*T)}L{_p(*R)}L{_p(*B)}L{_p(*L)}Z" fill="#121620" stroke="#0d1117" stroke-width=".5"><title>{d.strftime("%b %d, %Y")}: 0 contributions</title></path>')
            continue
        h = 6 + (CITY_HMAX - 6) * math.sqrt(n / peak)
        level = sum(n > t for t in lv)
        Tu, Ru, Bu, Lu = [(x, y - h) for x, y in (T, R, B, L)]
        
        bld_parts = []
        bld_parts.append(f'<path d="M{_p(*L)}L{_p(*B)}L{_p(*Bu)}L{_p(*Lu)}Z" fill="#1a2440"/>'
                         f'<path d="M{_p(*B)}L{_p(*R)}L{_p(*Ru)}L{_p(*Bu)}Z" fill="#111831"/>'
                         f'<path d="M{_p(*Tu)}L{_p(*Ru)}L{_p(*Bu)}L{_p(*Lu)}Z" fill="{ROOFS[level]}"/>')
        on, side, off, fl = [], [], [], []
        for face, (a, b) in (("l", (L, B)), ("r", (B, R))):
            for r in range(int((h - 5) // 5.5)):
                v0 = 3.5 + r * 5.5
                for u0 in (.18, .58):
                    lit = next(rnd) < .55
                    if not lit and next(rnd) < .5:
                        continue
                    pts = [(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u - v)
                           for u, v in ((u0, v0), (u0 + .26, v0), (u0 + .26, v0 + 2.5), (u0, v0 + 2.5))]
                    seg = "M" + "L".join(_p(*q) for q in pts) + "Z"
                    if not lit:
                        off.append(seg)
                    elif next(rnd) < .03:
                        fl.append((seg, face))
                    else:
                        (on if face == "l" else side).append(seg)
        if off:
            bld_parts.append(f'<path d="{"".join(off)}" fill="{WIN_OFF}"/>')
        if on:
            bld_parts.append(f'<path class="win-on" d="{"".join(on)}" fill="{WIN_ON}"/>')
        if side:
            bld_parts.append(f'<path class="win-side" d="{"".join(side)}" fill="{WIN_ON_SIDE}"/>')
        for seg, face in fl:
            flick += 1
            bld_parts.append(f'<path class="f{flick % 3}" d="{seg}" fill="{WIN_ON if face == "l" else WIN_ON_SIDE}"/>')

        # Interactive group wrapper for each building with tooltip and hover reaction
        group_markup = f'<g class="bld"><title>{d.strftime("%b %d, %Y")}: {n} contribution{"s" if n != 1 else ""}</title>{"".join(bld_parts)}</g>'
        shapes.append(group_markup)

    stars = []
    for i in range(36):
        x, y = 440 + next(rnd) * 380, 75 + next(rnd) * 110
        if x > 720 and y < 145:
            continue
        cls = f' class="s{i % 3}"' if i % 3 == 0 else ""
        stars.append(f'<circle{cls} cx="{x:.1f}" cy="{y:.1f}" r="{(.6, .8, 1.0)[i % 3]}" fill="#c9d1d9" opacity="{.35 + next(rnd) * .5:.2f}"/>')
    
    busiest_d, busiest_n = max(days, key=lambda t: t[1]) if days and peak > 0 else (None, 0)
    info = [
        f'<tspan class="cy" font-weight="700">{total:,}</tspan> contributions \u00b7 last 365 days',
        f'busiest day <tspan class="fg">{busiest_d:%b} {busiest_d.day}</tspan> \u00b7 {busiest_n}' if busiest_n else "",
        f'{sum(1 for n in counts if n)} active days'
    ]
    info_svg = "".join(f'<text x="{FR-36}" y="{170 + i*18}" text-anchor="end" class="dim" style="font-size:11.5px">{t}</text>'
                       for i, t in enumerate(info) if t)
    legend = "".join(f'<rect x="{X + 46 + i*15}" y="{332}" width="10" height="10" rx="1.5" fill="{c}"/>'
                     for i, c in enumerate(["#121620"] + ROOFS))
    
    body = heading(40, "contribution-city", "// 03") + f'''
<g class="ln" style="animation-delay:.15s"><text x="{X}" y="82" class="dim" style="font-size:13px"><tspan class="gr">$</tspan> render-city --last 365d --panoramic <tspan fill="#484f58"># hover any building to inspect</tspan></text></g>
<g>{"".join(stars)}</g>
<g class="moon">
  <circle cx="{FR-70}" cy="{110}" r="32" fill="url(#moonglow)"/>
  <circle cx="{FR-70}" cy="{110}" r="11" fill="#e6edf3"/>
  <circle cx="{FR-65}" cy="{106}" r="10" fill="#03040a"/>
  <title>Contribution Moon: Real-time Lunar Tracker</title>
</g>
<g class="plane"><g transform="translate(0 92)"><rect x="0" y="0" width="13" height="2" rx="1" fill="#484f58"/><circle class="bl" cx="0" cy="1" r="1.5" fill="#ff7b72"/><circle class="bl" cx="13" cy="1" r="1.5" fill="#f0f6fc" style="animation-delay:.7s"/></g></g>
{info_svg}
{"".join(shapes)}
<text x="{X}" y="{341}" class="dim" style="font-size:10.5px">quiet</text>{legend}<text x="{X + 46 + 5*15 + 6}" y="{341}" class="dim" style="font-size:10.5px">skyscraper</text>'''

    css = f"""@keyframes tw{{0%,100%{{opacity:.9}}50%{{opacity:.15}}}}
@keyframes fl{{0%,40%,100%{{opacity:1}}45%,60%{{opacity:.1}}}}
@keyframes blink{{0%,90%,100%{{opacity:0}}93%{{opacity:1}}}}
@keyframes fly{{from{{transform:translate({FL - 40}px,0)}}to{{transform:translate({FR + 40}px,-24px)}}}}
.s0{{animation:tw 3s infinite}}
.f0{{animation:fl 5s infinite}}.f1{{animation:fl 7s infinite 2s}}.f2{{animation:fl 9s infinite 4s}}
.plane{{animation:fly 24s linear infinite}}.bl{{animation:blink 1.4s infinite}}
.bld{{transition:transform .2s ease, filter .2s ease; cursor:pointer}}
.bld:hover{{transform:translateY(-4px); filter:drop-shadow(0 0 10px {CYAN}) drop-shadow(0 0 18px {CYAN}) brightness(1.35)}}
.bld:hover .win-on{{fill:#ffffff}}
.tile{{transition:fill .15s ease, stroke .15s ease; cursor:pointer}}
.tile:hover{{fill:#1a253c; stroke:{CYAN}; stroke-width:1}}
.moon{{transition:transform .3s ease; cursor:pointer}}
.moon:hover{{transform:scale(1.08)}}"""
    defs = f'<radialGradient id="moonglow"><stop offset="0" stop-color="#f0f6fc" stop-opacity=".22"/><stop offset="1" stop-color="#f0f6fc" stop-opacity="0"/></radialGradient>'
    desc = (f"Contribution city: an isometric panoramic night skyline with one building per day of the last year. "
            f"{total:,} contributions" + (f", busiest day {busiest_d:%B} {busiest_d.day} with {busiest_n}" if busiest_n else "") + ".")
    
    # 360 height makes it a compact widescreen rectangle!
    return slice_svg(360, body, title="Contribution city", desc=desc, css=css, defs=defs)

def build_activity_graph(weeks, updated):
    # Width: 880, Height: 320 (compact rectangular graph)
    h = 320
    weekly_counts = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in weeks]
    max_c = max(weekly_counts) if weekly_counts else 1
    if max_c < 10:
        max_c = 10
    total_commits = sum(weekly_counts)
    
    # Chart area bounds
    gx0, gx1 = X + 20, FR - 36
    gy0, gy1 = 110, 260
    gw = gx1 - gx0
    gh = gy1 - gy0
    n = len(weeks)

    # Compute points
    pts = []
    for i, c in enumerate(weekly_counts):
        px = gx0 + (i / max(1, n - 1)) * gw
        py = gy1 - (c / max_c) * gh
        pts.append((px, py, c, weeks[i]["firstDay"]))

    # Build smooth cubic bezier path
    path_d = [f"M{_p(pts[0][0], pts[0][1])}"]
    for i in range(1, len(pts)):
        p0 = pts[i - 1]
        p1 = pts[i]
        cpx1 = p0[0] + (p1[0] - p0[0]) * 0.5
        cpy1 = p0[1]
        cpx2 = p0[0] + (p1[0] - p0[0]) * 0.5
        cpy2 = p1[1]
        path_d.append(f"C{_p(cpx1, cpy1)} {_p(cpx2, cpy2)} {_p(p1[0], p1[1])}")

    line_path = "".join(path_d)
    area_path = f"{line_path} L{_p(gx1, gy1)} L{_p(gx0, gy1)} Z"

    # Grid lines & ticks
    grid_lines = []
    for step in [0.0, 0.33, 0.66, 1.0]:
        y_val = gy1 - step * gh
        val_label = int(step * max_c)
        grid_lines.append(f'<line x1="{gx0}" y1="{y_val:.1f}" x2="{gx1}" y2="{y_val:.1f}" stroke="{CYAN}" stroke-opacity=".12" stroke-dasharray="3,3"/>')
        grid_lines.append(f'<text x="{gx0 - 10}" y="{y_val + 4:.1f}" text-anchor="end" class="dim" style="font-size:10px">{val_label}</text>')

    # Month markers on X axis
    month_markers = []
    seen_months = set()
    for i, (px, py, c, d_str) in enumerate(pts):
        dt = datetime.date.fromisoformat(d_str)
        m_str = dt.strftime("%b")
        if m_str not in seen_months:
            seen_months.add(m_str)
            month_markers.append(f'<text x="{px:.1f}" y="{gy1 + 18}" text-anchor="middle" class="dim" style="font-size:10px">{m_str}</text>')
            month_markers.append(f'<line x1="{px:.1f}" y1="{gy1}" x2="{px:.1f}" y2="{gy1 + 4}" stroke="{CYAN}" stroke-opacity=".3"/>')

    # Data points with interactive hover tooltips
    points_svg = []
    for px, py, c, d_str in pts:
        if c > 0:
            dt = datetime.date.fromisoformat(d_str)
            points_svg.append(
                f'<circle class="pt" cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{CYAN}" stroke="#03040a" stroke-width="1.5">'
                f'<title>Week of {dt.strftime("%b %d, %Y")}: {c} contribution{"s" if c != 1 else ""}</title>'
                f'</circle>'
            )

    body = heading(40, "activity-graph", "// 04") + f'''
<g class="ln" style="animation-delay:.15s">
  <text x="{X}" y="82" class="dim" style="font-size:13px">
    <tspan class="gr">$</tspan> render-activity --timeline 52w --metric velocity <tspan fill="#484f58"># interactive commit trend</tspan>
  </text>
  <text x="{FR-36}" y="82" text-anchor="end" class="cy" style="font-size:12px;font-weight:700">
    Peak: {max_c} commits/wk &#160;&#160;<tspan class="dim">|</tspan>&#160;&#160; Total: {total_commits} commits
  </text>
</g>
<g>{"".join(grid_lines)}</g>
<path d="{area_path}" fill="url(#activity_grad)"/>
<path d="{line_path}" fill="none" stroke="{CYAN}" stroke-width="2.5" filter="url(#line_glow)"/>
<path d="{line_path}" fill="none" stroke="#ffffff" stroke-width="1.5" opacity=".85"/>
<g>{"".join(points_svg)}</g>
<g>{"".join(month_markers)}</g>
'''

    css = f"""
.pt{{transition:all .2s ease; cursor:pointer}}
.pt:hover{{r:6.5; fill:#ffffff; filter:drop-shadow(0 0 8px {CYAN}) drop-shadow(0 0 16px {CYAN})}}
"""
    defs = f'''
<linearGradient id="activity_grad" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0%" stop-color="{CYAN}" stop-opacity=".45"/>
  <stop offset="60%" stop-color="{MAGENTA}" stop-opacity=".15"/>
  <stop offset="100%" stop-color="#03040a" stop-opacity="0"/>
</linearGradient>
<filter id="line_glow" x="-20%" y="-40%" width="140%" height="180%">
  <feGaussianBlur stdDeviation="3.5" result="blur"/>
  <feMerge>
    <feMergeNode in="blur"/>
    <feMergeNode in="SourceGraphic"/>
  </feMerge>
</filter>
'''
    desc = f"Weekly activity velocity graph over 52 weeks with peak of {max_c} contributions per week."
    return slice_svg(h, body, title="Activity Graph", desc=desc, css=css, defs=defs)

def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("PROFILE_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN or PROFILE_TOKEN environment variable is required.")
        sys.exit(1)
    login = "satyamshh967"
    today = datetime.date.today()

    query = """query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              firstDay
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }"""

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": login}}).encode("utf-8"),
        headers={"Authorization": f"bearer {token}", "User-Agent": "Antigravity-City-Renderer"}
    )

    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    calendar_data = res["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = calendar_data["weeks"]
    days = {}
    for w in weeks:
        for d in w["contributionDays"]:
            days[datetime.date.fromisoformat(d["date"])] = d["contributionCount"]

    start = today - datetime.timedelta(weeks=52)
    start -= datetime.timedelta(days=(start.weekday() + 1) % 7)
    calendar = [[d.isoformat(), days.get(d, 0)] for d in
                (start + datetime.timedelta(days=i) for i in range((today - start).days + 1))]

    # 1. Build Widescreen Rectangular Panoramic City (height 360px)
    city_svg = build_panoramic_city(calendar, today.isoformat())
    
    # 2. Build Cyberpunk Activity Graph (height 320px)
    graph_svg = build_activity_graph(weeks, today.isoformat())

    here = pathlib.Path(__file__).resolve().parent
    root = here.parent
    out_dir = root / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    city_file = out_dir / "contribution-city.svg"
    city_file.write_text(city_svg, encoding="utf-8")
    print(f"Generated {city_file} successfully! (Size: {len(city_svg)} chars, Widescreen 880x360)")

    graph_file = out_dir / "activity-graph.svg"
    graph_file.write_text(graph_svg, encoding="utf-8")
    print(f"Generated {graph_file} successfully! (Size: {len(graph_svg)} chars, Graph 880x320)")

if __name__ == "__main__":
    main()
