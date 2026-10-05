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

CITY_TW, CITY_TH = 25, 12.5                  # iso tile width / height
CITY_OX, CITY_OY = 152.5, 262                # grid origin inside the 880-wide slice
CITY_HMAX = 118                              # tallest building, px

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

def build_city(calendar, updated):
    days = [(datetime.date.fromisoformat(d), n) for d, n in calendar]
    counts = [n for _, n in days]
    total, peak = sum(counts), max(counts) if counts else 0
    lv = _levels(counts)
    rnd = _rng(f"{updated}-{total}")
    start = days[0][0]

    cells = []
    for d, n in days:
        idx = (d - start).days
        cells.append((idx // 7, (d.weekday() + 1) % 7, n))
    cells.sort(key=lambda c: (c[0] + c[1], c[0]))

    shapes, flick = [], 0
    for w, dow, n in cells:
        cx = CITY_OX + (w - dow) * CITY_TW / 2
        cy = CITY_OY + (w + dow) * CITY_TH / 2
        L, R = (cx - CITY_TW / 2, cy), (cx + CITY_TW / 2, cy)
        T, B = (cx, cy - CITY_TH / 2), (cx, cy + CITY_TH / 2)
        if n == 0:
            shapes.append(f'<path d="M{_p(*T)}L{_p(*R)}L{_p(*B)}L{_p(*L)}Z" fill="#161b22" stroke="#0d1117" stroke-width=".6"/>')
            continue
        h = 8 + (CITY_HMAX - 8) * math.sqrt(n / peak)
        level = sum(n > t for t in lv)
        Tu, Ru, Bu, Lu = [(x, y - h) for x, y in (T, R, B, L)]
        shapes.append(f'<path d="M{_p(*L)}L{_p(*B)}L{_p(*Bu)}L{_p(*Lu)}Z" fill="#1a2440"/>'
                      f'<path d="M{_p(*B)}L{_p(*Ru)}L{_p(*Bu)}Z" fill="#111831"/>'
                      f'<path d="M{_p(*Tu)}L{_p(*Ru)}L{_p(*Bu)}L{_p(*Lu)}Z" fill="{ROOFS[level]}"/>')
        on, side, off, fl = [], [], [], []
        for face, (a, b) in (("l", (L, B)), ("r", (B, R))):
            for r in range(int((h - 6) // 7)):
                v0 = 5 + r * 7
                for u0 in (.18, .58):
                    lit = next(rnd) < .55
                    if not lit and next(rnd) < .5:
                        continue
                    pts = [(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u - v)
                           for u, v in ((u0, v0), (u0 + .26, v0), (u0 + .26, v0 + 3.2), (u0, v0 + 3.2))]
                    seg = "M" + "L".join(_p(*q) for q in pts) + "Z"
                    if not lit:
                        off.append(seg)
                    elif next(rnd) < .03:
                        fl.append((seg, face))
                    else:
                        (on if face == "l" else side).append(seg)
        if off:
            shapes.append(f'<path d="{"".join(off)}" fill="{WIN_OFF}"/>')
        if on:
            shapes.append(f'<path d="{"".join(on)}" fill="{WIN_ON}"/>')
        if side:
            shapes.append(f'<path d="{"".join(side)}" fill="{WIN_ON_SIDE}"/>')
        for seg, face in fl:
            flick += 1
            shapes.append(f'<path class="f{flick % 3}" d="{seg}" fill="{WIN_ON if face == "l" else WIN_ON_SIDE}"/>')

    stars = []
    for i in range(46):
        x, y = 470 + next(rnd) * 350, 118 + next(rnd) * 150
        if x > 700 and y < 215:
            continue
        cls = f' class="s{i % 3}"' if i % 3 == 0 else ""
        stars.append(f'<circle{cls} cx="{x:.1f}" cy="{y:.1f}" r="{(.6, .8, 1.1)[i % 3]}" fill="#c9d1d9" opacity="{.35 + next(rnd) * .5:.2f}"/>')
    
    busiest_d, busiest_n = max(days, key=lambda t: t[1]) if days and peak > 0 else (None, 0)
    info = [
        f'<tspan class="cy" font-weight="700">{total:,}</tspan> contributions \u00b7 last 365 days',
        f'busiest day <tspan class="fg">{busiest_d:%b} {busiest_d.day}</tspan> \u00b7 {busiest_n}' if busiest_n else "",
        f'{sum(1 for n in counts if n)} active days'
    ]
    info_svg = "".join(f'<text x="{FR-36}" y="{300 + i*20}" text-anchor="end" class="dim" style="font-size:12px">{t}</text>'
                       for i, t in enumerate(info) if t)
    legend = "".join(f'<rect x="{X + 52 + i*16}" y="{642}" width="11" height="11" fill="{c}"/>'
                     for i, c in enumerate(["#161b22"] + ROOFS))
    
    body = heading(44, "contribution-city", "// 03") + f'''
<g class="ln" style="animation-delay:.15s"><text x="{X}" y="96" class="dim"><tspan class="gr">$</tspan> render-city --last 365d <tspan fill="#484f58"># one building per day</tspan></text></g>
<g>{"".join(stars)}</g>
<circle cx="{FR-80}" cy="{160}" r="40" fill="url(#moonglow)"/>
<circle cx="{FR-80}" cy="{160}" r="14" fill="#e6edf3"/>
<circle cx="{FR-74}" cy="{155}" r="12.5" fill="#03040a"/>
<g class="plane"><g transform="translate(0 132)"><rect x="0" y="0" width="14" height="2" rx="1" fill="#484f58"/><circle class="bl" cx="0" cy="1" r="1.6" fill="#ff7b72"/><circle class="bl" cx="14" cy="1" r="1.6" fill="#f0f6fc" style="animation-delay:.7s"/></g></g>
{info_svg}
{"".join(shapes)}
<text x="{X}" y="{652}" class="dim" style="font-size:11px">quiet</text>{legend}<text x="{X + 52 + 5*16 + 6}" y="{652}" class="dim" style="font-size:11px">skyscraper</text>'''

    css = f"""@keyframes tw{{0%,100%{{opacity:.9}}50%{{opacity:.15}}}}
@keyframes fl{{0%,40%,100%{{opacity:1}}45%,60%{{opacity:.1}}}}
@keyframes blink{{0%,90%,100%{{opacity:0}}93%{{opacity:1}}}}
@keyframes fly{{from{{transform:translate({FL - 40}px,0)}}to{{transform:translate({FR + 40}px,-30px)}}}}
.s0{{animation:tw 3s infinite}}
.f0{{animation:fl 5s infinite}}.f1{{animation:fl 7s infinite 2s}}.f2{{animation:fl 9s infinite 4s}}
.plane{{animation:fly 26s linear infinite}}.bl{{animation:blink 1.4s infinite}}"""
    defs = f'<radialGradient id="moonglow"><stop offset="0" stop-color="#f0f6fc" stop-opacity=".22"/><stop offset="1" stop-color="#f0f6fc" stop-opacity="0"/></radialGradient>'
    desc = (f"Contribution city: an isometric night skyline with one building per day of the last year, "
            f"taller and brighter for busier days. {total:,} contributions"
            + (f", busiest day {busiest_d:%B} {busiest_d.day} with {busiest_n}" if busiest_n else "") + ".")
    
    return slice_svg(680, body, title="Contribution city", desc=desc, css=css, defs=defs)

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
    days = {}
    for w in calendar_data["weeks"]:
        for d in w["contributionDays"]:
            days[datetime.date.fromisoformat(d["date"])] = d["contributionCount"]

    start = today - datetime.timedelta(weeks=52)
    start -= datetime.timedelta(days=(start.weekday() + 1) % 7)
    calendar = [[d.isoformat(), days.get(d, 0)] for d in
                (start + datetime.timedelta(days=i) for i in range((today - start).days + 1))]

    svg_content = build_city(calendar, today.isoformat())
    
    here = pathlib.Path(__file__).resolve().parent
    root = here.parent
    out_dir = root / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "contribution-city.svg"
    out_file.write_text(svg_content, encoding="utf-8")
    print(f"Generated {out_file} successfully! Size: {len(svg_content)} chars")

if __name__ == "__main__":
    main()
