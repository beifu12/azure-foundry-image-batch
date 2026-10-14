"""Container UI/API regressions. Synthetic data only; no Azure credentials."""
import io
import json
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from unittest.mock import Mock, patch

import web_app as web
import image_batch as batch

urlopen=build_opener(ProxyHandler({})).open

TENANT='33333333-3333-4333-8333-333333333333'
SID='11111111-1111-4111-8111-111111111111'
AID=f'/subscriptions/{SID}/resourceGroups/CV-A03/providers/Microsoft.CognitiveServices/accounts/cv-a03-001'


class MemoryAzure:
    """ARM-shaped state machine; records writes without contacting any cloud."""
    def __init__(self):self.resources={};self.writes=[]
    def all(self,path,params=None):
        if path=='/subscriptions':return [{'subscriptionId':SID,'tenantId':TENANT,'state':'Enabled','displayName':'Azure Subscription A03'}]
        if path.endswith('/locations'):return [{'name':name} for name in ('eastus','eastus2','westus3')]
        if path.endswith('/accounts'):return [v for k,v in self.resources.items() if k.endswith('/'+v.get('name','')) and v.get('kind')=='AIServices']
        if path.endswith('/deployments'):return [v for k,v in self.resources.items() if k.startswith(path+'/')]
        if path.endswith('/modelCapacities'):
            locations=['eastus2','westus3'] if params['modelName']=='gpt-image-2' else ['eastus','eastus2','westus3']
            return [{'location':r,'properties':{'skuName':'GlobalStandard','availableCapacity':1}} for r in locations]
        if path.endswith('/models'):return [{'model':{'format':'OpenAI','name':name,'version':'2026-01-01','isDefaultVersion':True,'skus':[{'name':'GlobalStandard','usageName':name,'capacity':{'minimum':1,'maximum':1,'step':1},'rateLimits':[{'count':1,'renewalPeriod':60}]}]}} for name in batch.MODELS]
        if path.endswith('/usages'):return [{'name':{'value':name},'unit':'Count','currentValue':0,'limit':1} for name in batch.MODELS]
        raise AssertionError(path)
    def optional(self,path,version=None):return self.resources.get(path)
    def get(self,path,version=None):return self.resources[path]
    def put(self,path,body,version=None):
        self.writes.append(path);value=copy_dict(body);value.update(id=path,name=path.rsplit('/',1)[-1]);value.setdefault('properties',{})['provisioningState']='Succeeded'
        if '/accounts/' in path and '/deployments/' not in path and '/projects/' not in path:
            value['identity']={'type':'SystemAssigned','principalId':'synthetic-principal'};value['properties'].update(allowProjectManagement=True,endpoint='https://example.invalid')
        self.resources[path]=value;return value
    def call(self,method,path,body=None,params=None,headers=None):
        if method=='POST' and path.endswith('/listKeys'):return {'key1':'synthetic-key'}
        raise AssertionError((method,path))


def copy_dict(value):return json.loads(json.dumps(value))


class WorkflowTests(unittest.TestCase):
    def test_logout_between_login_check_and_commit_cannot_restore_credential(self):
        session=web.Session();gate={'commit':False};original=session.lock
        class LogoutAtCommit:
            def __enter__(self):
                original.acquire()
                if gate['commit']:
                    gate['commit']=False;session.cancel.set();session.api=None;session.credential=None
                return self
            def __exit__(self,*args):original.release()
        session.lock=LogoutAtCommit()
        def subs(*args):gate['commit']=True;return [{'subscriptionId':SID,'displayName':'Synthetic'}]
        with patch('azure.identity.DeviceCodeCredential',return_value=Mock()),patch.object(batch,'subscriptions',side_effect=subs):
            web.start_login(session,{'tenant_id':TENANT});session.thread.join(3)
        self.assertEqual(session.job['status'],'cancelled');self.assertIsNone(session.api);self.assertIsNone(session.credential)

    def test_empty_version_resolves_azure_default_for_each_region(self):
        session=web.Session();session.api=Mock();session.credential=Mock();session.tenant=TENANT;session.subscriptions=[{'subscriptionId':SID,'displayName':'Azure Subscription A03'}]
        data={'subscription_ids':[SID],'models':[{'name':'gpt-image-2','version':''}],'regions':['eastus2','westus3'],'quota_scope':'regional','resource_group_template':'CV-{subcode}','account_template':'cv-{subcode}-{index:03d}','project_template':'{foundry}-resource'}
        with patch.object(web,'JobAzure',return_value=MemoryAzure()):web.start_scan(session,data);session.thread.join(3)
        self.assertEqual(session.job['status'],'done',session.job)
        rows=session.plans[0]['plan']['rows'];self.assertEqual({r['version'] for r in rows},{'2026-01-01'})
        self.assertTrue(all(r['capacity']==1 for r in rows));self.assertEqual(len(rows),2)

    def test_default_version_requires_explicit_azure_default_marker(self):
        rows=[{'model':{'name':'gpt-6-sol','format':'OpenAI','version':'v2','isDefaultVersion':True,'skus':[{'name':'GlobalStandard'}]}},{'model':{'name':'gpt-6-sol','format':'OpenAI','version':'v9','skus':[{'name':'GlobalStandard'}]}}]
        self.assertEqual(web.default_version(rows,'gpt-6-sol','GlobalStandard'),'v2')
        with self.assertRaises(ValueError):web.default_version(rows[1:],'gpt-6-sol','GlobalStandard')

    def test_cancel_interrupts_rate_limit_wait(self):
        event=threading.Event();event.set();api=web.JobAzure(Mock(),event,lambda _:None)
        with self.assertRaises(web.Cancelled):api.pause(120)

    def test_two_models_reuse_accounts_and_projects_and_region_numbers(self):
        session=web.Session();session.api=Mock();session.credential=Mock();session.tenant=TENANT
        session.subscriptions=[{'subscriptionId':SID,'displayName':'Azure Subscription A03'}]
        api=MemoryAzure()
        data={'subscription_ids':[SID],'models':[{'name':'gpt-image-2','version':'2026-01-01'},{'name':'gpt-6-sol','version':'2026-01-01'}],'regions':['eastus2','westus3'],'auto_regions':True,'quota_scope':'regional','resource_group_template':'CV-{subcode}','account_template':'cv-{subcode}-{index:03d}','project_template':'{foundry}-resource'}
        with patch.object(web,'JobAzure',return_value=api):
            web.start_scan(session,data);session.thread.join(3)
            self.assertEqual(session.job['status'],'done',session.job)
            web.start_deploy(session,{'plan_id':session.plan_id,'confirmed':True});session.thread.join(3)
        self.assertEqual(session.job['status'],'done',session.job)
        self.assertEqual(len(session.results),5)
        accounts=[p for p in api.writes if '/accounts/' in p and '/deployments/' not in p and '/projects/' not in p]
        projects=[p for p in api.writes if '/projects/' in p]
        self.assertEqual(len(accounts),3);self.assertEqual(len(projects),3)
        self.assertEqual(len(set(accounts)),3)
        names={r['区域']:r['资源名称-foundry'] for r in session.results}
        self.assertEqual(names['East US 2'],'cv-a03-001');self.assertEqual(names['West US 3'],'cv-a03-002');self.assertEqual(names['eastus'],'cv-a03-006')

    def deployment_session(self):
        session=web.Session();session.api=Mock();session.credential=Mock();session.tenant=TENANT;session.plan_id='reviewed'
        row={'subscription':'Azure Subscription A03','subscription_id':SID,'region':'eastus2','model':'gpt-image-2','version':'requested','status':'existing','sku':'GlobalStandard'}
        plan={'rows':[row],'errors':[],'config':{},'tenant_id':TENANT}
        session.plans=[{'plan':plan,'projects':{AID:{'name':'project','new':False}}}]
        output={'account_id':AID,'model':{'name':'gpt-image-2','version':'actual-existing'},'deployment':'existing','capacity':2,'endpoint':'https://example.invalid'}
        return session,{'rows':[{**row,'outputs':[output]}],'errors':[]}

    def test_existing_deployment_exports_actual_version(self):
        session,report=self.deployment_session()
        with patch.object(batch,'execute',return_value=report),patch.object(web,'ensure_project'):
            web.start_deploy(session,{'plan_id':'reviewed','confirmed':True});session.thread.join(3)
        self.assertEqual(session.results[0]['version'],'actual-existing')

    def test_cancel_preserves_completed_resource_records(self):
        session,report=self.deployment_session()
        def execute(api,plan,on_progress):on_progress(report);raise web.Cancelled()
        with patch.object(batch,'execute',side_effect=execute):
            web.start_deploy(session,{'plan_id':'reviewed','confirmed':True});session.thread.join(3)
        self.assertEqual(session.job['status'],'cancelled')
        self.assertEqual(len(session.results),1)
        self.assertEqual(session.results[0]['version'],'actual-existing')
        self.assertEqual(session.results[0]['资源'],'')

    def test_image2_restriction_does_not_limit_other_models(self):
        session=web.Session();session.tenant=TENANT;session.subscriptions=[{'subscriptionId':SID}]
        data={'subscription_ids':[SID],'models':[{'name':'gpt-image-2','version':'2026-04-21'},{'name':'gpt-6-sol','version':'2026-01-01'}],'regions':['eastus2','eastus'],'auto_regions':True,'resource_group_template':'rg-{sub8}','account_template':'ai-{sub8}-{region}','project_template':'{foundry}-project'}
        configs,_=web.configurations(session,data)
        self.assertEqual(configs[0]['regions'],['eastus2']);self.assertEqual(configs[1]['regions'],'auto')

    def test_excel_has_exact_customer_columns_and_text_values(self):
        from openpyxl import load_workbook
        rows=[{'订阅':'=unsafe','订阅 ID':SID,'资源组':'CV-A03','资源名称-foundry':'cv-a03-001','区域':'East US 2','资源':'cv-a03-001-resource','url':'https://example.invalid','密钥':'synthetic-key'}]
        book=load_workbook(io.BytesIO(web.excel(rows)))
        self.assertEqual(list(next(book.active.values)),list(web.COLUMNS))
        self.assertEqual(book.active['A2'].data_type,'s')
        self.assertEqual(book.active['H2'].value,'synthetic-key')

    def test_review_cannot_be_executed_using_browser_supplied_plan(self):
        session=web.Session();session.api=Mock();session.tenant=TENANT
        with self.assertRaises(ValueError):web.start_deploy(session,{'plan_id':'made-up','confirmed':True})
        session.api.put.assert_not_called()

    def test_session_snapshot_does_not_expose_keys_or_credentials(self):
        session=web.Session();session.credential=Mock();session.keys={AID:'synthetic-key'}
        session.results=[{'密钥':'synthetic-key','订阅 ID':SID}]
        snapshot=json.dumps(session.snapshot())
        self.assertNotIn('synthetic-key',snapshot)
        self.assertNotIn('credential',snapshot)

    def test_cancel_stops_next_azure_call(self):
        event=threading.Event();event.set()
        api=web.JobAzure(Mock(),event,lambda _:None)
        with patch.object(batch.Azure,'call') as request:
            with self.assertRaises(web.Cancelled):api.call('PUT',AID,{})
        request.assert_not_called()

    def test_existing_project_is_reused_without_write(self):
        api=Mock();api.optional.return_value={'id':AID+'/projects/p','location':'eastus2','properties':{'provisioningState':'Succeeded'}}
        web.ensure_project(api,AID,'p','eastus2')
        api.put.assert_not_called()

    def test_missing_project_requires_parent_support_before_write(self):
        api=Mock();api.optional.return_value=None;api.get.return_value={'kind':'OpenAI','properties':{}}
        with self.assertRaises(ValueError):web.ensure_project(api,AID,'p','eastus2')
        api.put.assert_not_called()

    def test_config_only_accepts_visible_selected_subscriptions(self):
        session=web.Session();session.tenant=TENANT;session.subscriptions=[{'subscriptionId':SID}]
        with self.assertRaises(ValueError):web.configurations(session,{'subscription_ids':['44444444-4444-4444-8444-444444444444']})

    def test_device_login_challenge_is_returned_without_token(self):
        session=web.Session()
        def factory(**kwargs):
            kwargs['prompt_callback']('https://microsoft.com/devicelogin','TEST-CODE',None)
            result=Mock();result.get_token.side_effect=RuntimeError('token=do-not-leak');return result
        with patch('azure.identity.DeviceCodeCredential',side_effect=factory):
            web.start_login(session,{'tenant_id':TENANT});session.thread.join(3)
        self.assertNotIn('do-not-leak',json.dumps(session.snapshot()))
        self.assertEqual(session.snapshot()['job']['status'],'failed')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=web.make_server('127.0.0.1',0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.origin=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()

    def bootstrap(self):
        with urlopen(self.origin+'/') as response:
            self.assertIn('Foundry',response.read().decode());return response.headers['Set-Cookie'].split(';')[0]

    def test_session_isolation_and_no_cache(self):
        first=self.bootstrap();second=self.bootstrap();self.assertNotEqual(first,second)
        with urlopen(Request(self.origin+'/api/state',headers={'Cookie':first})) as response:
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertFalse(json.load(response)['connected'])

    def test_unused_anonymous_sessions_cannot_permanently_fill_capacity(self):
        with self.server.sessions_lock:
            for i in range(256):self.server.sessions['unused-'+str(i)]=web.Session()
        self.bootstrap()

    def test_cross_origin_write_is_rejected_before_body_read(self):
        cookie=self.bootstrap()
        request=Request(self.origin+'/api/login',data=b'{}',headers={'Cookie':cookie,'Origin':'https://evil.invalid','Content-Type':'application/json','X-Requested-With':'FoundryUI'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,403)

    def test_key_export_requires_explicit_post(self):
        cookie=self.bootstrap()
        with self.assertRaises(HTTPError) as error:urlopen(Request(self.origin+'/api/export',headers={'Cookie':cookie}))
        self.assertEqual(error.exception.code,404)

    def test_unconnected_client_cannot_scan(self):
        cookie=self.bootstrap()
        request=Request(self.origin+'/api/scan',data=b'{}',headers={'Cookie':cookie,'Origin':self.origin,'Content-Type':'application/json','X-Requested-With':'FoundryUI'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,400)

    def test_public_https_origin_uses_secure_cookie_and_rejects_http_origin(self):
        with patch.object(web,'PUBLIC_ORIGIN','https://workspace.example.invalid'):
            with urlopen(Request(self.origin+'/',headers={'Host':'workspace.example.invalid'})) as response:
                cookie=response.headers['Set-Cookie'];self.assertIn('; Secure',cookie)
            request=Request(self.origin+'/api/login',data=b'{}',headers={'Host':'workspace.example.invalid','Cookie':cookie.split(';')[0],'Origin':'http://workspace.example.invalid','Content-Type':'application/json','X-Requested-With':'FoundryUI'})
            with self.assertRaises(HTTPError) as error:urlopen(request)
            self.assertEqual(error.exception.code,403)


if __name__=='__main__':unittest.main()
