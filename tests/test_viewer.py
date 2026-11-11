"""Invariants of the replay viewer. No golden numbers (D-013)."""
from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path, PurePosixPath

import pytest

from humanbrowser import viewer
from humanbrowser.ruler import Ruler, provisional

O = "http://site.test"
LEAD = {"name": "Restock alerts", "href": "/alerts", "scent": 0.4, "visibility": 0.1}


def row(i, found, urls, exit_url, missed=(), clicked=None, reason=None):
    steps = [{"url": u, "clicked": (clicked or {}).get(k, f"link{k}"), "href": f"/l{k}",
              "promise": 0.1, "visibility": 0.5, "spent_before": float(k),
              "missed": dict(LEAD) if k in missed else None} for k, u in enumerate(urls)]
    return {"visitor": i, "found": found, "reason": reason or ("found" if found else "quit"),
            "actions": len(urls), "spent": float(len(urls)), "budget": 8.0,
            "persistence": 0.5, "exit_url": exit_url, "steps": steps, "unnoticed": []}


ROWS = [
    row(0, True, [f"{O}/", f"{O}/a"], f"{O}/goal", missed=(0,)),
    row(1, False, [f"{O}/", f"{O}/b", f"{O}/a"], f"{O}/", missed=(0, 1, 2), reason="quit"),
    row(2, False, [f"{O}/", f"{O}/b", f"{O}/b"], f"{O}/c", missed=(1,), reason="capped"),
    row(3, True, [f"{O}/", f"{O}/b"], f"{O}/goal"),
    row(4, False, [], f"{O}/", reason="dead_end"),
]


def cand(name, y, noticed=True, p=0.25):
    return {"name": name, "href": f"/{name}", "box": [10, y, 80, 20], "scent": 0.2,
            "visibility": 0.5 if noticed else 0.1, "score": 0.1, "p": p,
            "noticed": noticed, "revisit": False}


def replay(r, why="typical"):
    steps = []
    for k, s in enumerate(r["steps"], 1):
        cands = [cand(s["clicked"], 50), cand("Other", 100), cand(LEAD["name"], 700, noticed=False, p=0.0)]
        steps.append({"i": k, "url": s["url"], "screenshot": f"step-{k:02d}.png",
                      "page": {"width": 400, "height": 800}, "clicked": 0, "promise": 0.1,
                      "cost": 1.0, "spent": float(k), "missed": 2 if s["missed"] else None,
                      "candidates": cands})
    return {"visitor": r["visitor"], "why": why, "found": r["found"], "reason": r["reason"],
            "actions": r["actions"], "budget": r["budget"], "persistence": r["persistence"],
            "steps": steps, "end": {"url": r["exit_url"], "screenshot": "end.png",
                                    "target_box": [20, 30, 200, 60] if r["found"] else None}}


RUN = {"goal": "find the restock alerts", "start_url": f"{O}/", "target": "#t", "n": len(ROWS),
       "seed": 1, "gate": "all", "scent": "lexical", "quantile": 0.9, "max_steps": 20,
       "viewport": {"width": 400, "height": 300}, "ruler": {"measured": False},
       "found": 2, "reasons": {"found": 2, "quit": 1, "capped": 1, "dead_end": 1}}


def png(w, h):
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_dir(root, rows=ROWS, run=RUN, replay_of=(1, 3)):
    (root / "traces.json").write_text(json.dumps(rows))
    if run is not None:
        (root / "run.json").write_text(json.dumps(run))
    for v in replay_of:
        d = root / "replays" / f"visitor-{v:03d}"
        d.mkdir(parents=True)
        rep = replay(rows[v])
        (d / "replay.json").write_text(json.dumps(rep))
        for s in rep["steps"]:
            (d / s["screenshot"]).write_bytes(png(400, 800))
        (d / "end.png").write_bytes(png(400, 800))
    return root


def measured_ruler():
    return Ruler(counts=list(range(1, 21)), quantiles={}, mean=10.5, n=20,
                 provenance="test", measured=True)


# -- flow map ------------------------------------------------------------------

def test_every_visited_page_is_a_node_with_a_unique_place():
    fl = viewer.flow(ROWS)
    place = viewer.layout(fl)
    for r in ROWS:
        assert all(u in place for u in viewer.path_of(r))
    assert len(set(place.values())) == len(place)


def test_edge_weights_sum_to_clicks():
    assert sum(viewer.flow(ROWS)["edges"].values()) == sum(len(r["steps"]) for r in ROWS)


def test_counts_are_separate_and_consistent():
    fl = viewer.flow(ROWS)
    assert fl["through"][fl["start"]] == len(ROWS)
    assert sum(fl["stopped"].values()) == sum(1 for r in ROWS if not r["found"])
    assert sum(fl["found"].values()) == sum(1 for r in ROWS if r["found"])
    for u, t in fl["through"].items():
        assert fl["stopped"][u] + fl["found"][u] <= t <= len(ROWS)


def test_start_page_is_column_zero():
    fl = viewer.flow(ROWS)
    assert viewer.layout(fl)[fl["start"]][0] == 0


def test_collapse_folds_only_low_traffic_pages_and_never_start_or_target():
    wide = [row(i, i == 0, [f"{O}/", f"{O}/p{i}"], f"{O}/goal" if i == 0 else f"{O}/p{i}")
            for i in range(20)]
    fl = viewer.flow(wide)
    place = viewer.layout(fl)
    hidden = viewer.collapse(fl, place, keep=5)
    assert hidden
    assert fl["start"] not in hidden and not any(fl["found"][u] for u in hidden)
    by_col = {}
    for u, (c, _) in place.items():
        by_col.setdefault(c, []).append(u)
    for us in by_col.values():
        shown = [u for u in us if u not in hidden]
        if any(u in hidden for u in us):
            assert len(shown) <= 5
            assert min(fl["through"][u] for u in shown) >= max(fl["through"][u] for u in us if u in hidden)
    assert not viewer.collapse(viewer.flow(ROWS), viewer.layout(viewer.flow(ROWS)), keep=5)


# -- missed leads --------------------------------------------------------------

def test_missed_leads_are_split_by_outcome_and_grouped_by_label():
    groups = viewer.stuck(ROWS)
    assert len(groups) == 1
    g = groups[0]
    assert g["found_anyway"] + g["not_found"] == g["missed_by"] <= len(ROWS)
    assert g["events"] == sum(1 for r in ROWS for s in r["steps"] if s["missed"])
    assert len(g["pages"]) > 1
    for p in g["pages"]:
        assert p["found_anyway"] + p["not_found"] == p["missed_by"] <= g["missed_by"]


def test_labels_differing_only_in_case_and_space_are_one_lead():
    rows = [row(0, False, [f"{O}/", f"{O}/x"], f"{O}/x", missed=(0, 1))]
    rows[0]["steps"][1]["missed"]["name"] = "  restock   ALERTS "
    assert len(viewer.stuck(rows)) == 1


def test_no_missed_count_is_printed_without_its_split():
    page = viewer.render(RUN, ROWS, [], provisional())
    assert page.count("missed by ") == page.count("found it anyway") > 0


# -- safety --------------------------------------------------------------------

def test_page_supplied_text_is_escaped(tmp_path):
    evil = '<script>alert("x")</script>'
    rows = [row(0, False, [f"{O}/", f'{O}/"><img src=x onerror=alert(1)>'], f"{O}/</script>",
                missed=(0,), clicked={0: evil, 1: "a & b"})]
    rows[0]["steps"][0]["missed"]["name"] = evil
    rep = replay(rows[0], why=evil)
    run = dict(RUN, goal=evil, start_url=evil)
    page = viewer.render(run, rows, [(PurePosixPath("replays/visitor-000"), rep)], provisional())
    assert evil not in page and "<img src=x" not in page
    assert page.count("<script") == 2 and page.count("</script>") == 2
    data = re.search(r'<script type="application/json" id="hb-data">(.*?)</script>', page, re.S).group(1)
    assert "<" not in data and ">" not in data
    loaded = json.loads(data)
    assert loaded["replays"][0]["why"] == evil
    assert loaded["replays"][0]["steps"][0]["candidates"][0]["name"] == evil


@pytest.mark.parametrize("name", ["../x.png", "/etc/x.png", "http://evil/x.png", "javascript:x",
                                  "a/../../x.png", "a\\b.png", "", None, 3, "x.png?a", "x.png#b"])
def test_unsafe_screenshot_paths_are_dropped(name):
    assert viewer.safe_rel(PurePosixPath("replays/visitor-001"), name) is None


def test_safe_screenshot_paths_are_relative_to_dir_and_quoted():
    base = PurePosixPath("replays/visitor-001")
    assert viewer.safe_rel(base, "step-01.png") == "replays/visitor-001/step-01.png"
    assert viewer.safe_rel(base, "a b.png") == "replays/visitor-001/a%20b.png"


def test_out_of_range_indices_and_unknown_fields_are_ignored():
    rep = replay(ROWS[1])
    rep["steps"][0]["clicked"] = 99
    rep["steps"][0]["missed"] = True
    rep["extra"] = {"x": 1}
    rows = [dict(r, future=1) for r in ROWS]
    data = viewer.player_data([(PurePosixPath("replays/visitor-001"), rep)], {}, {}, str)
    assert data[0]["steps"][0]["clicked"] is None and data[0]["steps"][0]["missed"] is None
    viewer.render(RUN, rows, [(PurePosixPath("replays/visitor-001"), rep)], provisional())


# -- percentiles ---------------------------------------------------------------

PCT = re.compile(r"\d+% percentile of human task effort[^\"<]*")


@pytest.mark.parametrize("run_measured,ruler,tagged", [
    (None, provisional(), True),
    (False, provisional(), True),
    (True, provisional(), True),
    (False, measured_ruler(), True),
    (True, measured_ruler(), False),
])
def test_percentiles_carry_the_provisional_tag_unless_both_rulers_are_measured(run_measured, ruler, tagged):
    run = None if run_measured is None else dict(RUN, ruler={"measured": run_measured})
    reps = [(PurePosixPath(f"replays/visitor-00{v}"), replay(ROWS[v])) for v in (1, 3)]
    page = viewer.render(run, ROWS, reps, ruler)
    found = PCT.findall(page)
    assert len(found) >= 3
    assert all(("ruler: PROVISIONAL" in p) == tagged for p in found)
    assert "/100" not in page


# -- player data ---------------------------------------------------------------

def test_player_frames_match_replays_and_filter_on_their_pages(tmp_path):
    make_dir(tmp_path)
    run, rows, reps = viewer.load(tmp_path)
    fl = viewer.flow(rows)
    ids = {u: i for i, u in enumerate(viewer.layout(fl))}
    data = viewer.player_data(reps, ids, {}, str)
    assert [d["visitor"] for d in data] == [1, 3]
    for d, (_, rep) in zip(data, reps):
        assert len(d["steps"]) == len(rep["steps"])
        assert set(d["nodes"]) == {ids[s["url"]] for s in rep["steps"]} | {ids[rep["end"]["url"]]}
        for s in d["steps"]:
            assert s["shot"].startswith(f"replays/visitor-{d['visitor']:03d}/")
            assert (tmp_path / s["shot"]).is_file()
            assert 0 <= s["clicked"] < len(s["candidates"])


def test_build_writes_a_self_contained_page(tmp_path):
    make_dir(tmp_path)
    out = viewer.build(tmp_path)
    assert out == tmp_path / "index.html" and out.is_file()
    page = out.read_text()
    assert not re.search(r'<script[^>]+src=|<link[^>]+href=|fetch\(|XMLHttpRequest|data:image', page)
    assert "find the restock alerts" in page and "2/5" in page


def test_build_works_without_run_json_or_replays(tmp_path):
    make_dir(tmp_path, run=None, replay_of=())
    page = viewer.build(tmp_path).read_text()
    assert "No run.json" in page


def test_main_rejects_a_directory_without_traces(tmp_path):
    assert viewer.main([str(tmp_path)]) == 2


# -- the page actually runs ----------------------------------------------------

@pytest.mark.browser
def test_player_runs_and_steps_in_a_real_browser(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    make_dir(tmp_path)
    url = viewer.build(tmp_path).as_uri()
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda ex: errors.append(str(ex)))
            pg.goto(url)
            assert pg.locator(".vbtn").count() == 2
            assert pg.locator(".mark.missed").count() == 1
            before = pg.text_content("#pos")
            pg.keyboard.press("ArrowRight")
            assert pg.text_content("#pos") != before
            pg.locator(".vbtn").nth(1).click()
            pg.locator("#timeline li.end .step").click()
            pg.wait_for_selector(".mark.target")
            pg.locator(".node.target").click()
            assert pg.locator(".vbtn").count() == 1
            assert not errors
        finally:
            b.close()


# -- follow-ups: wording, p_ungated, end.page, why, hrefs, long pages ---------

def test_no_label_claims_a_link_was_not_noticed():
    reps = [(PurePosixPath("replays/visitor-001"), replay(ROWS[1]))]
    page = viewer.render(RUN, ROWS, reps, provisional())
    assert "not noticed" not in page.lower()
    assert "below the noticeability threshold" in page


def test_a_label_covering_several_hrefs_says_so_without_splitting():
    rows = [row(0, False, [f"{O}/", f"{O}/x"], f"{O}/x", missed=(0, 1))]
    rows[0]["steps"][1]["missed"]["href"] = "/other"
    groups = viewer.stuck(rows)
    assert len(groups) == 1 and groups[0]["hrefs"] == 2
    assert "2 different links" in viewer.render(RUN, rows, [], provisional())
    assert "different links" not in viewer.render(RUN, ROWS, [], provisional())


def test_why_uses_the_map_labels():
    rep = replay(ROWS[1], why=f"2/5 visitors stopped at {O}/b")
    data = viewer.player_data([(PurePosixPath("replays/visitor-001"), rep)], {}, {f"{O}/b": "/b"}, str)
    assert data[0]["why"] == "2/5 visitors stopped at /b"


def test_p_ungated_and_end_page_pass_through_only_when_present():
    rep = replay(ROWS[3])
    base = PurePosixPath("replays/visitor-003")
    plain = viewer.player_data([(base, rep)], {}, {}, str)[0]
    assert all(c["p_ungated"] is None for s in plain["steps"] for c in s["candidates"])
    assert plain["end"]["w"] is None
    rep["steps"][0]["candidates"][2]["p_ungated"] = 0.3
    rep["end"]["page"] = {"width": 400, "height": 1600}
    rich = viewer.player_data([(base, rep)], {}, {}, str)[0]
    assert rich["steps"][0]["candidates"][2]["p_ungated"] == 0.3
    assert (rich["end"]["w"], rich["end"]["h"]) == (400, 1600)


@pytest.mark.browser
def test_long_page_shows_the_fold_and_scrolls_to_the_click(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    make_dir(tmp_path, replay_of=())
    d = tmp_path / "replays" / "visitor-001"
    d.mkdir(parents=True)
    rep = replay(ROWS[1])
    for s in rep["steps"]:
        s["page"] = {"width": 400, "height": 2400}
        s["candidates"][0]["box"] = [10, 2000, 80, 20]          # the click is far below the fold
        s["candidates"][2]["p_ungated"] = 0.5
        (d / s["screenshot"]).write_bytes(png(400, 2400))
    (d / "end.png").write_bytes(png(400, 2400))
    (d / "replay.json").write_text(json.dumps(rep))
    url = viewer.build(tmp_path).as_uri()
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            pg.on("pageerror", lambda ex: errors.append(str(ex)))
            pg.goto(url)
            fold = pg.locator(".fold")
            assert fold.count() == 1
            top = float(fold.evaluate("n => parseFloat(n.style.top)"))
            assert top == pytest.approx(100 * RUN["viewport"]["height"] / 2400)
            pg.wait_for_function("document.getElementById('stage').scrollTop > 0")
            assert "cut its click chance" in pg.text_content("#detail")
            assert pg.locator("th", has_text="p gate off").count() == 1
            assert not errors
        finally:
            b.close()
