#!/usr/bin/env python3
"""Recon tool for the Network design (Design tab) coverage inventory (docs/netlab-ui-qa/).

Not a pass/fail check like docs/netlab-integration/tools/check_design_ui.py: this walks the tab
through every reachable state without a VM (empty, unsaved edit, invalid, saved, plan generated with
the real engine, advanced editor open, files list open, history open, export/import dialogs,
renumber/clear dialogs opened then cancelled, the Apply to devices dialog as far as it goes without a
VM, and a narrow viewport) and dumps every interactive element inside #design-view (and #lab-tabs) in
each state to JSON, for docs/netlab-ui-qa/coverage.json to be built from.

Run against an already-running fixture manager (see docs/redesign/tools/fixture_manager.py); this
script never starts one itself and never touches port 8081, /srv/containerlab-node-manager or ~/labs.

Two modes:
  --mode full (default): the whole guided/plan/history/renumber/clear tour on `ospf-basics`
    (linked, Not deployed, no git binding) -- every state that does not need a Running, git-bound lab.
  --mode apply_export: a short tour on a Running, git-bound lab (`BGP_TheoryToPractice` in this
    fixture) to reach the states `--mode full` cannot: the Export plan to Git dialog (needs a git
    binding) and the Apply to devices dialog past its choose step (needs deployment.status Running).
    Review still runs against no real devices, so every target comes back unreachable -- that failure
    state is itself part of the inventory.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/tools/inventory_dom.py --base http://127.0.0.1:8097 --out docs/netlab-ui-qa/dom_states.json
    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/tools/inventory_dom.py --base http://127.0.0.1:8097 --mode apply_export \\
        --lab BGP_TheoryToPractice --out docs/netlab-ui-qa/dom_states_apply_export.json
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

LAB = 'ospf-basics'

DUMP_JS = """
(rootSel) => {
  const root = document.querySelector(rootSel);
  if (!root) return {present: false};
  const interactive = 'button, input, select, textarea, a[href], [role="button"], [role="menuitem"], [role="tab"], summary, details, dialog, [data-design-view-file], [data-design-vrf-remove], [data-design-vlan-remove], [data-design-static-remove], [data-design-apply-takeover], [data-design-apply-show]';
  // Non-interactive state/status/error text the source enumeration also cares about (badges, pills,
  // warning banners, status lines): these are read-only, but their textContent per state IS the thing
  // designStateOf/designApplyDisabledReason/etc. render, so the DOM inventory must carry it too.
  const text = 'p[role="status"], p[role="alert"], ul[role="alert"], .banner, .pill, .caption, .form-help, .form-error,'+
   ' #design-state, #design-state-pill, #design-state-text, #design-detail, #design-engine, #design-engine-text,'+
   ' #design-plan-status, #design-problems, #design-compatibility, #design-plan-errors, #design-plan-warnings,'+
   ' #design-plan-renumbering, #design-plan-collisions, #design-ledger, #design-ownership,'+
   ' #design-apply-choose-error, #design-apply-review-error, #design-export-git-error, #design-history-body,'+
   ' #design-files-body, #design-apply-last, #design-apply-progress-body, #design-apply-review-body,'+
   ' #design-apply-choose-body, #design-export-git-destination';
  const nodes = [...new Set([...root.querySelectorAll(interactive), ...root.querySelectorAll(text)])];
  const describe = (el) => {
    const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : {width:0,height:0};
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      name: el.getAttribute('name'),
      type: el.getAttribute('type'),
      role: el.getAttribute('role'),
      text: (el.innerText || el.value || el.textContent || '').trim().slice(0, 80),
      disabled: !!el.disabled,
      hidden: el.hidden || el.closest('[hidden]') !== null,
      open: el.tagName === 'DETAILS' || el.tagName === 'DIALOG' ? !!el.open : null,
      checked: 'checked' in el ? el.checked : null,
      value: (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') ? String(el.value).slice(0, 60) : null,
      dataset: Object.assign({}, el.dataset),
      ariaLabel: el.getAttribute('aria-label'),
      ariaHaspopup: el.getAttribute('aria-haspopup'),
      ariaExpanded: el.getAttribute('aria-expanded'),
      ariaSelected: el.getAttribute('aria-selected'),
      title: el.getAttribute('title'),
      placeholder: el.getAttribute('placeholder'),
      visibleArea: Math.round(rect.width) + 'x' + Math.round(rect.height)
    };
  };
  return {present: true, count: nodes.length, elements: nodes.map(describe)};
}
"""


def open_design(page, timeout=15000):
    """Advanced > Experimental > Network design: the Design tab is gone, so click #tab-advanced, open
    #experimental-design (closed by default) and wait for the #design-view region to be visible."""
    page.click('#tab-advanced')
    if not page.evaluate("() => document.getElementById('experimental-design').open"):
        page.click('#experimental-design > summary')
    page.wait_for_selector('#design-view', state='visible', timeout=timeout)


def wait_http(url, seconds=30):
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read())
        except Exception:
            time.sleep(0.5)
    raise SystemExit('manager did not answer at ' + url)


def run_full(page, dump, lab, errors):
    """The whole guided/plan/history/renumber/clear tour on a lab with no git binding and no deployment."""
    # --- Navigation: no Tools shortcut any more; Advanced > Experimental > Network design ---------------
    page.goto(BASE_URL[0] + '/#lab=' + lab['id'] + '&view=tools')
    page.wait_for_selector('#tools-view:not([hidden])', timeout=15000)
    dump('nav_tools_tab', '#tools-view')
    dump('nav_lab_tabs', '#lab-tabs')
    dump('nav_tools_has_no_design_card', '#tools-view')
    open_design(page)
    page.wait_for_selector('#design-view:not([hidden])', timeout=15000)
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)
    dump('nav_after_tools_shortcut')

    # --- Old deep link (#view=design lands on Advanced with Experimental open) --------------------------------------------------
    page.goto(BASE_URL[0] + '/#lab=' + lab['id'] + '&view=design')
    page.wait_for_selector('#design-view:not([hidden])', timeout=15000)
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)
    dump('nav_deep_link')
    dump('lab_tabs_on_design', '#lab-tabs')

    # --- Empty (no design) ----------------------------------------------------------------------------
    dump('empty')
    page.click('#design-more-button')
    dump('empty_more_menu_open', '#design-more-menu')
    page.keyboard.press('Escape')

    # --- Unsaved edit (dirty) -------------------------------------------------------------------------
    box = page.locator('input[name="design-module"][value="ospf"]')
    if not box.is_checked():
        box.check()
    page.locator('input[name="design-module"][value="ospf"]').dispatch_event('change')
    dump('unsaved_dirty')

    # --- Invalid: a pool inside the management network -------------------------------------------------
    page.fill('#design-pool-lan-ipv4', '172.20.20.0/24')
    page.locator('#design-pool-lan-ipv4').dispatch_event('change')
    page.click('#design-save')
    page.wait_for_function('() => (document.getElementById("design-problems")?.textContent || "").length > 0', timeout=10000)
    dump('invalid_problems')

    # --- Fix and save (clean/saved) ---------------------------------------------------------------------
    page.fill('#design-pool-lan-ipv4', '172.16.0.0/16')
    page.locator('#design-pool-lan-ipv4').dispatch_event('change')
    box = page.locator('input[name="design-module"][value="bgp"]')
    if not box.is_checked():
        box.check()
    page.locator('input[name="design-module"][value="bgp"]').dispatch_event('change')
    page.wait_for_selector('#design-bgp-settings:not([hidden])', timeout=5000)
    page.fill('#design-bgp-as', '65010')
    page.locator('#design-bgp-as').dispatch_event('change')
    page.click('#design-save')
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Unsaved")', timeout=10000)
    dump('saved_clean')

    # --- Advanced editor open (details) ------------------------------------------------------------------
    page.click('#design-advanced-details summary')
    page.wait_for_timeout(300)
    dump('advanced_open')

    # --- Generate plan (queued/generating/succeeded) ------------------------------------------------------
    page.click('#design-generate')
    try:
        page.wait_for_function('(w) => (document.getElementById("design-state")?.textContent || "").includes(w)', arg='Generating', timeout=8000)
        dump('generating')
    except Exception as exc:
        errors.append('generating state not observed: ' + str(exc))
    page.wait_for_function('(w) => (document.getElementById("design-state")?.textContent || "").includes(w)', arg='Plan ready', timeout=120000)
    dump('plan_succeeded')

    # --- Files list open (View a generated file) ------------------------------------------------------------
    view_button = page.locator('#design-files button', has_text='View').first
    if view_button.count():
        view_button.click()
        page.wait_for_selector('dialog[open] pre', timeout=10000)
        dump('files_view_dialog', 'dialog[open]')
        page.keyboard.press('Escape')

    # --- History open ------------------------------------------------------------------------------------------
    page.click('#design-history summary')
    page.wait_for_timeout(200)
    dump('history_open')

    # --- Owned settings (Advanced -> Owned settings loads on <details> toggle) ---------------------------------
    page.wait_for_timeout(500)
    dump('advanced_ownership_loaded')

    # --- Export design file (More menu; capture just the menu item states, download itself is not driven) ------
    page.click('#design-more-button')
    dump('more_menu_with_plan', '#design-more-menu')
    page.keyboard.press('Escape')

    # --- Import dialog (native file picker cannot be scripted headlessly; capture the trigger state only) -------
    # design-import-file is a hidden <input type=file>; clicking #design-import opens the OS picker, which
    # Playwright cannot drive without set_input_files on a known path. We record the control's state only.
    dump('import_control_state')

    # --- Renumber dialog: open then cancel -----------------------------------------------------------------------
    page.click('#design-more-button')
    page.click('#design-renumber')
    page.wait_for_selector('#design-renumber-dialog[open]', timeout=5000)
    dump('renumber_dialog_open', '#design-renumber-dialog')
    page.click('#design-renumber-dialog [data-op-close]')
    page.wait_for_timeout(200)
    dump('renumber_dialog_closed', '#design-renumber-dialog')

    # --- Clear dialog: open then cancel --------------------------------------------------------------------------
    page.click('#design-more-button')
    page.click('#design-clear')
    page.wait_for_selector('#design-clear-dialog[open]', timeout=5000)
    dump('clear_dialog_open', '#design-clear-dialog')
    page.click('#design-clear-dialog [data-op-close]')
    page.wait_for_timeout(200)
    dump('clear_dialog_closed', '#design-clear-dialog')

    # --- Export plan to Git dialog: this lab has no git binding, so the button stays disabled. -------------------
    reason = page.get_attribute('#design-export-git', 'title')
    if not (page.locator('#design-export-git').get_attribute('disabled') is not None):
        page.click('#design-export-git')
        page.wait_for_selector('#design-export-git-dialog[open]', timeout=5000)
        dump('export_git_dialog_open', '#design-export-git-dialog')
        page.click('#design-export-git-dialog [data-design-export-git-close]')
        page.wait_for_timeout(200)
    else:
        dump('export_git_button_disabled')
        errors.append('export_git_dialog_open not reached on %s: button disabled (%s) -- see --mode apply_export' % (lab['name'], reason))

    # --- Apply to devices dialog: this lab is Not deployed, so the button stays disabled. ------------------------
    apply_reason = page.get_attribute('#design-apply', 'title')
    apply_disabled = page.locator('#design-apply').get_attribute('disabled') is not None
    if not apply_disabled:
        page.click('#design-apply')
        page.wait_for_selector('#design-apply-dialog[open]', timeout=5000)
        dump('apply_dialog_choose_step', '#design-apply-dialog')
        page.click('[data-design-apply-close]')
        page.wait_for_timeout(200)
    else:
        dump('apply_button_disabled')
        errors.append('apply_dialog_choose_step not reached on %s: button disabled (%s) -- see --mode apply_export' % (lab['name'], apply_reason))

    # --- Cancel a generation: re-generate then click Cancel quickly (best-effort; may finish before we click) ----
    page.click('#design-generate')
    try:
        page.wait_for_selector('#design-cancel:not([hidden])', timeout=4000)
        page.click('#design-cancel')
        dump('cancel_clicked')
    except Exception as exc:
        errors.append('cancel button not reachable before the fast fixture engine finished: ' + str(exc))
    page.wait_for_function('(w) => !(document.getElementById("design-state")?.textContent || "").includes(w)', arg='Generating', timeout=120000)
    dump('post_cancel_attempt')

    # --- Narrow viewport (390x844) ------------------------------------------------------------------------------
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_timeout(300)
    dump('narrow_viewport')
    dump('narrow_viewport_lab_tabs', '#lab-tabs')


def run_apply_export(page, dump, lab, errors):
    """A short tour on a Running, git-bound lab to reach the Apply and Export-to-Git dialogs past their
    disabled button state. Devices are the fixture's scripted answers, not real SSH targets, so the
    review step is expected to report every target unreachable -- that is itself a state to record."""
    page.goto(BASE_URL[0] + '/#lab=' + lab['id'] + '&view=design')
    page.wait_for_selector('#design-view:not([hidden])', timeout=15000)
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)
    dump('ae_empty')

    box = page.locator('input[name="design-module"][value="ospf"]')
    if not box.is_checked():
        box.check()
    page.locator('input[name="design-module"][value="ospf"]').dispatch_event('change')
    page.click('#design-save')
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Unsaved")', timeout=10000)
    dump('ae_saved')

    page.click('#design-generate')
    page.wait_for_function('(w) => (document.getElementById("design-state")?.textContent || "").includes(w)', arg='Plan ready', timeout=180000)
    dump('ae_plan_succeeded')

    # --- Export plan to Git dialog (this lab has a git binding) ---------------------------------------------------
    reason = page.get_attribute('#design-export-git', 'title')
    if not (page.locator('#design-export-git').get_attribute('disabled') is not None):
        page.click('#design-export-git')
        page.wait_for_selector('#design-export-git-dialog[open]', timeout=5000)
        dump('export_git_dialog_open', '#design-export-git-dialog')
        # Fill the checkpoint field to exercise the destination-line update, then cancel without submitting.
        page.fill('#design-export-git-checkpoint', 'inventory-probe')
        page.locator('#design-export-git-checkpoint').dispatch_event('input')
        page.wait_for_timeout(200)
        dump('export_git_dialog_filled', '#design-export-git-dialog')
        page.click('#design-export-git-dialog [data-design-export-git-close]')
        page.wait_for_timeout(200)
    else:
        dump('export_git_button_disabled')
        errors.append('export_git_dialog_open not reached: button still disabled (%s)' % reason)

    # --- Apply to devices dialog (this lab is Running) -------------------------------------------------------------
    apply_reason = page.get_attribute('#design-apply', 'title')
    apply_disabled = page.locator('#design-apply').get_attribute('disabled') is not None
    if not apply_disabled:
        page.click('#design-apply')
        page.wait_for_selector('#design-apply-dialog[open]', timeout=5000)
        dump('apply_dialog_choose_step', '#design-apply-dialog')
        # Limit the review to a couple of devices: this fixture lab has 13 designable devices and each
        # review connection is a real (failing) SSH attempt, so reviewing all of them serially is slow.
        boxes = page.locator('#design-apply-choose-body input[name="design-apply-target"]')
        for i in range(boxes.count()):
            if i >= 2 and boxes.nth(i).is_checked():
                boxes.nth(i).uncheck()
        dump('apply_dialog_choose_step_narrowed', '#design-apply-dialog')
        page.click('#design-apply-review-run')
        try:
            page.wait_for_function('() => document.getElementById("design-apply-review-step") && !document.getElementById("design-apply-review-step").hidden', timeout=60000)
            dump('apply_dialog_review_step', '#design-apply-dialog')
        except Exception as exc:
            errors.append('apply review step not observed: ' + str(exc))
            dump('apply_dialog_review_step_timeout', '#design-apply-dialog')
        page.click('[data-design-apply-close]')
        page.wait_for_timeout(200)
    else:
        dump('apply_button_disabled')
        errors.append('apply_dialog_choose_step not reached: button still disabled (%s)' % apply_reason)


BASE_URL = ['']  # set in main(); read by run_full/run_apply_export via closure-free module state


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', default='http://127.0.0.1:8097')
    parser.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'dom_states.json'))
    parser.add_argument('--shots', default='')
    parser.add_argument('--lab', default='', help='lab name to open (default: ospf-basics for full, BGP_TheoryToPractice for apply_export)')
    parser.add_argument('--mode', default='full', choices=('full', 'apply_export'),
                         help="'full' walks the whole guided/plan/history/renumber/clear tour (ospf-basics); "
                              "'apply_export' is a shorter tour on a Running, git-bound lab (e.g. BGP_TheoryToPractice) "
                              "to reach the Apply to devices and Export plan to Git dialogs, which need deployment.status "
                              "Running and a git binding respectively")
    args = parser.parse_args()
    BASE_URL[0] = args.base
    lab_name = args.lab or (LAB if args.mode == 'full' else 'BGP_TheoryToPractice')

    state = wait_http(args.base + '/api/state')
    lab = next(l for l in state['labs'] if l['name'] == lab_name)
    states = {}
    errors = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        chromium_version = browser.version
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda e: errors.append(str(e)))

        def dump(name, sel='#design-view'):
            data = page.evaluate(DUMP_JS, sel)
            states[name] = data
            print('captured %-28s present=%s count=%s' % (name, data.get('present'), data.get('count')), flush=True)
            if args.shots:
                Path(args.shots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(args.shots) / (name + '.png')), full_page=True)

        if args.mode == 'full':
            run_full(page, dump, lab, errors)
        else:
            run_apply_export(page, dump, lab, errors)

        browser.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({'chromium_version': chromium_version, 'lab_id': lab['id'], 'lab_name': lab_name,
                                          'mode': args.mode, 'states': states, 'errors': errors}, indent=2))
    print('wrote', args.out)
    print('chromium', chromium_version)
    if errors:
        print('errors:', errors)


if __name__ == '__main__':
    sys.exit(main())
