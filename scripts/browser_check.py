"""Reproducible real-UI acceptance using a temporary DB and a local test server.

Run .venv/Scripts/python scripts/browser_check.py. Uses installed Edge, no browser
download. All positive mutations are performed through forms and buttons. Direct
HTTP calls below are explicitly negative security probes in the user's session.
"""
from __future__ import annotations
import json
import hashlib
import logging
import sqlite3
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
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    output=ROOT/'evidence/browser'
    output.mkdir(parents=True,exist_ok=True)
    result={'passed':False,'suite':'integrated-assets-maintenance-rbac-v2','steps':[],'console_errors':[],'unexpected_http_errors':[],
            'screenshots':[],'browser':'Microsoft Edge headless via Playwright',
            'python_version':sys.version.split()[0],
            'started_at':datetime.now(timezone.utc).isoformat(),
            'data_isolation':'fresh temporary SQLite database; positive changes through UI',
            'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                             ['app/static/app.js','app/static/styles.css','app/business.py']}}
    server=None
    with tempfile.TemporaryDirectory(prefix='labreserve-ui-') as temp:
        app=create_app({'DATABASE':str(Path(temp)/'ui.sqlite3'),'TESTING':True})
        with sqlite3.connect(Path(temp)/'ui.sqlite3') as connection:
            result['schema_tables']=[row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        connection.close()
        result['schema_table_count']=len(result['schema_tables'])
        server=make_server('127.0.0.1',0,app,threaded=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='msedge',headless=True)
                pages={}
                def step(name):
                    result['steps'].append({'name':name,'passed':True})
                    print(f"PASS {len(result['steps']):02d}: {name}",flush=True)
                def nav(page,key):
                    if page.viewport_size['width']<=700:
                        page.get_by_role('button',name='展开导航',exact=True).click()
                    page.locator(f'#main-nav [data-nav="{key}"]').click()
                    expect(page.locator('#main-content .page-heading')).to_be_visible()
                    expect(page.locator('.loading-state')).to_have_count(0)
                def screenshot(page,name,full=True,selector=None,overview=False):
                    page.locator('.toast button').evaluate_all('(els)=>els.forEach(el=>el.click())')
                    path=output/name
                    if overview:
                        page.evaluate('scrollTo(0,0)')
                        bounds=page.evaluate("""() => {
                            const a=document.querySelector('.page-heading').getBoundingClientRect();
                            const b=document.querySelector('.stats-grid').getBoundingClientRect();
                            return {x:a.left,y:a.top,width:a.width,height:b.bottom-a.top};
                        }""")
                        page.screenshot(path=str(path),clip=bounds,animations='disabled')
                    elif selector:page.locator(selector).screenshot(path=str(path),animations='disabled')
                    else:page.screenshot(path=str(path),full_page=full,animations='disabled')
                    result['screenshots'].append(str(path.relative_to(ROOT)))
                def region(page,name,selector):
                    """One contiguous crop of genuine rendered elements, with no DOM editing."""
                    page.locator('.toast button').evaluate_all('(els)=>els.forEach(el=>el.click())')
                    page.locator(selector).first.evaluate('el=>el.scrollIntoView({block:"start",inline:"start"})')
                    bounds=page.locator(selector).evaluate_all("""els => {
                        const rects=els.map(el=>el.getBoundingClientRect());
                        const x=Math.min(...rects.map(r=>r.left));
                        const y=Math.min(...rects.map(r=>r.top));
                        return {x:x,y:y,
                          width:Math.max(...rects.map(r=>r.right))-x,
                          height:Math.max(...rects.map(r=>r.bottom))-y};
                    }""")
                    assert bounds['y']>=0 and bounds['y']+bounds['height']<=page.viewport_size['height']+1,(name,bounds)
                    path=output/name
                    page.screenshot(path=str(path),clip=bounds,animations='disabled')
                    result['screenshots'].append(str(path.relative_to(ROOT)))
                def login(name):
                    ctx=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1.5,locale='zh-CN',timezone_id='Asia/Shanghai')
                    page=ctx.new_page()
                    page.set_default_timeout(15000)
                    page.on('pageerror',lambda e:result['console_errors'].append(str(e)))
                    page.on('response',lambda r:result['unexpected_http_errors'].append({'url':r.url,'status':r.status})
                            if r.status>=400 and not (r.status==401 and r.url.endswith('/api/me')) else None)
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
                    if status==200:
                        expect(page.locator('#action-dialog')).not_to_be_visible()
                        expect(page.locator('.loading-state')).to_have_count(0)
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
                    search(page,'reservations',purpose)
                    return body['data']['id']
                def row_for(page,rid):return page.locator(f'tr[data-reservation-row="{rid}"]')
                def search(page,key,text):page.locator(f'input[data-filter="search"][data-page="{key}"]').fill(text)
                def read(page,path):
                    r=page.request.get(base+path)
                    assert r.status==200,(path,r.status,r.text())
                    return r.json()['data']
                def directory_toggle(page,source,rid):
                    page.locator(f'#metadata-panel [data-source-id="{source}"][data-id="{rid}"]').click()
                    submit(page,source)

                keeper=login('keeper')
                nav(keeper,'equipment')
                keeper.locator('#metadata-panel > summary').click()
                keeper.locator('[data-source-id="category.save"][data-id="0"]').click()
                keeper.locator('#metadata-code').fill('CAT-UI-2026')
                keeper.locator('#metadata-name').fill('综合电子测量')
                keeper.locator('#metadata-description').fill('传感器采集与电子测量课程设备分类')
                category=submit(keeper,'category.save')['data']
                step('管理员通过真实目录表单新建设备分类')
                keeper.locator('[data-source-id="laboratory.save"][data-id="0"]').click()
                keeper.locator('#metadata-code').fill('LAB-UI-2026')
                keeper.locator('#metadata-name').fill('嵌入式与测量实验室')
                keeper.locator('#laboratory-location').fill('实验中心 C305')
                keeper.locator('#laboratory-manager').select_option(str(read(keeper,'/api/me')['user']['id']))
                keeper.locator('#metadata-description').fill('用于嵌入式采集、测量与设备借还实训')
                screenshot(keeper,'10a-laboratory-form.png',selector='#action-dialog')
                laboratory=submit(keeper,'laboratory.save')['data']
                step('实验室独立保存位置负责人和说明，供设备通过外键关联')
                keeper.locator('[data-action="open-equipment"]').first.click()
                keeper.locator('#device-code').fill('EQ-UI-010')
                keeper.locator('#device-name').fill('多功能数据采集仪')
                keeper.locator('#device-model').fill('DAQ-USB-6002')
                keeper.locator('#device-category').select_option(str(category['id']))
                keeper.locator('#device-laboratory').select_option(str(laboratory['id']))
                keeper.locator('#device-location').fill('C305 · 02号设备柜')
                keeper.locator('#device-description').fill('多通道模拟量采集，配USB线、端子排与传感器套件。')
                asset=submit(keeper,'equipment.save')['data']
                eid=asset['id']
                search(keeper,'equipment','EQ-UI-010')
                card=keeper.locator(f'[data-equipment-card="{eid}"]')
                expect(card).to_contain_text('综合电子测量')
                expect(card).to_contain_text('嵌入式与测量实验室')
                expect(card).to_contain_text('DAQ-USB-6002')
                screenshot(keeper,'10-equipment-assets.png',selector=f'[data-equipment-card="{eid}"]')
                step('真实设备档案保存资产编号型号服役状态并关联分类与实验室')
                card.locator('[data-source-id="maintenance.start"]').click()
                expect(keeper.locator('#action-dialog')).to_be_visible()
                keeper.locator('#maintenance-reason').fill('课程实验前进行采集通道校准与接线检查')
                maintenance=submit(keeper,'maintenance.start')['data']
                expect(card).to_contain_text('维护中')
                assert next(r for r in read(keeper,'/api/equipment') if r['id']==eid)['status']=='maintenance'
                step('开始维护创建独立记录，设备立即派生为maintenance状态')
                keeper.locator('[data-action="open-reservation"]').first.click()
                assert keeper.locator(f'#reserve-equipment option[value="{eid}"]').count()==0
                keeper.keyboard.press('Escape')
                step('预约下拉仅列available设备，维护中设备不能选择')
                keeper.locator(f'#maintenance-panel [data-source-id="maintenance.end"][data-id="{maintenance["id"]}"]').click()
                keeper.locator('#maintenance-result').fill('全部采集通道校准完成，接线及功能检查通过，恢复预约')
                screenshot(keeper,'11a-completion-form.png',selector='#action-dialog .dialog-body')
                submit(keeper,'maintenance.end')
                expect(card).to_contain_text('可预约')
                screenshot(keeper,'11-maintenance-lifecycle.png',selector='#maintenance-panel')
                screenshot(keeper,'11-compact.png',selector=f'tr[data-maintenance-row="{maintenance["id"]}"]')
                step('完成维护独立保存处理结果完成人结束时间，设备恢复available')
                directory_toggle(keeper,'category.set_active',category['id'])
                expect(card).to_contain_text('已停用')
                directory_toggle(keeper,'category.set_active',category['id'])
                directory_toggle(keeper,'laboratory.set_active',laboratory['id'])
                expect(card).to_contain_text('已停用')
                directory_toggle(keeper,'laboratory.set_active',laboratory['id'])
                expect(card).to_contain_text('可预约')
                step('分类及实验室通过各自启停事件使关联设备可用状态同步重算')
                card.locator('[data-action="open-equipment"]').click()
                keeper.locator('#device-lifecycle').select_option('disabled')
                submit(keeper,'equipment.save')
                expect(card).to_contain_text('已停用')
                card.locator('[data-action="open-equipment"]').click()
                keeper.locator('#device-lifecycle').select_option('active')
                submit(keeper,'equipment.save')
                step('档案服役状态可通过真实表单停用与恢复，与维护记录分别管理')

                student=login('student')
                screenshot(student,'01-student-dashboard.png',overview=True)
                assert student.locator('#main-nav [data-nav="rbac"]').count()==0
                assert student.locator('#main-nav [data-nav="audit"]').count()==0
                step('学生隐藏权限管理及审计菜单')
                purpose='浏览器验收：关联资产的传感器数据采集实验'
                rid=new_reservation(student,purpose,equipment=str(eid))
                search(student,'reservations',purpose)
                expect(row_for(student,rid)).to_contain_text('待审批')
                assert row_for(student,rid).locator('[data-source-id="reservation.approve"]').count()==0
                screenshot(student,'02-student-reservation.png',selector='#main-content > .panel')
                step('学生监听器提交预约并持久化为待审批')

                teacher=login('teacher')
                nav(teacher,'reservations')
                search(teacher,'reservations',purpose)
                row_for(teacher,rid).locator('[data-source-id="reservation.approve"]').click()
                teacher.locator('#review-note').fill('同意进行课程实验，领用时检查配件。')
                submit(teacher,'reservation.approve')
                expect(row_for(teacher,rid)).to_contain_text('已批准')
                reviewed=next(r for r in read(teacher,'/api/reservations') if r['id']==rid)
                assert reviewed['review_id'] and reviewed['workflow_status']=='approved'
                screenshot(teacher,'03-teacher-approval.png',selector='#main-content > .panel')
                step('教师在共享预约页面批准他人申请，独立审批记录与四态工作流对应')

                nav(keeper,'reservations')
                search(keeper,'reservations',purpose)
                row_for(keeper,rid).locator('[data-source-id="loan.checkout"]').click()
                checkout_condition='借出前：采集通道正常，USB线与端子排齐全，无外观损伤。'
                keeper.locator('#checkout-condition').fill(checkout_condition)
                checkout=submit(keeper,'loan.checkout')['data']
                step('设备管理员从已批准预约办理实物领用')
                nav(keeper,'loans')
                search(keeper,'loans','多功能数据采集仪')
                lid=checkout['id']
                keeper.locator(f'button[data-source-id="loan.return"][data-id="{lid}"]').click()
                expect(keeper.locator('#action-dialog')).to_contain_text(checkout_condition)
                keeper.locator('#return-acceptance').select_option('passed')
                return_condition='归还验收：设备及附件齐全，采集与通讯测试通过，无新增损伤。'
                keeper.locator('#return-condition').fill(return_condition)
                screenshot(keeper,'12-loan-inspection.png',selector='#action-dialog')
                submit(keeper,'loan.return')
                expect(keeper.locator('tbody tr').filter(has_text=f'借用 #{lid}')).to_contain_text('已归还')
                loan=next(r for r in read(keeper,'/api/loans') if r['id']==lid)
                assert loan['checkout_condition']==checkout_condition and loan['return_condition']==return_condition
                assert loan['checkout_by_name']=='王老师' and loan['returned_by_name']=='王老师'
                assert loan['acceptance_result']=='passed'
                screenshot(keeper,'04-loan-return.png',selector='#main-content > .panel:last-of-type')
                region(keeper,'12-compact.png','.loans-table th:nth-child(2), .loans-table th:nth-child(3), .loans-table td:nth-child(2), .loans-table td:nth-child(3)')
                step('归还独立保存经办人检查与验收通过结果，保留借出检查且同步预约状态')

                admin=login('admin')
                nav(admin,'rbac')
                expect(admin.locator('#permission-form')).to_be_visible()
                admin.locator('#role-selector').select_option(label='指导教师 · teacher')
                screenshot(admin,'05-permission-matrix.png',selector='#permission-form')
                admin.set_viewport_size({'width':1000,'height':1000})
                region(admin,'05-compact.png','.matrix-table tbody tr:nth-last-child(-n+6)')
                region(admin,'05-page-compact.png','.matrix-table thead, .matrix-table tbody tr:nth-child(-n+3)')
                admin.set_viewport_size({'width':1440,'height':1000})
                step('管理员查看页面菜单业务三类对象权限矩阵')
                target=admin.locator('.matrix-check[value="reservation:approve"]')
                expect(target).to_be_checked()
                target.uncheck()
                with admin.expect_response(lambda r:r.url.endswith('/api/events') and r.request.method=='POST') as call:
                    admin.locator('#permission-form button[type="submit"]').click()
                assert call.value.status==200
                expect(admin.locator('#permission-form button[type="submit"]')).to_be_enabled()
                step('管理员通过矩阵撤销教师批准许可')
                rid2=new_reservation(student,'浏览器验收：撤权即时生效',equipment=str(eid),days=26)
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
                screenshot(admin,'06-multi-role-assignment.png',selector='#main-content > .panel')
                step('管理员通过真实表单保存用户学生与教师双角色')

                multi=login('multi')
                mrid=new_reservation(multi,'浏览器验收：多角色禁止自审',equipment=str(eid),days=30)
                expect(row_for(multi,mrid)).to_contain_text('本人申请不可自审')
                assert row_for(multi,mrid).locator('[data-source-id="reservation.approve"]').count()==0
                m=multi.request.get(base+'/api/me').json()['data']
                denied=multi.request.post(base+'/api/events',data={'source_id':'reservation.approve','payload':{'id':mrid}},headers={'X-CSRF-Token':m['csrf_token']})
                assert denied.status==403 and denied.json()['error']['code']=='SELF_REVIEW_FORBIDDEN'
                step('多角色账号有批准许可，仍被业务规则禁止自审')
                screenshot(multi,'07-self-review-denied.png',selector='#main-content > .panel')

                auditor=login('auditor')
                nav(auditor,'equipment')
                search(auditor,'equipment','EQ-UI-010')
                expect(auditor.locator('[data-equipment-card]')).to_have_count(1)
                assert auditor.locator('[data-action="open-equipment"]').count()==0
                assert auditor.locator('[data-source-id^="maintenance."]').count()==0
                assert auditor.locator('#metadata-panel [data-source-id]').count()==0
                assert auditor.locator('[data-action="open-reservation"]').count()==0
                screenshot(auditor,'13-readonly-equipment.png',selector=f'[data-equipment-card="{eid}"]')
                step('审计员共享设备维护与目录视图，不出现任何编辑维护预约操作')
                a=read(auditor,'/api/me')
                denied=auditor.request.post(base+'/api/events',data={'source_id':'maintenance.start','payload':{'equipment_id':eid,'reason':'越权请求'}},headers={'X-CSRF-Token':a['csrf_token']})
                assert denied.status==403
                step('审计员直调维护事件被equipment:update许可校验拒绝')
                nav(auditor,'audit')
                auditor.locator('select[data-filter="status"]').select_option('denied')
                expect(auditor.locator('tbody')).to_contain_text('当前角色没有该操作权限')
                screenshot(auditor,'14-audit-denied.png',selector='#main-content > .panel')
                auditor.get_by_role('tab',name='事件监听与绑定',exact=True).click()
                expect(auditor.locator('.bindings-panel')).to_contain_text('reservation.submit')
                expect(auditor.locator('.bindings-panel tbody tr')).to_have_count(15)
                expect(auditor.locator('.bindings-panel')).to_contain_text('maintenance.start')
                expect(auditor.locator('.bindings-panel')).to_contain_text('laboratory.save')
                screenshot(auditor,'08-event-audit.png',selector='.bindings-panel')
                step('审计员查看15个固定事件绑定及允许拒绝记录，包含目录和维护事件')
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
                search(student,'reservations','浏览器验收：撤权即时生效')
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
                assert not result['unexpected_http_errors'],result['unexpected_http_errors']
                step('全部六个浏览器身份无JavaScript异常和非预期HTTP错误')
                result['verified_records']={'equipment_id':eid,'category_id':category['id'],'laboratory_id':laboratory['id'],
                                            'maintenance_id':maintenance['id'],'reservation_id':rid,'loan_id':lid}
                result['passed']=True
                browser.close()
        except Exception:
            result['failure']=traceback.format_exc()
            raise
        finally:
            if server:server.shutdown()
            if server:server.server_close()
            result['finished_at']=datetime.now(timezone.utc).isoformat()
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'passed':result['passed'],'steps':len(result['steps']),'failure':result.get('failure')},ensure_ascii=False))

if __name__=='__main__':run()
