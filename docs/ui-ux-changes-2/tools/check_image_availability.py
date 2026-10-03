#!/usr/bin/env python3
"""Item 2: the lab builder knows whether an image is usable on this VM and says so before the student commits.
Driven in a real browser against a running manager (the deployed one or the fixture): the builder's image line
under the bar after a device is placed (on the VM) and after its template is changed to an image found nowhere
(amber, "a deploy fails"); the Image field's list offers the VM's images; the Save to the VM… review lists the
images with the VM's answers and calls out the one found nowhere; a Start lab review of an existing lab shows the
same section. Nothing is saved or deployed: every review is cancelled. Zero console or page errors.

    CLAB_BASE=http://192.168.132.132:8081 CLAB_LAB=netlab-test CLAB_MISSING=vrnetlab/cisco_xrv9k:24.3.1 \\
      CLAB_SHOTS=/tmp/shots clab-backup-ui/.venv/bin/python docs/ui-ux-changes-2/tools/check_image_availability.py
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://192.168.132.132:8081')
LAB = os.environ.get('CLAB_LAB', 'netlab-test')          # an existing lab, not running: its Start lab review is opened and cancelled
MISSING = os.environ.get('CLAB_MISSING', 'vrnetlab/cisco_xrv9k:24.3.1')   # an image that is neither on the VM nor in a registry
OUT = os.environ.get('CLAB_SHOTS', '')
NAME = 'uiux2-img2-' + time.strftime('%H%M%S')
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    page.on('console', lambda m: errors.append(m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    shot = lambda name: page.screenshot(path=os.path.join(OUT, name + '.png')) if OUT else None
    api = lambda path: json.loads(page.request.get(BASE + '/api' + path).text())
    vm_images = api('/operations/images')
    check('the manager lists the VM images (read-only helper mode)', vm_images.get('available') is True and len(vm_images.get('images', [])) > 0, vm_images)
    local = vm_images['images'][0]
    answer = json.loads(page.request.post(BASE + '/api/operations/image-check', data=json.dumps({'references': [local, MISSING]}), headers={'Content-Type': 'application/json'}).text())
    by = {i['reference']: i for i in answer.get('images', [])}
    check('image-check: a VM image is local, the missing one is found nowhere', by.get(local, {}).get('local') is True and by.get(MISSING, {}).get('local') is False and by.get(MISSING, {}).get('registry') == 'not-found', answer)
    bad = page.request.post(BASE + '/api/operations/image-check', data=json.dumps({'references': ['-rm']}), headers={'Content-Type': 'application/json'})
    check('image-check answers a name that is no reference as invalid, never sending it', bad.status == 200 and json.loads(bad.text()).get('images', [{}])[0].get('registry') == 'invalid', bad.status)

    page.goto(BASE + '/static/lab-builder.html'); page.wait_for_selector('#builder-welcome-new', timeout=20000); page.click('#builder-welcome-new')
    page.wait_for_selector('#builder-new-name', timeout=20000); page.fill('#builder-new-name', NAME); page.click('#builder-new-create')
    page.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000); page.wait_for_timeout(1200)
    line = page.locator('#builder-images')
    check('no device, no image line', not line.is_visible())
    template_card = lambda name: page.get_by_text(name, exact=True).first.locator('xpath=ancestor::*[@draggable="true"][1]')
    def drag(name, x, y):
        card = template_card(name); box = card.bounding_box()
        page.mouse.move(box['x'] + 10, box['y'] + 8); page.mouse.down(); page.mouse.move(x, y, steps=12); page.mouse.up(); page.wait_for_timeout(900)
    drag('Linux host', 420, 260)
    page.wait_for_timeout(2500)
    check('a placed device brings the image line, its image on the VM', line.is_visible() and 'on the VM' in line.inner_text() and 'warn' not in (line.get_attribute('class') or ''), line.inner_text() if line.count() else '')
    shot('01-image-line-on-vm')
    # The Image field lists the VM's images.
    template_card('Cisco XRv9k').locator('button[aria-label="Edit"]').click(); page.wait_for_selector('#node-image', timeout=15000); page.wait_for_timeout(400)
    page.click('#node-image'); page.keyboard.press('Control+A'); page.keyboard.type(local.split('/')[-1].split(':')[0][:4]); page.wait_for_timeout(600)
    options = page.locator('[role="listbox"] [role="option"]').all_inner_texts()
    check('the Image field offers the images the VM has', any(local.rsplit(':', 1)[0] == o for o in options), options[:8])
    shot('02-image-list-offers-vm-images')
    page.fill('#node-image', MISSING.rsplit(':', 1)[0]); page.wait_for_timeout(300)
    page.click('#node-version'); page.keyboard.press('Control+A'); page.keyboard.type(MISSING.rsplit(':', 1)[1]); page.wait_for_timeout(400)
    page.get_by_role('button', name='Save', exact=True).click(); page.wait_for_timeout(700)
    drag('Cisco XRv9k', 700, 260)
    page.wait_for_timeout(3500)
    text = line.inner_text() if line.count() else ''
    check('an image found nowhere turns the line amber and says a deploy fails', MISSING in text and 'no registry offers it' in text and 'warn' in (line.get_attribute('class') or ''), text)
    shot('03-image-line-missing')
    # The save review lists the images with the VM's answers; cancelled.
    page.click('#builder-save'); page.wait_for_selector('#operation-review[open]', timeout=30000)
    page.wait_for_function('() => !document.querySelector("#op-review-images-status")', timeout=30000)
    review = page.inner_text('#op-review-images')
    fix = page.locator('#op-review-images-fix')
    check('the save review lists the image the VM cannot supply, with the VM\'s answer, and only images that need attention', 'no registry offers it' in review and 'on the VM.' not in review.replace('not on the VM', ''), review)
    check('the unpullable image is named once (in the list, with its reason) and its fix sentence sits under the list heading', fix.is_visible() and MISSING not in fix.inner_text() and 'Choose an image the VM has, or load it on the VM first' in fix.inner_text() and page.locator('#op-review-images-notice').count() == 0 and page.inner_text('#operation-review').count(MISSING) == 1, fix.inner_text() if fix.count() else 'no fix line')
    check('the review still lets the student decide (Save stays enabled)', page.locator('#op-confirm').is_enabled())
    shot('04-save-review-images')
    page.click('#op-cancel'); page.wait_for_timeout(500)
    # The Start lab review of an existing lab shows the same section; cancelled.
    lab = next((l for l in api('/state')['labs'] if l['name'] == LAB), None)
    if lab:
        page.goto(BASE + '/'); page.wait_for_selector('#lab-cards .lab-card', timeout=30000)
        page.click('[data-lab-more="%s"]' % lab['id']); page.wait_for_selector('#lab-operations-dialog [data-op-action="deploy"]', timeout=20000)
        page.click('#lab-operations-dialog [data-op-action="deploy"]'); page.wait_for_selector('#operation-review[open]', timeout=30000)
        if page.locator('#op-review-images').count():
            page.wait_for_function('() => !document.querySelector("#op-review-images-status")', timeout=30000)
            shown = page.locator('#op-review-images-section').is_visible()
            deploy_review = page.inner_text('#op-review-images') if shown else ''
            check('the Start lab review lists only images that need attention, and no Images section when none does', (not shown) or ('not on the VM' in deploy_review and 'on the VM.' not in deploy_review.replace('not on the VM', '')), deploy_review)
        else:
            check('the Start lab review opened; this topology names no image, so there is no Images section', True)
        shot('05-deploy-review-images')
        page.click('#op-cancel'); page.wait_for_timeout(400)
    else:
        print('skip: lab %s not in My labs, the Start lab review is not checked' % LAB)
    check('no console or page errors', not errors, errors)
    browser.close()
print('FAILED: ' + ', '.join(failed) if failed else 'ALL CHECKS PASSED')
sys.exit(1 if failed else 0)
