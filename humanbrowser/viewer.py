"""
A standalone replay player for a `--record DIR` run.

`python -m humanbrowser.viewer DIR` (or `build(DIR)`) reads run.json,
traces.json and replays/visitor-NNN/replay.json and writes DIR/index.html: one
self-contained file with the run header, the missed leads ranked, a flow map of
the site as the population walked it, and a step-by-step player for each
replayed visitor (D-030).

Screenshots are clean captures; every mark on them is drawn by this page from
the JSON. The data is embedded at build time so the page opens from file://
without fetch. Everything that came from a page (URLs, link text) is escaped
here or reaches the page's script as JSON and is only ever set as text.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from .budget import _median, wilson
from .ruler import Ruler

TITLES = {"found": "Found it", "quit": "Gave up here",
          "capped": "Still searching at the step cap", "dead_end": "Nothing left to click"}
URL_RE = re.compile(r"https?://[^\s,;]+")
KEEP = 8          # pages shown per map column before the rest fold into "+k more"


# -- loading -------------------------------------------------------------------

def load(run_dir):
    d = Path(run_dir)
    rows = json.loads((d / "traces.json").read_text())
    run = json.loads((d / "run.json").read_text()) if (d / "run.json").is_file() else None
    replays = []
    for f in sorted(d.glob("replays/*/replay.json")):
        try:
            rep = json.loads(f.read_text())
        except ValueError as ex:
            raise ValueError(f"{f}: {ex}") from ex
        replays.append((PurePosixPath(f.parent.relative_to(d).as_posix()), rep))
    return run, rows, replays


def safe_rel(base: PurePosixPath, name) -> str | None:
    """A screenshot path relative to DIR, URL-quoted, or None if it could leave DIR."""
    if not isinstance(name, str) or not name or name.startswith("/") \
            or any(c in name for c in ":\\?#"):
        return None
    p = base / name
    if ".." in p.parts:
        return None
    return quote(p.as_posix())


def _num(x):
    ok = isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    return float(x) if ok else None


def _box(b):
    if isinstance(b, (list, tuple)) and len(b) == 4 and all(_num(v) is not None for v in b):
        return [float(v) for v in b]
    return None


def _idx(i, n):
    return i if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n else None


# -- the flow map --------------------------------------------------------------

def path_of(row) -> list[str]:
    """Pages in visit order: where each click happened, then where the visit ended."""
    return [s["url"] for s in row.get("steps", [])] + [row["exit_url"]]


def flow(rows) -> dict:
    """Pages, click edges and per-page counts.

    `through` counts visitors who were on a page at least once; `stopped` counts
    visitors who ended there without finding the target; `found` counts visitors
    who found it there. They are different quantities and are drawn separately.
    """
    through, stopped, found = Counter(), Counter(), Counter()
    stop_reasons = defaultdict(Counter)
    edges, starts = Counter(), Counter()
    for r in rows:
        p = path_of(r)
        starts[p[0]] += 1
        for u in set(p):
            through[u] += 1
        for a, b in zip(p, p[1:]):
            edges[(a, b)] += 1
        if r["found"]:
            found[r["exit_url"]] += 1
        else:
            stopped[r["exit_url"]] += 1
            stop_reasons[r["exit_url"]][r["reason"]] += 1
    start = starts.most_common(1)[0][0] if starts else None
    return {"start": start, "through": through, "stopped": stopped, "found": found,
            "stop_reasons": stop_reasons, "edges": edges}


def layout(fl) -> dict[str, tuple[int, int]]:
    """(column, row) per page. Column = fewest clicks from the start page;
    rows are ordered to follow each page's parents."""
    out = defaultdict(list)
    for (a, b) in fl["edges"]:
        if a != b:
            out[a].append(b)
    depth = {}
    if fl["start"] is not None:
        depth[fl["start"]] = 0
        q = deque([fl["start"]])
        while q:
            u = q.popleft()
            for v in out[u]:
                if v not in depth:
                    depth[v] = depth[u] + 1
                    q.append(v)
    last = max(depth.values(), default=-1) + 1
    for u in fl["through"]:
        depth.setdefault(u, last)

    cols = defaultdict(list)
    for u in fl["through"]:
        cols[depth[u]].append(u)
    row = {}
    for c in sorted(cols):
        def key(u):
            inc = [(row[a], w) for (a, b), w in fl["edges"].items()
                   if b == u and a in row and depth[a] < c]
            total = sum(w for _, w in inc)
            bary = sum(r * w for r, w in inc) / total if total else 0.0
            return (bary, -fl["through"][u], u)
        for i, u in enumerate(sorted(cols[c], key=key)):
            row[u] = i
    return {u: (depth[u], row[u]) for u in fl["through"]}


def collapse(fl, place, keep: int = KEEP) -> set[str]:
    """Pages folded into their column's "+k more" by default: the lowest-traffic
    ones beyond `keep`. The start page and pages where the target was found never fold."""
    cols = defaultdict(list)
    for u, (c, _) in place.items():
        cols[c].append(u)
    hidden = set()
    for us in cols.values():
        if len(us) <= keep + 1:
            continue
        pinned = {u for u in us if u == fl["start"] or fl["found"][u]}
        rest = sorted((u for u in us if u not in pinned), key=lambda u: (-fl["through"][u], u))
        hidden.update(rest[max(0, keep - len(pinned)):])
    return hidden


# -- missed leads --------------------------------------------------------------

def stuck(rows) -> list[dict]:
    """Missed leads grouped by label, most-missed first.

    A lead missed on several pages is one defect, so it is one row; the pages are
    the breakdown. Visitors are counted once per group (and once per page), and
    always split by outcome: missing the lead is not the same as failing.
    """
    found = {r["visitor"]: bool(r["found"]) for r in rows}
    groups = {}
    for r in rows:
        for s in r.get("steps", []):
            m = s.get("missed")
            if not isinstance(m, dict):
                continue
            name = " ".join(str(m.get("name") or m.get("href") or "(unnamed link)").split())
            g = groups.setdefault(name.casefold(), {"labels": Counter(), "visitors": set(),
                                                    "pages": defaultdict(set), "events": 0,
                                                    "hrefs": set()})
            if m.get("href"):
                g["hrefs"].add(str(m["href"]))
            g["labels"][name] += 1
            g["visitors"].add(r["visitor"])
            g["pages"][s["url"]].add(r["visitor"])
            g["events"] += 1

    def split(vs):
        f = sum(1 for v in vs if found[v])
        return {"missed_by": len(vs), "found_anyway": f, "not_found": len(vs) - f}

    out = []
    for g in groups.values():
        pages = [{"url": u, **split(vs)} for u, vs in g["pages"].items()]
        pages.sort(key=lambda p: (-p["missed_by"], -p["not_found"], p["url"]))
        out.append({"label": g["labels"].most_common(1)[0][0], "events": g["events"],
                    "hrefs": len(g["hrefs"]),
                    **split(g["visitors"]), "pages": pages})
    out.sort(key=lambda g: (-g["missed_by"], -g["not_found"], g["label"]))
    return out


# -- rendering -----------------------------------------------------------------

def e(s) -> str:
    return html.escape(str(s), quote=True)


def label_for(url: str, origins: set[str]) -> str:
    if len(origins) > 1:
        return url
    s = urlsplit(url)
    return (s.path or "/") + (f"?{s.query}" if s.query else "") + (f"#{s.fragment}" if s.fragment else "")


def pct_text(p: float, provisional: bool) -> str:
    return f"{p:.0%} percentile of human task effort" + (" · ruler: PROVISIONAL" if provisional else "")


def split_text(g: dict, n: int) -> str:
    """The only way a missed count is printed: never without the outcome split."""
    return (f"missed by {g['missed_by']} of {n} visitors — "
            f"{g['found_anyway']} found it anyway, {g['not_found']} did not")


def render_stuck(groups, n, ids, labels) -> str:
    if not groups:
        return '<p class="muted">No step in traces.json records a missed lead.</p>'
    items = []
    for g in groups:
        bar = (f'<span class="split" aria-hidden="true">'
               f'<i class="nf" style="width:{100 * g["not_found"] / max(n, 1):.1f}%"></i>'
               f'<i class="fa" style="width:{100 * g["found_anyway"] / max(n, 1):.1f}%"></i></span>')
        pages = []
        for p in g["pages"]:
            name = e(labels.get(p["url"], p["url"]))
            link = (f'<button class="linkish" data-node="{ids[p["url"]]}">{name}</button>'
                    if p["url"] in ids else name)
            pages.append(f'<li>{link}: {e(split_text(p, n))}</li>')
        items.append(
            f'<details class="lead"><summary><b>{e(g["label"])}</b>{bar}'
            f'<span>{e(split_text(g, n))}</span>'
            f'<span class="muted"> · on {len(g["pages"])} page{"s" if len(g["pages"]) != 1 else ""},'
            f' {g["events"]} step{"s" if g["events"] != 1 else ""}'
            f'{f", {hrefs} different links" if (hrefs := g["hrefs"]) > 1 else ""}</span></summary>'
            f'<ul>{"".join(pages)}</ul></details>')
    return "".join(items)


def player_data(replays, ids, labels, pct_of) -> list[dict]:
    out = []
    for base, rep in sorted(replays, key=lambda br: str(br[0])):
        steps = []
        for k, s in enumerate(rep.get("steps") or [], 1):
            cands = [{"name": str(c.get("name") or ""), "href": str(c.get("href") or ""),
                      "box": _box(c.get("box")), "scent": _num(c.get("scent")),
                      "visibility": _num(c.get("visibility")), "score": _num(c.get("score")),
                      "p": _num(c.get("p")), "p_ungated": _num(c.get("p_ungated")), "noticed": c.get("noticed") is not False,
                      "revisit": c.get("revisit") is True}
                     for c in s.get("candidates") or [] if isinstance(c, dict)]
            page = s.get("page") if isinstance(s.get("page"), dict) else {}
            url = str(s.get("url") or "")
            steps.append({"i": s.get("i") if isinstance(s.get("i"), int) else k,
                          "url": url, "label": labels.get(url, url), "node": ids.get(url),
                          "shot": safe_rel(base, s.get("screenshot")),
                          "w": _num(page.get("width")), "h": _num(page.get("height")),
                          "clicked": _idx(s.get("clicked"), len(cands)),
                          "missed": _idx(s.get("missed"), len(cands)),
                          "promise": _num(s.get("promise")), "cost": _num(s.get("cost")),
                          "spent": _num(s.get("spent")), "spent_before": _num(s.get("spent_before")),
                          "candidates": cands})
        end = rep.get("end") if isinstance(rep.get("end"), dict) else {}
        end_url = str(end.get("url") or "")
        end_page = end.get("page") if isinstance(end.get("page"), dict) else {}
        actions = _num(rep.get("actions"))
        reason = str(rep.get("reason") or "")
        nodes = sorted({s["node"] for s in steps if s["node"] is not None}
                       | ({ids[end_url]} if end_url in ids else set()))
        why = URL_RE.sub(lambda m: labels.get(m.group(0), m.group(0)), str(rep.get("why") or ""))
        out.append({"visitor": rep.get("visitor"), "why": why,
                    "found": rep.get("found") is True, "reason": reason,
                    "title": TITLES.get(reason, reason),
                    "actions": actions, "pct": pct_of(actions) if actions is not None else None,
                    "budget": _num(rep.get("budget")), "steps": steps, "nodes": nodes,
                    "end": {"url": end_url, "label": labels.get(end_url, end_url),
                            "node": ids.get(end_url), "shot": safe_rel(base, end.get("screenshot")),
                            "target": _box(end.get("target_box")),
                            "w": _num(end_page.get("width")), "h": _num(end_page.get("height"))}})
    return out


def _json_for_script(obj) -> str:
    return (json.dumps(obj, separators=(",", ":"), allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def render(run, rows, replays, ruler: Ruler) -> str:
    run_measured = ruler.measured if run is None else (run.get("ruler") or {}).get("measured") is True
    provisional = not (ruler.measured and run_measured)

    def pct_of(actions):
        return pct_text(ruler.percentile_of(actions), provisional)

    fl = flow(rows)
    place = layout(fl)
    hidden = collapse(fl, place)
    ids = {u: i for i, u in enumerate(place)}
    origins = {urlsplit(u).netloc for u in place}
    labels = {u: label_for(u, origins) for u in place}
    n = len(rows)

    k = sum(1 for r in rows if r["found"])
    lo, hi = wilson(k, n)
    med_find = _median([r["actions"] for r in rows if r["found"]])
    med_quit = _median([r["actions"] for r in rows if not r["found"]])
    reasons = Counter(r["reason"] for r in rows)

    head = []
    if run is not None:
        head.append(f'<p class="goal">Goal: <q>{e(run.get("goal", ""))}</q></p>')
        meta = [f"start {run.get('start_url', '')}"] + [
            f"{k_} {run[k_]}" for k_ in ("seed", "gate", "scent", "quantile", "max_steps") if k_ in run]
        head.append(f'<p class="muted small">{e(" · ".join(meta))}</p>')
        if run.get("n") not in (None, n):
            head.append(f'<p class="warn">run.json says n={e(run.get("n"))} but traces.json has '
                        f'{n} visitors; the numbers below use traces.json.</p>')
    else:
        head.append('<p class="muted small">No run.json in this directory: goal and settings unknown.</p>')

    stats = [f'<div class="stat"><b>{k}/{n}</b> found it <span class="muted">'
             f'({k / n:.0%}, 95% CI {lo:.0%}–{hi:.0%})</span></div>'
             if n else '<div class="stat">no visitors</div>']
    if med_find is not None:
        stats.append(f'<div class="stat">median <b>{med_find:g}</b> actions to find it · '
                     f'<span class="pct">{e(pct_of(med_find))}</span></div>')
    if med_quit is not None:
        stats.append(f'<div class="stat">median <b>{med_quit:g}</b> actions before stopping</div>')
    stats.append('<div class="stat muted">' + e(" · ".join(
        f"{r} {c}" for r, c in sorted(reasons.items()))) + '</div>')

    nodes = [{"id": ids[u], "label": labels[u], "col": c, "row": r_,
              "through": fl["through"][u], "stopped": fl["stopped"][u], "found": fl["found"][u],
              "start": u == fl["start"], "hidden": u in hidden,
              "reasons": dict(fl["stop_reasons"][u]), "loops": fl["edges"].get((u, u), 0)}
             for u, (c, r_) in place.items()]
    edges = [{"a": ids[a], "b": ids[b], "w": w} for (a, b), w in fl["edges"].items()]
    vp = (run or {}).get("viewport") if isinstance((run or {}).get("viewport"), dict) else {}
    data = {"n": n, "viewport": {"width": _num(vp.get("width")), "height": _num(vp.get("height"))},
            "map": {"nodes": nodes, "edges": edges},
            "replays": player_data(replays, ids, labels, pct_of)}

    return PAGE.format(
        css=CSS, js=JS, data=_json_for_script(data), head="".join(head), stats="".join(stats),
        stuck=render_stuck(stuck(rows), n, ids, labels),
        ruler_note='<p class="muted small">ruler: PROVISIONAL — percentiles are estimated '
                   'from one published statistic, not measured.</p>' if provisional else "")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HumanBrowser replay</title>
<style>{css}</style></head>
<body>
<header>
  <h1>HumanBrowser replay</h1>
  {head}
  <div class="stats">{stats}</div>
  {ruler_note}
</header>
<main>
<section id="player-sec">
  <div class="sec-head"><h2>Replays</h2><span id="filter-note" class="muted small"></span>
    <button id="clear" hidden>Show all</button></div>
  <div id="visitors" class="visitors"></div>
  <div id="player" class="player">
    <ol id="timeline" class="timeline" aria-label="Steps"></ol>
    <div class="centre">
      <div class="controls">
        <button id="prev" aria-label="Previous step">← Prev</button>
        <button id="play" aria-label="Play">▶ Play</button>
        <button id="next" aria-label="Next step">Next →</button>
        <span id="pos" class="muted small"></span>
        <span class="legend small"><i class="lg clicked"></i>clicked <i class="lg missed"></i>missed lead
          <i class="lg subthr"></i>below the noticeability threshold <i class="lg target"></i>the feature</span>
      </div>
      <div id="stage" class="stage" tabindex="0" aria-label="Page screenshot"></div>
    </div>
    <aside id="detail" class="detail"></aside>
  </div>
</section>
<section>
  <div class="sec-head"><h2>Missed leads</h2></div>
  <p class="caveat">A missed lead is the strongest link by scent on a step where it was below the
  noticeability threshold. Missing it is not failing: many visitors who miss it find the feature
  another way, so every count is split by outcome.</p>
  {stuck}
</section>
<section>
  <div class="sec-head">
    <h2>Where visitors went</h2>
    <div class="legend small">
      <span><i class="sw thru"></i>visitors who were on the page</span>
      <span><i class="sw stop"></i>stopped there without finding it</span>
      <span><i class="sw edge"></i>clicks further from the start (thicker = more); select a page
      to see clicks back or sideways and filter the replays</span>
    </div>
  </div>
  <p class="caveat">A page where many visitors stopped is where their patience ran out, which is
  not necessarily where the feature is hard to find (D-026). The missed leads above are the better
  guide.</p>
  <div class="map-wrap"><svg id="map" role="img" aria-label="Flow map of pages visited"></svg></div>
</section>
</main>
<script type="application/json" id="hb-data">{data}</script>
<script>{js}</script>
</body></html>
"""

CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#16181d;--muted:#5f6672;--line:#d9dde3;
--thru:#4d6fa8;--stop:#d0402b;--ok:#1f8a4c;--start:#2a62d9;--edge:#8b93a1;--hi:#2a62d9;
--barbg:#eceff3;--fa:#9db0cf}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121418;--panel:#1b1e24;
--ink:#e7e9ee;--muted:#98a0ad;--line:#2d323b;--thru:#7f9fd6;--stop:#ef6a55;--ok:#4cc27e;
--start:#6e9bff;--edge:#6b7380;--hi:#8fb0ff;--barbg:#2a2f37;--fa:#4a5a78}}
:root[data-theme="dark"]{--bg:#121418;--panel:#1b1e24;--ink:#e7e9ee;--muted:#98a0ad;--line:#2d323b;
--thru:#7f9fd6;--stop:#ef6a55;--ok:#4cc27e;--start:#6e9bff;--edge:#6b7380;--hi:#8fb0ff;--barbg:#2a2f37;--fa:#4a5a78}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,sans-serif}
header,main{max-width:1600px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 6px}h2{font-size:16px;margin:0}
.goal{font-size:15px;margin:0 0 2px}.small{font-size:12px}.muted{color:var(--muted)}
.warn{color:var(--stop);font-size:13px}
.stats{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:8px}.stat b{font-size:17px}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.sec-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin-bottom:8px}
.sec-head h2{margin-right:auto}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--muted);align-items:center}
.sw{display:inline-block;width:18px;height:8px;border-radius:2px;margin-right:6px;vertical-align:middle}
.sw.thru{background:var(--thru)}.sw.stop{background:var(--stop)}.sw.edge{background:var(--edge);height:3px}
.caveat{font-size:12px;color:var(--muted);margin:0 0 10px;max-width:900px}
button{font:inherit;padding:4px 12px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer}
button:hover{border-color:var(--hi)}
.linkish{border:0;background:none;padding:0;color:var(--hi);text-decoration:underline;cursor:pointer}
/* missed leads */
.lead{border-top:1px solid var(--line);padding:6px 0}
.lead summary{cursor:pointer;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center}
.lead ul{margin:6px 0 2px;padding-left:22px;font-size:13px}
.split{display:inline-flex;width:140px;height:10px;background:var(--barbg);border-radius:3px;overflow:hidden}
.split i{display:block;height:100%}.split .nf{background:var(--stop)}.split .fa{background:var(--fa)}
/* player */
.visitors{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.vbtn{display:flex;flex-direction:column;align-items:flex-start;gap:2px;text-align:left;max-width:280px}
.vbtn.cur{border-color:var(--hi);box-shadow:0 0 0 1px var(--hi)}
.badge{font-size:11px;font-weight:700;padding:1px 7px;border-radius:4px;color:#fff;background:var(--stop)}
.badge.found{background:var(--ok)}
.player{display:grid;grid-template-columns:250px minmax(0,1fr) 340px;gap:12px;align-items:start}
@media (max-width:1100px){.player{grid-template-columns:1fr}}
.timeline{list-style:none;margin:0;padding:0;max-height:80vh;overflow:auto;border:1px solid var(--line);border-radius:8px}
.timeline li{display:flex;align-items:stretch;border-bottom:1px solid var(--line)}
.timeline li:last-child{border-bottom:0}
.timeline .step{flex:1;border:0;border-radius:0;background:none;text-align:left;padding:6px 8px;min-width:0}
.timeline .step .nm{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.timeline .step .sub{display:block;font-size:11.5px;color:var(--muted)}
.timeline li.cur{background:color-mix(in srgb,var(--hi) 14%,transparent)}
.timeline li.miss .nm::after{content:" ●";color:var(--stop)}
.timeline .maplink{border:0;border-left:1px solid var(--line);border-radius:0;background:none;font-size:11px;color:var(--hi);padding:0 8px}
.timeline li.end .nm{color:var(--stop)}.timeline li.end.ok .nm{color:var(--ok)}
.centre{min-width:0}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}
.controls .legend{margin-left:auto}
.lg{display:inline-block;width:14px;height:10px;border-radius:2px;margin:0 3px 0 6px;vertical-align:middle}
.lg.clicked{border:2px solid #1d6bff}.lg.missed{border:2px dashed #d93025}
.lg.subthr{border:2px dashed #8a8f98}.lg.target{border:2px solid #188038}
.stage{max-height:80vh;overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff}
.shot{position:relative;width:100%}
.shot img{display:block;width:100%;height:auto}
.marks{position:absolute;inset:0;pointer-events:none}
.mark{position:absolute;border-radius:4px;box-sizing:border-box}
.mark.clicked{border:3px solid #1d6bff;background:rgba(29,107,255,.12)}
.mark.missed{border:3px dashed #d93025;background:rgba(217,48,37,.10)}
.mark.subthr{border:1.5px dashed #8a8f98}
.mark.target{border:3px solid #188038;background:rgba(24,128,56,.12)}
.mark.focus{border:3px solid #f9ab00;background:rgba(249,171,0,.15)}
.mark .tag{position:absolute;left:-3px;bottom:100%;margin-bottom:3px;white-space:nowrap;color:#fff;
font:600 12px/1.3 system-ui,sans-serif;padding:2px 7px;border-radius:4px}
.mark.below .tag{bottom:auto;top:100%;margin:3px 0 0}
.mark.clicked .tag{background:#1d6bff}.mark.missed .tag{background:#d93025}
.mark.target .tag{background:#188038}.mark.focus .tag{background:#b37800}
.fold{position:absolute;left:0;right:0;border-top:2px dashed #f9ab00}
.fold span{position:absolute;right:4px;top:2px;background:#f9ab00;color:#111;font:600 11px system-ui,sans-serif;padding:1px 6px;border-radius:3px}
.detail{border:1px solid var(--line);border-radius:8px;padding:10px;max-height:80vh;overflow:auto;font-size:13px}
.detail h3{font-size:14px;margin:0 0 4px;overflow-wrap:anywhere}
.detail .kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:6px 0}
.detail .kv dt{color:var(--muted)}.detail .kv dd{margin:0}
.callout{border-left:3px solid var(--stop);padding:4px 8px;margin:8px 0;background:color-mix(in srgb,var(--stop) 8%,transparent)}
.callout.ok{border-color:var(--ok);background:color-mix(in srgb,var(--ok) 8%,transparent)}
table.cands{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
.cands th{text-align:right;color:var(--muted);font-weight:600;padding:3px 4px;position:sticky;top:-10px;background:var(--panel)}
.cands td{text-align:right;padding:3px 4px;border-top:1px solid var(--line)}
.cands th:first-child,.cands td:first-child{text-align:left;max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cands tr{cursor:pointer}.cands tr:hover td{background:color-mix(in srgb,var(--hi) 8%,transparent)}
.cands tr.clicked td:first-child{box-shadow:inset 3px 0 #1d6bff;font-weight:700}
.cands tr.missed td:first-child{box-shadow:inset 3px 0 #d93025;font-weight:700}
.cands tr.subthr td{color:var(--muted)}
/* map */
.map-wrap{overflow:auto;max-height:78vh;border-top:1px solid var(--line)}
#map{display:block}
.edge{fill:none;stroke:var(--edge);stroke-opacity:.45}
.edge.back{display:none;stroke-dasharray:5 4}
.edge.hi{display:inline;stroke:var(--hi);stroke-opacity:.9}.edge.dim{stroke-opacity:.06}
.node,.more{cursor:pointer}.node:focus,.more:focus{outline:none}
.node .box{fill:var(--panel);stroke:var(--line);stroke-width:1.2}
.node:hover .box,.node:focus .box,.more:hover .box,.more:focus .box{stroke:var(--hi)}
.node.start .box{stroke:var(--start);stroke-width:2.5}
.node.target .box{stroke:var(--ok);stroke-width:2.5}
.node.sel .box{stroke:var(--hi);stroke-width:3.5}
.node.dim,.more.dim{opacity:.35}
.more .box{fill:var(--bg);stroke:var(--line);stroke-dasharray:4 3}
.lbl{font-size:12.5px;font-weight:600;fill:var(--ink)}.sub{font-size:11px;fill:var(--muted)}
.num{font-size:11px;fill:var(--thru);font-variant-numeric:tabular-nums}.stopnum{fill:var(--stop)}
.bar-bg{fill:var(--barbg)}.bar.thru{fill:var(--thru)}.bar.stop{fill:var(--stop)}
.chip{font-size:10px;font-weight:700;letter-spacing:.04em}
.start-chip{fill:var(--start)}.found-chip{fill:var(--ok)}
"""

JS = r"""
(() => {
const D = JSON.parse(document.getElementById('hb-data').textContent);
const NS = 'http://www.w3.org/2000/svg';
// Every string from the data goes in through append() as text, never as markup.
function h(tag, cls, ...kids) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  for (const k of kids) if (k != null) n.append(k);
  return n;
}
function s(tag, attrs, ...kids) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  for (const k of kids) if (k != null) n.append(k);
  return n;
}
const fx = (x, d = 2) => x == null ? '–' : x.toFixed(d);
const short = (t, n = 27) => t.length <= n ? t : t.slice(0, n - 1) + '…';
const byId = Object.fromEntries(D.map.nodes.map(n => [String(n.id), n]));

// ---------------------------------------------------------------- flow map
const W = 210, H = 58, CG = 96, RG = 14, TOP = 30, LEFT = 90, PAD = 24, BAR = W - 64;
const expanded = new Set();
let sel = null;
const svg = document.getElementById('map');

function drawMap() {
  svg.replaceChildren();
  const disp = {}, cols = {};
  for (const nd of D.map.nodes) {
    const c = cols[nd.col] ||= {shown: [], more: 0, stop: 0, folds: false};
    if (nd.hidden) c.folds = true;
    if (nd.hidden && !expanded.has(nd.col)) {
      disp[nd.id] = 'm' + nd.col; c.more++; c.stop += nd.stopped;
    } else { disp[nd.id] = String(nd.id); c.shown.push(nd); }
  }
  const pos = {};
  let w = 0, hgt = 0;
  for (const [ci, c] of Object.entries(cols)) {
    c.shown.sort((a, b) => a.row - b.row);
    const x = LEFT + Number(ci) * (W + CG);
    c.shown.forEach((nd, i) => { pos[nd.id] = [x, TOP + PAD + i * (H + RG)]; });
    if (c.folds) pos['m' + ci] = [x, TOP + PAD + c.shown.length * (H + RG)];
    w = Math.max(w, x + W + PAD);
    hgt = Math.max(hgt, TOP + PAD + (c.shown.length + (c.folds ? 1 : 0)) * (H + RG) + PAD);
  }
  svg.setAttribute('width', w); svg.setAttribute('height', hgt);
  svg.setAttribute('viewBox', `0 0 ${w} ${hgt}`);

  const agg = new Map();
  for (const ed of D.map.edges) {
    const a = disp[ed.a], b = disp[ed.b];
    if (a === b) continue;
    const k = a + '>' + b;
    if (!agg.has(k)) agg.set(k, {a, b, w: 0});
    agg.get(k).w += ed.w;
  }
  const es = [...agg.values()].sort((p, q) => p.w - q.w);
  const maxw = Math.max(1, ...es.map(x => x.w));
  const eg = s('g', {});
  for (const ed of es) {
    const [ax, ay] = pos[ed.a], [bx, by] = pos[ed.b];
    const y1 = ay + H / 2, y2 = by + H / 2;
    let x1, x2, c1, c2;
    if (bx > ax) { x1 = ax + W; x2 = bx; const d = Math.max(60, (x2 - x1) / 2); c1 = x1 + d; c2 = x2 - d; }
    else if (bx === ax) { x1 = x2 = ax; c1 = c2 = ax - 30 - Math.abs(y2 - y1) * 0.12; }
    else { x1 = ax; x2 = bx + W; c1 = x1 - 40; c2 = x2 + 40; }
    const name = id => id[0] === 'm' ? 'other pages' : byId[id].label;
    eg.append(s('path', {class: 'edge' + (bx <= ax ? ' back' : ''), 'data-a': ed.a, 'data-b': ed.b,
      d: `M${x1},${y1} C${c1},${y1} ${c2},${y2} ${x2},${y2}`, 'stroke-width': (1 + 7 * ed.w / maxw).toFixed(1)},
      s('title', {}, `${name(ed.a)} → ${name(ed.b)}: ${ed.w} click${ed.w === 1 ? '' : 's'}`)));
  }
  svg.append(eg);

  const ng = s('g', {});
  for (const [ci, c] of Object.entries(cols)) {
    for (const nd of c.shown) ng.append(nodeEl(nd, pos[nd.id]));
    if (!c.folds) continue;
    const [x, y] = pos['m' + ci], open = expanded.has(Number(ci));
    const g = s('g', {class: 'more', tabindex: 0, role: 'button', transform: `translate(${x},${y})`},
      s('rect', {class: 'box', width: W, height: H, rx: 7}),
      s('text', {class: 'lbl', x: 10, y: 24}, open ? 'Show fewer pages' : `+${c.more} more page${c.more === 1 ? '' : 's'}`),
      s('text', {class: 'sub', x: 10, y: 42}, open ? 'fold the low-traffic pages' : `${c.stop} stopped on them · click to show`));
    const toggle = () => { open ? expanded.delete(Number(ci)) : expanded.add(Number(ci)); drawMap(); };
    g.addEventListener('click', toggle);
    g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } });
    ng.append(g);
  }
  svg.append(ng);
  highlight();
}

function nodeEl(nd, [x, y]) {
  const n = D.n || 1;
  const tip = [nd.label, `${nd.through}/${D.n} visitors were here`];
  if (nd.stopped) tip.push(`${nd.stopped} stopped here without finding it (` +
    Object.entries(nd.reasons).map(([k, v]) => `${k} ${v}`).join(', ') + ')');
  if (nd.found) tip.push(`${nd.found} found the target here`);
  if (nd.loops) tip.push(`${nd.loops} click${nd.loops === 1 ? '' : 's'} stayed on this page`);
  const g = s('g', {class: 'node' + (nd.start ? ' start' : '') + (nd.found ? ' target' : ''),
    'data-id': nd.id, tabindex: 0, role: 'button', transform: `translate(${x},${y})`},
    s('title', {}, tip.join('\n')),
    s('rect', {class: 'box', width: W, height: H, rx: 7}),
    nd.start ? s('text', {class: 'chip start-chip', x: 0, y: -6}, 'START') : null,
    nd.found ? s('text', {class: 'chip found-chip', x: W, y: -6, 'text-anchor': 'end'}, `FOUND HERE · ${nd.found}`) : null,
    s('text', {class: 'lbl', x: 10, y: 19}, short(nd.label)),
    s('rect', {class: 'bar-bg', x: 10, y: 28, width: BAR, height: 8, rx: 2}),
    s('rect', {class: 'bar thru', x: 10, y: 28, width: (BAR * nd.through / n).toFixed(1), height: 8, rx: 2}),
    s('text', {class: 'num', x: W - 8, y: 36, 'text-anchor': 'end'}, String(nd.through)),
    s('rect', {class: 'bar-bg', x: 10, y: 41, width: BAR, height: 8, rx: 2}),
    s('rect', {class: 'bar stop', x: 10, y: 41, width: (BAR * nd.stopped / n).toFixed(1), height: 8, rx: 2}),
    s('text', {class: 'num stopnum', x: W - 8, y: 49, 'text-anchor': 'end'}, String(nd.stopped)));
  g.addEventListener('click', () => select(String(nd.id), true));
  g.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); ev.stopPropagation(); select(String(nd.id), true); }
  });
  return g;
}

function highlight() {
  const near = new Set(sel === null ? [] : [sel]);
  svg.querySelectorAll('.edge').forEach(p => {
    const on = sel !== null && (p.dataset.a === sel || p.dataset.b === sel);
    if (on) { near.add(p.dataset.a); near.add(p.dataset.b); }
    p.classList.toggle('hi', on);
    p.classList.toggle('dim', sel !== null && !on);
  });
  svg.querySelectorAll('.node').forEach(g => {
    g.classList.toggle('sel', g.dataset.id === sel);
    g.setAttribute('aria-pressed', g.dataset.id === sel);
    g.classList.toggle('dim', sel !== null && !near.has(g.dataset.id));
  });
  svg.querySelectorAll('.more').forEach(g => g.classList.toggle('dim', sel !== null));
}

function select(id, toggle, reveal) {
  sel = (toggle && sel === id) ? null : id;
  if (sel !== null && byId[sel] && byId[sel].hidden) expanded.add(byId[sel].col);
  drawMap();
  listVisitors();
  if (reveal && sel !== null) {
    const g = svg.querySelector(`.node[data-id="${sel}"]`);
    if (g) g.scrollIntoView({block: 'center', inline: 'center', behavior: 'smooth'});
  }
}
document.getElementById('clear').addEventListener('click', () => select(null));
document.querySelectorAll('[data-node]').forEach(b =>
  b.addEventListener('click', () => select(b.dataset.node, false, true)));

// ---------------------------------------------------------------- player
const R = D.replays;
let cur = R.length ? 0 : -1, f = 0, timer = null, focusIdx = null;
const $ = id => document.getElementById(id);
const visitorsEl = $('visitors'), tl = $('timeline'), stage = $('stage'), detail = $('detail');

function visible() { return R.map((r, i) => i).filter(i => sel === null || R[i].nodes.includes(Number(sel))); }

function listVisitors() {
  const vis = visible();
  if (vis.length && !vis.includes(cur)) { cur = vis[0]; f = 0; stop(); }
  visitorsEl.replaceChildren(...vis.map(i => {
    const r = R[i];
    const b = h('button', 'vbtn' + (i === cur ? ' cur' : ''),
      h('span', null, h('span', 'badge' + (r.found ? ' found' : ''), r.title), ` visitor ${r.visitor}`),
      h('span', 'muted small', `${r.actions ?? '?'} actions${r.why ? ' · ' + r.why : ''}`));
    b.addEventListener('click', () => { stop(); cur = i; f = 0; listVisitors(); });
    return b;
  }));
  if (!R.length) visitorsEl.append(h('p', 'muted', 'No replays in this directory (replays/visitor-NNN/replay.json).'));
  const note = $('filter-note');
  if (sel === null) { note.textContent = R.length ? 'Select a page on the map to show only replays that passed through it.' : ''; }
  else {
    const nd = byId[sel];
    note.textContent = `${nd.label}: ${nd.through} of ${D.n} visitors were on this page; ` +
      `${vis.length} of ${R.length} replays passed through it.`;
  }
  $('clear').hidden = sel === null;
  $('player').hidden = !vis.length;
  if (vis.length) buildTimeline();
}

function patience(r, spent) {
  if (r.budget == null) return 'patience unlimited';
  if (spent == null) return 'patience ?';
  return `patience ${Math.round(Math.max(0, 1 - spent / r.budget) * 100)}%`;
}

function buildTimeline() {
  const r = R[cur];
  const rows = r.steps.map((st, k) => {
    const c = st.clicked != null ? st.candidates[st.clicked] : null;
    const btn = h('button', 'step', h('span', 'nm', `${st.i}. ${c ? c.name || c.href || '?' : '?'}`),
      h('span', 'sub', `${short(st.label, 22)} · ${patience(r, st.spent)} left`));
    btn.addEventListener('click', () => go(k));
    const li = h('li', st.missed != null ? 'miss' : '', btn);
    if (st.node != null) {
      const m = h('button', 'maplink', 'map');
      m.title = 'Show this page on the flow map';
      m.addEventListener('click', () => select(String(st.node), false, true));
      li.append(m);
    }
    return li;
  });
  const endBtn = h('button', 'step', h('span', 'nm', r.title),
    h('span', 'sub', `${r.actions ?? '?'} actions`), r.pct ? h('span', 'sub pct', r.pct) : null);
  endBtn.addEventListener('click', () => go(r.steps.length));
  const endLi = h('li', 'end' + (r.found ? ' ok' : ''), endBtn);
  if (r.end.node != null) {
    const m = h('button', 'maplink', 'map');
    m.addEventListener('click', () => select(String(r.end.node), false, true));
    endLi.append(m);
  }
  tl.replaceChildren(...rows, endLi);
  show();
}

function go(k) { const r = R[cur]; f = Math.max(0, Math.min(r.steps.length, k)); focusIdx = null; show(); }

function mark(ov, box, w, hh, kind, tag) {
  if (!box) return null;
  const [x, y, bw, bh] = box, p = 4;
  const m = h('div', 'mark ' + kind + (y < 34 ? ' below' : ''), tag ? h('span', 'tag', tag) : null);
  m.style.left = `${(x - p) / w * 100}%`; m.style.top = `${(y - p) / hh * 100}%`;
  m.style.width = `${(bw + 2 * p) / w * 100}%`; m.style.height = `${(bh + 2 * p) / hh * 100}%`;
  ov.append(m);
  return m;
}

function show() {
  const r = R[cur], last = r.steps.length, st = f < last ? r.steps[f] : null;
  tl.querySelectorAll('li').forEach((li, k) => li.classList.toggle('cur', k === f));
  const curLi = tl.children[f];
  if (curLi) curLi.scrollIntoView({block: 'nearest'});
  $('pos').textContent = st ? `step ${f + 1} of ${last} · then the outcome` : 'outcome';
  $('prev').disabled = f === 0; $('next').disabled = f === last;

  const shot = st ? st.shot : r.end.shot;
  stage.replaceChildren();
  if (!shot) stage.append(h('p', 'muted', ' No screenshot for this frame.'));
  else {
    const inner = h('div', 'shot'), img = new Image(), ov = h('div', 'marks');
    img.src = shot; img.alt = `Screenshot of ${st ? st.label : r.end.label}`;
    inner.append(img, ov); stage.append(inner);
    const place = (w, hh) => {
      if (!w || !hh) return;
      inner.style.aspectRatio = `${w} / ${hh}`;
      let focus = null;
      if (st) {
        st.candidates.forEach((c, k) => {
          if (!c.noticed && k !== st.clicked && k !== st.missed) mark(ov, c.box, w, hh, 'subthr');
        });
        if (st.missed != null) {
          const c = st.candidates[st.missed];
          mark(ov, c.box, w, hh, 'missed', `strongest lead, below the noticeability threshold: ${c.name || c.href}`);
        }
        if (st.clicked != null) {
          const c = st.candidates[st.clicked];
          focus = mark(ov, c.box, w, hh, 'clicked', `clicks: ${c.name || c.href}`);
        }
        if (focusIdx != null) {
          const c = st.candidates[focusIdx];
          focus = mark(ov, c.box, w, hh, 'focus', c.name || c.href) || focus;
        }
      } else if (r.found && r.end.target) {
        focus = mark(ov, r.end.target, w, hh, 'target', 'the feature');
      }
      const vh = D.viewport.height;
      if (vh && vh < hh) {
        const fold = h('div', 'fold', h('span', null, 'fold'));
        fold.style.top = `${vh / hh * 100}%`;
        ov.append(fold);
      }
      requestAnimationFrame(() => {
        if (!focus) { stage.scrollTop = 0; return; }
        const y = focus.offsetTop + focus.offsetHeight / 2;
        stage.scrollTop = Math.max(0, y - stage.clientHeight / 2);
      });
    };
    const fw = st ? st.w : r.end.w, fh = st ? st.h : r.end.h;
    if (fw && fh) place(fw, fh);
    else img.addEventListener('load', () => place(img.naturalWidth, img.naturalHeight));
  }
  showDetail(r, st);
}

const pc = x => `${(x * 100).toFixed(1)}%`;
function change(before, after) {
  if (after < before) return `Visibility cut its click chance from ${pc(before)} to ${pc(after)}.`;
  if (after > before) return `Visibility raised its click chance from ${pc(before)} to ${pc(after)}.`;
  return `Visibility left its click chance at ${pc(after)}.`;
}

function kv(pairs) {
  const dl = h('dl', 'kv');
  for (const [k, v] of pairs) dl.append(h('dt', null, k), h('dd', null, v));
  return dl;
}

function showDetail(r, st) {
  detail.replaceChildren();
  if (!st) {
    const lastSt = r.steps[r.steps.length - 1];
    detail.append(h('h3', null, r.title),
      kv([['visitor', String(r.visitor)], ['page', r.end.label], ['actions', String(r.actions ?? '?')],
          ['effort', r.pct || '–'], ['patience left', patience(r, lastSt ? lastSt.spent : 0).replace('patience ', '')],
          ['picked because', r.why || '–']]));
    detail.append(r.found
      ? h('p', 'callout ok', r.end.target ? 'The feature is outlined in green.' : 'Found; the target box was not captured.')
      : h('p', 'callout', 'The visit ended here. This is where patience ran out, not necessarily where the feature was missed (D-026).'));
    return;
  }
  const before = st.spent_before != null ? st.spent_before
    : st.spent != null && st.cost != null ? st.spent - st.cost : null;
  detail.append(h('h3', null, `Step ${st.i} · ${st.label}`),
    kv([['patience', `${patience(r, before).replace('patience ', '')} → ${patience(r, st.spent).replace('patience ', '')}`],
        ['this action cost', fx(st.cost)], ['spent after', fx(st.spent)],
        ['budget', r.budget == null ? 'unlimited' : fx(r.budget)], ['promise', fx(st.promise, 3)]]));
  if (st.missed != null) {
    const c = st.candidates[st.missed];
    detail.append(h('p', 'callout', 'Strongest lead by scent, below the noticeability threshold: ',
      h('b', null, c.name || c.href), ` (scent ${fx(c.scent, 3)}, visibility ${fx(c.visibility, 3)}).`,
      c.p_ungated != null && c.p != null ? ' ' + change(c.p_ungated, c.p) : null));
  }
  const ung = st.candidates.some(c => c.p_ungated != null);
  const order = st.candidates.map((c, k) => k)
    .sort((a, b) => (st.candidates[b].p ?? -1) - (st.candidates[a].p ?? -1) ||
                    (st.candidates[b].scent ?? -1) - (st.candidates[a].scent ?? -1));
  const tb = h('tbody');
  for (const k of order) {
    const c = st.candidates[k];
    const flags = [k === st.clicked ? 'clicked' : '', k === st.missed ? 'missed' : '', !c.noticed ? 'subthr' : '']
      .filter(Boolean).join(' ');
    const words = [k === st.clicked ? 'clicked' : '', k === st.missed ? 'missed lead' : '',
      !c.noticed ? 'below the noticeability threshold' : ''].filter(Boolean).join(', ');
    const tr = h('tr', flags,
      h('td', null, (c.name || c.href || '?') + (c.revisit ? ' ↺' : '')),
      h('td', null, fx(c.scent, 3)), h('td', null, fx(c.visibility, 2)),
      h('td', null, fx(c.score, 3)), h('td', null, fx(c.p, 3)),
      ung ? h('td', null, fx(c.p_ungated, 3)) : null);
    tr.title = [c.name, c.href, words, c.revisit ? 'already visited' : ''].filter(Boolean).join('\n');
    tr.addEventListener('click', () => { focusIdx = k; show(); });
    tb.append(tr);
  }
  detail.append(h('p', 'muted small', `${st.candidates.length} links on the page, ranked by click probability. ` +
    'Links below the noticeability threshold are less likely to be clicked, not impossible: ' +
    'the gate down-weights them rather than removing them (D-003). ' +
    (ung ? '"p gate off" is the click probability with the visibility gate turned off. ' : '') +
    'Click a row to outline it. ↺ = already visited.'),
    h('table', 'cands', h('thead', null, h('tr', null, h('th', null, 'link'), h('th', null, 'scent'),
      h('th', null, 'vis'), h('th', null, 'score'), h('th', null, 'p'),
      ung ? h('th', null, 'p gate off') : null)), tb));
}

function stop() { if (timer) clearInterval(timer); timer = null; $('play').textContent = '▶ Play'; }
function play() {
  if (timer) return stop();
  const r = R[cur];
  if (f >= r.steps.length) go(0);
  $('play').textContent = '❚❚ Pause';
  timer = setInterval(() => { if (f >= R[cur].steps.length) stop(); else go(f + 1); }, 1600);
}
$('prev').addEventListener('click', () => { stop(); go(f - 1); });
$('next').addEventListener('click', () => { stop(); go(f + 1); });
$('play').addEventListener('click', play);
document.addEventListener('keydown', ev => {
  if (cur < 0 || ev.altKey || ev.ctrlKey || ev.metaKey) return;
  if (ev.target.closest && ev.target.closest('input,textarea,select,svg')) return;
  if (ev.key === 'ArrowRight') { ev.preventDefault(); stop(); go(f + 1); }
  else if (ev.key === 'ArrowLeft') { ev.preventDefault(); stop(); go(f - 1); }
  else if (ev.key === ' ') { ev.preventDefault(); play(); }
});

drawMap();
listVisitors();
})();
"""


def build(run_dir, ruler: Ruler | None = None) -> Path:
    """Write DIR/index.html for a --record DIR run and return its path."""
    run, rows, replays = load(run_dir)
    out = Path(run_dir) / "index.html"
    out.write_text(render(run, rows, replays, ruler or Ruler.load()))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m humanbrowser.viewer",
                                 description="Write DIR/index.html for a --record DIR run.")
    ap.add_argument("dir")
    args = ap.parse_args(argv)
    if not (Path(args.dir) / "traces.json").is_file():
        print(f"no traces.json in {args.dir}", file=sys.stderr)
        return 2
    print(build(args.dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
