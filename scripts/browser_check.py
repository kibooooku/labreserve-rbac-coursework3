"""Reproducible real-UI acceptance using a temporary DB and a local test server.

Run .venv/Scripts/python scripts/browser_check.py. Uses installed Edge, no browser
download. All positive mutations are performed through forms and buttons. Direct
HTTP calls below are explicitly negative security probes in the user's session.
"""
from __future__ import annotations
import json
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app

def run():
    output=ROOT/'evidence/browser'
    output.mkdir(parents=True,exist_ok=True)
    result={'passed':False,'steps':[],'console_errors':[],'unexpected_http_errors':[],
            'screenshots':[],'browser':'Microsoft Edge headless via Playwright',
            'started_at':datetime.now(timezone.utc).isoformat(),
            'data_isolation':'fresh temporary SQLite database; positive changes through UI'}
    server=None
    with tempfile.TemporaryDirectory(prefix='labreserve-ui-') as temp:
        app=create_app({'DATABASE':str(Path(temp)/'ui.sqlite3'),'TESTING':True})
        server=make_server('127.0.0.1',0,app,threaded=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='msedge',headless=True)
                pages={}
                def step(name):result['steps'].append({'name':name,'passed':True})
                def nav(page,key):
                    if page.viewport_size['width']<=700:
                        page.get_by_role('button',name='展开导航',exact=True).click()
                    page.locator(f'#main-nav [data-nav="{key}"]').click()
                    expect(page.locator('#main-content .page-heading')).to_be_visible()
                    expect(page.locator('.loading-state')).to_have_count(0)
                def screenshot(page,name,full=True):
                    page.locator('.toast button').evaluate_all('(els)=>els.forEach(el=>el.click())')
                    path=output/name
                    page.screenshot(path=str(path),full_page=full,animations='disabled')
                    result['screenshots'].append(str(path.relative_to(ROOT)))
                def login(name):
                    ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='Asia/Shanghai')
                    page=ctx.new_page()
                    page.set_default_timeout(15000)
                    page.on('pageerror',lambda e:result['console_errors'].append(str(e)))
                    page.goto(base)
                    expect(page.locator('#login-view')).to_be_visible()
                    page.locator('#username').fill(name)
                    page.locator('#password').fill('Lab@2026!')
                    page.locator('#login-form button[type="submit"]').click()
                    expect(page.locator('#app-view')).to_be_visible()
                    expect(page.locator('.stats-grid')).to_be_visible()
                    pages[name]=page
                    step(f'{name}通过页面真实登录')
                    return page
                def submit(page,source,status=200):
                    with page.expect_response(lambda r:r.url.endswith('/api/events') and r.request.method=='POST') as call:
                        page.locator(f'#action-form button[type="submit"][data-source-id="{source}"]').click()
                    response=call.value
                    assert response.status==status,(source,response.status,response.text())
                    if status==200:expect(page.locator('#action-dialog')).not_to_be_visible()
                    return response.json()
                def new_reservation(page,purpose,equipment='6',days=20):
                    nav(page,'reservations')
                    page.locator('[data-action="open-reservation"]').first.click()
                    expect(page.locator('#reserve-equipment')).to_be_visible()
                    page.locator('#reserve-equipment').select_option(equipment)
                    start=(datetime.now(timezone(timedelta(hours=8)))+timedelta(days=days)).replace(hour=10,minute=0,second=0,microsecond=0)
                    page.locator('#reserve-start').fill(start.strftime('%Y-%m-%dT%H:%M'))
                    page.locator('#reserve-end').fill((start+timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'))
                    page.locator('#reserve-purpose').fill(purpose)
                    body=submit(page,'reservation.submit')
                    return body['data']['id']
                def row_for(page,rid):return page.locator('tbody tr').filter(has_text=f'#{rid}').first

                student=login('student')
                screenshot(student,'01-student-dashboard.png')
                assert student.locator('#main-nav [data-nav="rbac"]').count()==0
                assert student.locator('#main-nav [data-nav="audit"]').count()==0
                step('学生隐藏权限管理及审计菜单')
                purpose='浏览器验收：传感器数据采集实验'
                rid=new_reservation(student,purpose)
                expect(row_for(student,rid)).to_contain_text('待审批')
                assert row_for(student,rid).locator('[data-source-id="reservation.approve"]').count()==0
                screenshot(student,'02-student-reservation.png')
                step('学生监听器提交预约并持久化为待审批')

                teacher=login('teacher')
                nav(teacher,'reservations')
                row_for(teacher,rid).locator('[data-source-id="reservation.approve"]').click()
                teacher.locator('#review-note').fill('同意进行课程实验，领用时检查配件。')
                submit(teacher,'reservation.approve')
                expect(row_for(teacher,rid)).to_contain_text('已批准')
                screenshot(teacher,'03-teacher-approval.png')
                step('教师在共享预约页面批准他人申请')

                keeper=login('keeper')
                nav(keeper,'reservations')
                row_for(keeper,rid).locator('[data-source-id="loan.checkout"]').click()
                keeper.locator('#checkout-condition').fill('设备功能正常，配件齐全。')
                checkout=submit(keeper,'loan.checkout')['data']
                step('设备管理员从已批准预约办理实物领用')
                nav(keeper,'loans')
                lid=checkout['id']
                keeper.locator(f'button[data-source-id="loan.return"][data-id="{lid}"]').click()
                keeper.locator('#return-condition').fill('设备及配件齐全，外观和功能检查通过。')
                submit(keeper,'loan.return')
                expect(keeper.locator('tbody tr').filter(has_text=f'借用 #{lid}')).to_contain_text('已归还')
                screenshot(keeper,'04-loan-return.png')
                step('设备管理员办理归还，借用和预约状态同步')

                admin=login('admin')
                nav(admin,'rbac')
                expect(admin.locator('#permission-form')).to_be_visible()
                admin.locator('#role-selector').select_option(label='指导教师 · teacher')
                screenshot(admin,'05-permission-matrix.png')
                step('管理员查看页面菜单业务三类对象权限矩阵')
                target=admin.locator('.matrix-check[value="reservation:approve"]')
                expect(target).to_be_checked()
                target.uncheck()
                with admin.expect_response(lambda r:r.url.endswith('/api/events') and r.request.method=='POST') as call:
                    admin.locator('#permission-form button[type="submit"]').click()
                assert call.value.status==200
                expect(admin.locator('#permission-form button[type="submit"]')).to_be_enabled()
                step('管理员通过矩阵撤销教师批准许可')
                rid2=new_reservation(student,'浏览器验收：撤权即时生效',equipment='8',days=21)
                # Explicit negative direct-call probe in the still logged-in teacher context.
                me=teacher.request.get(base+'/api/me').json()['data']
                denied=teacher.request.post(base+'/api/events',data={'source_id':'reservation.approve','payload':{'id':rid2},'object_code':'equipment','operation_code':'view'},headers={'X-CSRF-Token':me['csrf_token']})
                assert denied.status==403 and denied.json()['error']['code']=='FORBIDDEN'
                step('教师旧会话直调审批接口被403拒绝，伪造对象操作无效')
                # Restore through the UI, preserving the original teaching roles.
                admin.locator('.matrix-check[value="reservation:approve"]').check()
                with admin.expect_response(lambda r:r.url.endswith('/api/events') and r.request.method=='POST') as call:
                    admin.locator('#permission-form button[type="submit"]').click()
                assert call.value.status==200
                step('管理员通过矩阵恢复教师许可')
                admin.get_by_role('tab',name='用户角色分配',exact=True).click()
                admin.locator('tbody tr').filter(has_text='multi').locator('[data-source-id="rbac.assign_roles"]').click()
                expect(admin.locator('#action-form input[name="role_ids"]:checked')).to_have_count(2)
                submit(admin,'rbac.assign_roles')
                screenshot(admin,'06-multi-role-assignment.png')
                step('管理员通过真实表单保存用户学生与教师双角色')

                multi=login('multi')
                mrid=new_reservation(multi,'浏览器验收：多角色禁止自审',equipment='6',days=25)
                expect(row_for(multi,mrid)).to_contain_text('本人申请不可自审')
                assert row_for(multi,mrid).locator('[data-source-id="reservation.approve"]').count()==0
                m=multi.request.get(base+'/api/me').json()['data']
                denied=multi.request.post(base+'/api/events',data={'source_id':'reservation.approve','payload':{'id':mrid}},headers={'X-CSRF-Token':m['csrf_token']})
                assert denied.status==403 and denied.json()['error']['code']=='SELF_REVIEW_FORBIDDEN'
                step('多角色账号有批准许可，仍被业务规则禁止自审')
                screenshot(multi,'07-self-review-denied.png')

                auditor=login('auditor')
                nav(auditor,'audit')
                expect(auditor.locator('tbody')).to_contain_text('当前角色没有该操作权限')
                auditor.get_by_role('tab',name='事件监听与绑定',exact=True).click()
                expect(auditor.locator('.bindings-panel')).to_contain_text('reservation.submit')
                expect(auditor.locator('.bindings-panel tbody tr')).to_have_count(9)
                screenshot(auditor,'08-event-audit.png')
                step('审计员查看九个固定事件绑定及允许拒绝记录')
                nav(auditor,'rbac')
                expect(auditor.locator('.matrix-check:enabled')).to_have_count(0)
                assert auditor.locator('#permission-form button[type="submit"]').count()==0
                step('审计员可读矩阵但无法修改授权')

                nav(admin,'reservations')
                with admin.expect_download() as dl:admin.locator('[data-action="export"]').click()
                download=dl.value
                download.save_as(str(output/'reservations.csv'))
                assert (output/'reservations.csv').read_bytes().startswith(b'\xef\xbb\xbf')
                step('管理员通过按钮下载带BOM的真实CSV')

                # Cancellation through real UI.
                nav(student,'reservations')
                row_for(student,rid2).locator('[data-source-id="reservation.cancel"]').click()
                submit(student,'reservation.cancel')
                expect(row_for(student,rid2)).to_contain_text('已取消')
                step('学生通过确认对话框取消本人待审预约')
                student.set_viewport_size({'width':390,'height':844})
                nav(student,'equipment')
                assert student.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                student.locator('[data-action="open-reservation"]').first.click()
                expect(student.locator('#reserve-purpose')).to_be_visible()
                assert student.locator('#action-dialog').evaluate('(el)=>el.getBoundingClientRect().width <= innerWidth')
                screenshot(student,'09-mobile-reservation.png',False)
                step('390像素窄屏导航和预约表单可操作且无整页水平溢出')
                student.keyboard.press('Escape')
                student.get_by_role('button',name='退出登录',exact=True).click()
                expect(student.locator('#login-view')).to_be_visible()
                assert student.request.get(base+'/api/me').status==401
                step('退出后会话失效，接口拒绝继续访问')
                assert not result['console_errors'],result['console_errors']
                step('全部浏览器上下文无JavaScript运行异常')
                result['passed']=True
                browser.close()
        except Exception:
            result['failure']=traceback.format_exc()
            raise
        finally:
            if server:server.shutdown()
            result['finished_at']=datetime.now(timezone.utc).isoformat()
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'passed':result['passed'],'steps':len(result['steps']),'failure':result.get('failure')},ensure_ascii=False))

if __name__=='__main__':run()
