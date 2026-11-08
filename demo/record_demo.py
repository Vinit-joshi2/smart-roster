"""Records a captioned ~4 min walkthrough of the running app.
Usage:  python app.py &   then   python demo/record_demo.py [http://localhost:8080]
Output: demo/raw/*.webm  (convert with: ffmpeg -i raw/x.webm -c:v libx264 -pix_fmt yuv420p smart-roster-demo.mp4)
Captions/cursor are injected by the recorder only; the app itself ships no JavaScript."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
INIT = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;width:18px;height:18px;border-radius:50%;background:rgba(255,80,60,.75);border:2px solid #fff;z-index:99999;pointer-events:none;transform:translate(-50%,-50%);left:-50px;top:-50px';
  const cap = document.createElement('div'); cap.id = 'cap';
  cap.style.cssText = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:rgba(20,26,50,.93);color:#fff;padding:12px 22px;border-radius:12px;font:600 17px system-ui;z-index:99998;max-width:80vw;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.35)';
  cap.textContent = sessionStorage.getItem('cap') || '';
  document.body.append(c, cap);
  const p = JSON.parse(sessionStorage.getItem('mouse') || 'null'); if (p) { c.style.left = p[0] + 'px'; c.style.top = p[1] + 'px'; }
  document.addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; sessionStorage.setItem('mouse', JSON.stringify([e.clientX, e.clientY])); });
});
"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(Path(__file__).parent / "raw"), record_video_size={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.add_init_script(INIT)

    def caption(t):
        pg.evaluate("t => { sessionStorage.setItem('cap', t); const c = document.getElementById('cap'); if (c) c.textContent = t; }", t)

    def wait(s):
        pg.wait_for_timeout(int(s * 1000))

    def go(sel, click=True):
        el = pg.locator(sel).first
        el.scroll_into_view_if_needed()
        b = el.bounding_box()
        pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=25)
        wait(0.5)
        if click:
            el.click()

    pg.goto(BASE + "/roster")
    pg.wait_for_selector(".grid")
    caption("Smart Roster – generates, validates and edits a monthly duty roster for 36 people across 25 brands (Python + Flask, HTML/CSS)"); wait(7)
    caption("One click generated November 2026: 100% mandatory coverage. Soft-rule warnings and cross-cover shifts are shown separately"); wait(7)
    caption("Company view: rows = employees by pod, columns = days. WO weekly off · L leave · CO comp-off · H public holiday · “+” = covering another process"); wait(9)
    go(".seg a:text-is('Pod')"); caption("Pod view – one pod, its coverage and its issues"); wait(6)
    go(".seg a:text-is('Brand')"); caption("Brand view – Kaya Naturals: ONE person owns this brand, so the rows below show staffed / required for each process"); wait(7)
    caption("Black Friday (27–28 Nov) needs 2 people on Customer Support – the single owner can’t do that alone, so the engine cross-covers (2/2)"); wait(8)
    pg.select_option("select[name=id]", label="Swift Electronics"); go("button:text-is('Show')")
    caption("Multi-employee brand – Swift Electronics: 3 people, CS needs 2 every Mon–Sat, so weekly offs are staggered"); wait(9)
    go(".seg a:text-is('Process')"); caption("Process view – every brand/process has its own operating calendar, minimum staff and special days"); wait(6)
    go(".seg a:text-is('Employee')"); pg.select_option("select[name=id]", label="Ishaan Gupta"); go("button:text-is('Show')")
    caption("Employee view – a pod floater: working days, weekly offs, holiday work (comp-off earned), and which brands each day is served"); wait(9)

    go("a.tab:has-text('Issues')"); caption("Issues tab – mandatory coverage rules (red) are separate from soft preferences (amber). Each issue explains cause and impact"); wait(7)
    pg.check("input[value=info]"); go("button:text-is('Apply filters')")
    caption("Include info: missed preferred off days and every cross-cover shift are listed transparently"); wait(6)

    go("a.tab:has-text('Handle a change')"); caption("Handling a change: a sole brand owner calls in sick after the roster is published"); wait(5)
    go("button:has-text('Demo: solo brand owner')"); pg.wait_for_selector(".issue")
    caption("Instantly: coverage gap, cause = “Leave clash”. The pod’s lead and floater are also on leave that day, so no designated backup is free"); wait(9)
    caption("The app ranks who can cover and why – same pod, current brand load – instead of just failing"); wait(8)
    go("form[action='/fix'] button >> nth=0"); caption("One click applies the cover and re-validates – every blocking issue from this change is resolved"); wait(7)

    go("a.tab:has-text('Roster')"); go(".seg a:text-is('Company')")
    caption("Manual editing with live validation: click any cell …"); wait(4)
    day = pg.evaluate("() => { const r = document.querySelector('td.cell[id^=\"c-E06-\"]'); return null }")
    cell = None
    for d in ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]:
        loc = pg.locator(f"td#c-E06-{d}")
        if loc.get_attribute("class") and "st-W" in loc.get_attribute("class"):
            cell = f"td#c-E06-{d} a"; break
    go(cell)
    caption("… and choose a status. The validator runs on the server immediately"); wait(4)
    go(".menu button:has(i.st-L)"); wait(1)
    caption("The toast and KPIs show the impact of the edit (red outline = people involved in a coverage problem)"); wait(8)
    go("button:has-text('Auto-repair')"); caption("Auto-repair applies the best suggested fix to every repairable gap"); wait(7)

    go("a.tab:has-text('Setup')"); caption("Master data: employees, pods, brands, processes & rules, assignments and holidays are all editable from the UI – no code changes"); wait(7)
    go(".seg a:has-text('Processes')"); caption("Per process: operating calendar (365 / all except holidays / Mon–Sat), minimum staff, special-day minimums, weekly-off pattern"); wait(9)
    go(".seg a:has-text('Employees')"); go("a.btn:has-text('Add employee')"); pg.fill("input[name=name]", "Demo Employee"); caption("Adding a new employee…"); wait(4)
    go(".modal button[type=submit]"); wait(2)
    caption("The roster is re-validated at once and flags what changed; Generate rebuilds with the new data"); wait(6)
    go("button:has-text('Generate roster')"); wait(4)

    go("a.tab:has-text('Rules')"); caption("Rules & assumptions are documented in-app and in the README: mandatory vs soft, calendars, weekly-rest definition"); wait(8)
    caption("Thank you – code, tests (19 passing), README with the 8 answers and approach note are in the repo"); wait(6)
    ctx.close(); browser.close()
