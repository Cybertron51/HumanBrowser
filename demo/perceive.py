import asyncio, json, sys
from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://attentioninsight.com/"

# This is the core of every browser agent's "perception" step.
COLLECT = r"""
() => {
  const SEL = 'a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[onclick],[tabindex]:not([tabindex="-1"])';
  const vw = innerWidth, vh = innerHeight;
  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;                    // zero-size
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
    if (r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;  // offscreen
    // hit-test: is this element actually the thing on top at its own center?
    const cx = Math.min(Math.max(r.left + r.width/2, 1), vw-1);
    const cy = Math.min(Math.max(r.top + r.height/2, 1), vh-1);
    const top = document.elementFromPoint(cx, cy);
    if (!top || !(el.contains(top) || top.contains(el))) continue;  // occluded by overlay
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || (el.tagName === 'A' ? 'link' : el.tagName === 'BUTTON' ? 'button' : el.tagName.toLowerCase()),
      name: (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('placeholder') || el.getAttribute('title') || '').trim().replace(/\s+/g,' ').slice(0,60),
      href: el.getAttribute('href') || null,
      box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    });
  }
  return out;
}
"""

PAINT = r"""
(els) => {
  const lay = document.createElement('div');
  lay.id = '__som__';
  lay.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none';
  const hues = [0,28,54,140,200,265,320];
  els.forEach((e,i) => {
    const h = hues[i % hues.length];
    const b = document.createElement('div');
    b.style.cssText = `position:absolute;left:${e.box[0]}px;top:${e.box[1]}px;width:${e.box[2]}px;height:${e.box[3]}px;border:2px solid hsl(${h} 85% 45%);background:hsl(${h} 85% 45% / .07)`;
    const t = document.createElement('div');
    t.textContent = i;
    t.style.cssText = `position:absolute;left:${e.box[0]}px;top:${Math.max(0,e.box[1]-15)}px;background:hsl(${h} 85% 42%);color:#fff;font:600 11px/15px ui-monospace,monospace;padding:0 4px;border-radius:2px`;
    lay.append(b,t);
  });
  document.body.append(lay);
}
"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await (await b.new_context(viewport={'width':1440,'height':900})).new_page()
        await pg.goto(URL, wait_until='domcontentloaded', timeout=45000)
        await pg.wait_for_timeout(3500)

        els = await pg.evaluate(COLLECT)
        open('elements.json','w').write(json.dumps(els, indent=1))

        # 1. indexed action space — what browser-use hands the model
        with open('elements.txt','w') as f:
            for i,e in enumerate(els):
                f.write(f"[{i}] <{e['role']}> {e['name']!r}"
                        + (f" href={e['href']}" if e['href'] else "")
                        + f"  @({e['box'][0]},{e['box'][1]}) {e['box'][2]}x{e['box'][3]}\n")

        # 2. accessibility tree — what Playwright MCP / Stagehand hand the model
        ax = await pg.accessibility.snapshot()
        def flat(n, d=0, out=None):
            out = [] if out is None else out
            nm = (n.get('name') or '').strip().replace('\n',' ')[:70]
            if n.get('role') not in ('none','generic','') :
                out.append('  '*d + f"{n['role']}" + (f' "{nm}"' if nm else ''))
                d += 1
            for c in n.get('children') or []: flat(c, d, out)
            return out
        open('a11y.txt','w').write('\n'.join(flat(ax)))

        await pg.evaluate(PAINT, els)
        await pg.screenshot(path='som.png')
        await b.close()
        print(f"elements={len(els)}  a11y_lines={len(open('a11y.txt').read().splitlines())}")

asyncio.run(main())
