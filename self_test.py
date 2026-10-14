"""Customer script regressions; no real identities or cloud writes."""
import importlib.util
import sys
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / 'image_batch.py'
spec = importlib.util.spec_from_file_location('image_batch', SOURCE)
batch = importlib.util.module_from_spec(spec)
sys.modules['image_batch'] = batch
if SOURCE.exists(): spec.loader.exec_module(batch)

SID='11111111-1111-4111-8111-111111111111'
TENANT='33333333-3333-4333-8333-333333333333'
ACCOUNT=f'/subscriptions/{SID}/resourceGroups/existing/providers/Microsoft.CognitiveServices/accounts/existing'


def configuration():
    return dict(tenant_id=TENANT,model='gpt-image-2',model_version='2026-04-21',sku='GlobalStandard',subscription_ids='all',regions='auto',quota_scope='regional',resource_group_template='rg-{sub8}-{region}',account_template='ai-{sub8}-{region}',deployment_name='images')


class FakeAzure:
    def __init__(self, accounts=None, deployments=None):
        self.calls=[];self.accounts=accounts or [];self.deployments=deployments or []
        self.remaining=2;self.read_failure=False;self.credential=None

    def all(self,path,params=None):
        self.calls.append(('GET',path))
        if path=='/subscriptions':return [{'subscriptionId':SID,'displayName':'测试订阅','tenantId':TENANT,'state':'Enabled'}]
        if path.endswith('/accounts'):return self.accounts
        if path.endswith('/deployments'):
            if self.read_failure:raise batch.AzureError(403)
            return self.deployments
        if path.endswith('/modelCapacities'):return [{'location':r,'properties':{'skuName':'GlobalStandard','availableCapacity':2}} for r in ['eastus2','westus3']]
        if path.endswith('/models'):return [{'model':{'format':'OpenAI','name':'gpt-image-2','version':'2026-04-21','skus':[{'name':'GlobalStandard','usageName':'image-global','capacity':{'minimum':1,'maximum':10,'step':1},'rateLimits':[{'count':1,'renewalPeriod':60}]}]}}]
        if path.endswith('/usages'):return [{'name':{'value':'image-global'},'unit':'Count','currentValue':0,'limit':self.remaining}]
        raise AssertionError(path)

    def optional(self,path,version=None):return None
    def get(self,path,version=None):
        self.calls.append(('GET',path))
        if '/deployments/' in path:
            return {'id':path,'name':path.split('/')[-1],'sku':{'name':'GlobalStandard','capacity':2},'properties':{'provisioningState':'Succeeded','model':{'format':'OpenAI','name':'gpt-image-2','version':'2026-04-21'},'rateLimits':[{'count':2,'renewalPeriod':60}]}}
        return {'id':path,'kind':'AIServices','location':'eastus2','properties':{'provisioningState':'Succeeded','endpoint':'https://example.invalid/'}}
    def put(self,path,body,version=None):
        self.calls.append(('PUT',path));return {}


class ScanTests(unittest.TestCase):
    def test_text_models_are_valid_selections_without_inventing_versions(self):
        for model in ('gpt-5.6-terra','gpt-5.6-luna','gpt-5.6-sol'):
            config=configuration();config['model']=model
            batch.check_config(config)

    def test_customer_names_support_subscription_code_and_region_index(self):
        self.assertEqual(batch.render_name('cv-{subcode}-{index:03d}',SID,'eastus2','account','Azure Subscription A03',2),'cv-a03-002')

    def test_scan_reports_real_subscription_progress(self):
        events=[]
        batch.scan(FakeAzure(),configuration(),on_progress=lambda *event:events.append(event))
        self.assertEqual([e[:2] for e in events],[(0,1),(1,1)])

    def test_scan_reads_only_and_allocates_remaining(self):
        api=FakeAzure();report=batch.scan(api,configuration())
        self.assertEqual([r['capacity'] for r in report['rows']],[2,2])
        self.assertTrue(all(m=='GET' for m,p in api.calls))

    def test_scan_global_pool_is_not_five_independent_pools(self):
        config=configuration();config['quota_scope']='subscription'
        rows=batch.scan(FakeAzure(),config)['rows']
        self.assertEqual(sum(r['capacity'] for r in rows),2)

    def test_unconfirmed_pool_still_produces_inventory_but_no_creation(self):
        config=configuration();config['quota_scope']='unknown'
        rows=batch.scan(FakeAzure(),config)['rows']
        self.assertTrue(all(r['status']=='blocked' for r in rows))
        self.assertTrue(all('capacity' not in r for r in rows))

    def test_unreadable_deployments_are_not_treated_as_empty(self):
        api=FakeAzure([{'id':ACCOUNT,'location':'eastus2','kind':'AIServices'}]);api.read_failure=True
        report=batch.scan(api,configuration())
        self.assertEqual(report['rows'],[])
        self.assertEqual(len(report['errors']),1)

    def test_existing_model_other_version_is_not_duplicated(self):
        api=FakeAzure([{'id':ACCOUNT,'location':'eastus2','kind':'AIServices','properties':{'provisioningState':'Succeeded'}}],[{'name':'old','sku':{'name':'GlobalStandard'},'properties':{'provisioningState':'Succeeded','model':{'format':'OpenAI','name':'gpt-image-2','version':'old'}}}])
        row=batch.scan(api,configuration())['rows'][0]
        self.assertEqual(row['status'],'existing')
        self.assertEqual(row['existing'][0]['version'],'old')

    def test_execute_rejects_stale_capacity_before_writing(self):
        api=FakeAzure();confirmed=batch.scan(api,configuration());api.remaining=1
        with self.assertRaises(ValueError):batch.execute(api,confirmed)
        self.assertTrue(all(m=='GET' for m,p in api.calls))

    def test_multiple_existing_accounts_require_unambiguous_choice(self):
        api=FakeAzure([{'id':ACCOUNT+str(i),'location':'eastus2','kind':'AIServices'} for i in range(2)])
        row=batch.scan(api,configuration())['rows'][0]
        self.assertEqual(row['status'],'blocked')

    def test_secret_file_never_overwrites_previously_captured_value(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'key.json';batch.write_json(path,{'key':'synthetic'},private=True)
            with self.assertRaises(FileExistsError):batch.write_json(path,{'key':'replacement'},private=True)
            self.assertEqual(batch.read_json(path)['key'],'synthetic')

    def test_successful_deploy_reports_actual_rpm_and_no_key(self):
        config=configuration();config['regions']=['eastus2']
        api=FakeAzure();confirmed=batch.scan(api,config)
        result=batch.execute(api,confirmed)
        row=result['rows'][0]
        self.assertEqual(row['status'],'created')
        self.assertEqual(row['outputs'][0]['rpm'],2)
        self.assertNotIn('key',row['outputs'][0])
        self.assertEqual(sum(m=='PUT' and '/deployments/' in p for m,p in api.calls),1)

    def test_invalid_output_prevents_application_setup_writes(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'config.json';batch.write_json(config,configuration())
            output=Path(folder)/'existing.json';batch.write_json(output,{})
            with patch.object(sys,'argv',['image_batch.py','setup-app','--config',str(config),'--output',str(output),'--app-name','客户应用','--execute']),patch.object(batch,'credential',side_effect=AssertionError('must validate before auth')) as auth:
                self.assertEqual(batch.main(),1)
                auth.assert_not_called()

    def test_unknown_scope_has_no_planned_rows_to_execute(self):
        config=configuration();config['quota_scope']='unknown'
        report=batch.scan(FakeAzure(),config)
        self.assertEqual([r for r in report['rows'] if r['status']=='planned'],[])

    def test_failed_existing_deployment_is_blocked_not_recreated(self):
        api=FakeAzure([{'id':ACCOUNT,'location':'eastus2','kind':'AIServices','properties':{'provisioningState':'Succeeded'}}],[{'name':'failed','sku':{'name':'GlobalStandard'},'properties':{'provisioningState':'Failed','model':{'format':'OpenAI','name':'gpt-image-2'}}}])
        row=batch.scan(api,configuration())['rows'][0]
        self.assertEqual(row['status'],'blocked')
        self.assertNotIn('capacity',row)

    def test_subscription_scan_errors_survive_execution(self):
        api=FakeAzure();config=configuration();config['regions']=['eastus2','unsupported']
        plan=batch.scan(api,config)
        report=batch.execute(api,plan)
        self.assertEqual(len(report['errors']),1)

    def test_progress_checkpoint_runs_after_individual_failure(self):
        class Failing(FakeAzure):
            def put(self,*args):raise batch.AzureError(403)
        api=Failing();plan=batch.scan(api,configuration());checkpoints=[]
        report=batch.execute(api,plan,lambda value:checkpoints.append(len(value['rows'])))
        self.assertEqual(checkpoints,[1,2])
        self.assertTrue(all(r['status']=='failed' for r in report['rows']))

    def test_identical_catalog_duplicates_do_not_hide_supported_region(self):
        class Duplicate(FakeAzure):
            def all(self,path,params=None):
                rows=super().all(path,params)
                return rows+rows if path.endswith('/models') else rows
        rows=batch.scan(Duplicate(),configuration())['rows']
        self.assertTrue(all(r['status']=='planned' for r in rows))

    def test_conflicting_catalog_duplicates_remain_blocked(self):
        import copy
        class Conflicting(FakeAzure):
            def all(self,path,params=None):
                rows=super().all(path,params)
                if path.endswith('/models'):
                    second=copy.deepcopy(rows[0]);second['model']['skus'][0]['usageName']='different'
                    return rows+[second]
                return rows
        self.assertTrue(all(r['status']=='blocked' for r in batch.scan(Conflicting(),configuration())['rows']))


class SetupTests(unittest.TestCase):
    def setUp(self):
        setup_spec=importlib.util.spec_from_file_location('app_setup',SOURCE.with_name('app_setup.py'))
        self.setup=importlib.util.module_from_spec(setup_spec);setup_spec.loader.exec_module(self.setup)

    def test_application_setup_preview_performs_only_reads(self):
        setup_source=SOURCE.with_name('app_setup.py')
        setup_spec=importlib.util.spec_from_file_location('app_setup',setup_source)
        setup=importlib.util.module_from_spec(setup_spec)
        if setup_source.exists():setup_spec.loader.exec_module(setup)
        class Graph:
            def all(self,path,params=None):return []
        result=setup.setup(FakeAzure(),Graph(),configuration(),'客户图像部署',False,False,90,None)
        self.assertFalse(result['executed'])
        self.assertEqual(result['application_action'],'create')

    def test_role_read_failure_records_subscription_and_continues(self):
        class Graph:
            def all(self,path,params=None):
                if 'servicePrincipals' in path:return [{'id':'44444444-4444-4444-8444-444444444444','appOwnerOrganizationId':TENANT}]
                return [{'id':'55555555-5555-4555-8555-555555555555','appId':'66666666-6666-4666-8666-666666666666','displayName':'test','signInAudience':'AzureADMyOrg'}]
        class Arm(FakeAzure):
            def all(self,path,params=None):
                if 'roleAssignments' in path:raise batch.AzureError(403)
                return super().all(path,params)
        result=self.setup.setup(Arm(),Graph(),configuration(),'test',False,False,90,None)
        self.assertEqual(result['subscriptions'][0]['status'],'failed')
        self.assertEqual(len(result['errors']),1)

    def test_existing_conditional_assignment_id_is_not_overwritten(self):
        import tempfile
        class Graph:
            def all(self,path,params=None):
                if 'servicePrincipals' in path:return [{'id':'44444444-4444-4444-8444-444444444444','appOwnerOrganizationId':TENANT}]
                return [{'id':'55555555-5555-4555-8555-555555555555','appId':'66666666-6666-4666-8666-666666666666','displayName':'test','signInAudience':'AzureADMyOrg'}]
        class Arm(FakeAzure):
            def all(self,path,params=None):return [] if 'roleAssignments' in path else super().all(path,params)
            def optional(self,path,version=None):return {'properties':{'condition':'existing-condition'}}
        with tempfile.TemporaryDirectory() as folder:
            arm=Arm();result=self.setup.setup(arm,Graph(),configuration(),'test',True,False,90,str(Path(folder)/'unused.private.json'))
            self.assertEqual(result['subscriptions'][0]['status'],'failed')
            self.assertFalse(any(m=='PUT' for m,p in arm.calls))


class AllocationTests(unittest.TestCase):
    def test_regional_quota_is_not_shared(self):
        rows = [dict(region=r, pool=r, remaining=2, maximum=10, minimum=1, step=1) for r in ['a', 'b', 'c', 'd', 'e']]
        self.assertEqual(batch.allocate(rows), [2]*5)

    def test_shared_pool_cannot_be_multiplied_by_regions(self):
        rows = [dict(region=r, pool='global', remaining=6, maximum=10, minimum=1, step=1) for r in ['a', 'b', 'c', 'd', 'e']]
        values = batch.allocate(rows)
        self.assertEqual(sum(values), 6)
        self.assertTrue(all(v >= 1 for v in values))

    def test_shared_pool_uses_most_conservative_remaining(self):
        rows = [dict(pool='global', remaining=n, maximum=10, minimum=1, step=1) for n in [5, 3]]
        self.assertEqual(sum(batch.allocate(rows)), 3)

    def test_allowed_values_and_steps_are_observed(self):
        self.assertEqual(batch.allowed_capacity(8, {'allowedValues': [1, 4, 7]}), 7)
        self.assertEqual(batch.allowed_capacity(8, {'minimum':2,'maximum':20,'step':3}), 8)
        self.assertEqual(batch.allowed_capacity(7, {'minimum':2,'maximum':20,'step':3}), 5)
        self.assertEqual(batch.allowed_capacity(1, {'minimum':2,'maximum':20,'step':3}), 0)

    def test_missing_constraints_are_not_guessed(self):
        with self.assertRaises(ValueError): batch.allowed_capacity(8, {})

    def test_pool_below_minimum_does_not_create_zero_deployment(self):
        rows = [dict(pool='g', remaining=1, minimum=2, maximum=5, step=1)]
        self.assertEqual(batch.allocate(rows), [0])

    def test_existing_other_version_counts_as_existing_model(self):
        dep = {'name':'existing','sku':{'name':'GlobalStandard'},'properties':{'model':{'name':'gpt-image-2','version':'old','format':'OpenAI'}}}
        self.assertTrue(batch.same_model(dep, 'gpt-image-2', 'GlobalStandard'))
        self.assertFalse(batch.same_model(dep, 'gpt-image-2', 'DataZoneStandard'))

    def test_subscription_scope_requires_confirmed_config(self):
        self.assertEqual(batch.quota_pool('regional', 'eastus2', {}), 'eastus2')
        self.assertEqual(batch.quota_pool('subscription', 'eastus2', {}), 'subscription')
        with self.assertRaises(ValueError): batch.quota_pool('unknown','eastus2',{})
        with self.assertRaises(ValueError): batch.quota_pool('data-zone','eastus2',{})

    def test_rpm_uses_authoritative_rate_period(self):
        self.assertEqual(batch.rpm([{'key':'requests','count':3,'renewalPeriod':10}]),18)
        self.assertIsNone(batch.rpm([{'key':'tokens','count':1000,'renewalPeriod':60}]))

    def test_large_shared_quota_is_fully_allocated(self):
        rows=[dict(pool='global',remaining=100000,maximum=100000,minimum=1,step=1) for _ in range(5)]
        self.assertEqual(batch.allocate(rows),[20000]*5)

    def test_names_are_customer_templates_with_subscription_id(self):
        self.assertEqual(batch.render_name('ai-{sub8}-{region}', '12345678-abcd-4abc-8abc-123456789abc','eastus2','account'), 'ai-12345678-eastus2')
        with self.assertRaises(ValueError): batch.render_name('ai/{region}','x','eastus2','account')
        with self.assertRaises(ValueError): batch.render_name('ai-{bad}','x','eastus2','account')


class EnvironmentTests(unittest.TestCase):
    def test_single_subscription_string_is_configuration_error_before_login(self):
        from unittest.mock import patch
        config=configuration();config['subscription_ids']=SID
        with patch.object(batch,'credential') as auth:
            report=batch.environment_report('app',config,online=True)
        failures=[c for c in report['checks'] if c['status']=='failed']
        self.assertEqual(failures[0]['name'],'客户配置')
        self.assertIn('subscription_ids',failures[0]['detail'])
        self.assertIn('[',failures[0]['detail'])
        auth.assert_not_called()

    def test_invalid_subscription_list_is_rejected_before_login(self):
        from unittest.mock import patch
        for selected in ([], ['not-a-uuid'], [None], 123):
            config=configuration();config['subscription_ids']=selected
            with patch.object(batch,'credential') as auth:
                report=batch.environment_report('app',config,online=True)
            self.assertTrue(any(c['name']=='客户配置' and c['status']=='failed' for c in report['checks']))
            self.assertIn('subscription_ids',str(report))
            auth.assert_not_called()

    def test_subscription_configuration_accepts_all_or_id_list(self):
        for selected in ('all', [SID]):
            config=configuration();config['subscription_ids']=selected
            batch.check_config(config)

    def test_admin_mode_reports_missing_cli_without_attempting_login(self):
        from unittest.mock import patch
        with patch('shutil.which',return_value=None),patch.object(batch,'credential') as auth:
            report=batch.environment_report('admin',configuration(),online=True)
        self.assertTrue(any(c['status']=='failed' and c['name']=='Azure CLI' for c in report['checks']))
        auth.assert_not_called()

    def test_application_offline_mode_does_not_require_cli(self):
        from unittest.mock import patch
        with patch('shutil.which',side_effect=AssertionError('app mode must not check az')),patch.object(batch,'credential') as auth:
            report=batch.environment_report('app',configuration(),online=False)
        self.assertFalse(any(c['status']=='failed' for c in report['checks']))
        self.assertFalse(report['online_verified']);auth.assert_not_called()

    def test_wrong_cloud_is_reported_before_azure_requests(self):
        from unittest.mock import patch,Mock
        with patch('shutil.which',return_value='az'),patch('subprocess.run',return_value=Mock(returncode=0,stdout='AzureChinaCloud')),patch.object(batch,'credential') as auth:
            report=batch.environment_report('admin',configuration(),online=True)
        self.assertTrue(any(c['status']=='failed' and c['name']=='Azure 云环境' for c in report['checks']))
        auth.assert_not_called()

    def test_login_failure_hides_sdk_exception_and_credentials(self):
        from unittest.mock import patch
        with patch.object(batch,'credential',side_effect=RuntimeError('client_secret=must-not-leak')):
            report=batch.environment_report('app',configuration(),online=True)
        self.assertTrue(any(c['status']=='failed' for c in report['checks']))
        self.assertNotIn('must-not-leak',str(report))

    def test_readonly_check_returns_only_subscription_count(self):
        from unittest.mock import patch
        with patch.object(batch,'credential',return_value=object()),patch.object(batch,'Azure',return_value=FakeAzure()):
            report=batch.environment_report('app',configuration(),online=True)
        self.assertTrue(report['online_verified'])
        self.assertEqual(report['visible_subscriptions'],1)
        self.assertNotIn(SID,str(report));self.assertNotIn(TENANT,str(report))

    def test_application_authority_cannot_be_redirected_by_environment(self):
        from unittest.mock import patch
        import os
        with patch.dict(os.environ,{'AZURE_TENANT_ID':TENANT,'AZURE_CLIENT_ID':'66666666-6666-4666-8666-666666666666','AZURE_CLIENT_SECRET':'synthetic-test-only','AZURE_AUTHORITY_HOST':'https://unexpected.invalid'}),patch('azure.identity.ClientSecretCredential') as sdk:
            batch.credential(configuration(),'app')
        self.assertEqual(sdk.call_args.kwargs.get('authority'),'https://login.microsoftonline.com')


class PackageTests(unittest.TestCase):
    def setUp(self):
        package_source=SOURCE.with_name('package_release.py')
        package_spec=importlib.util.spec_from_file_location('package_release',package_source)
        self.package=importlib.util.module_from_spec(package_spec)
        if package_source.exists():package_spec.loader.exec_module(self.package)

    def test_zip_members_use_ascii_names_and_predictable_root(self):
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'package.zip'
            self.package.build_package(output)
            with zipfile.ZipFile(output) as archive:
                self.assertTrue(all(name.isascii() for name in archive.namelist()))
                self.assertTrue(all(name.startswith('azure-foundry-image-batch/') for name in archive.namelist()))
                self.assertIsNone(archive.testzip())

    def test_package_excludes_local_customer_files(self):
        import tempfile
        import zipfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';source.mkdir()
            for name in self.package.FILES:
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('source fixture',encoding='utf-8')
            (source/'config.json').write_text('customer fixture',encoding='utf-8')
            (source/'keys.private.json').write_text('private fixture',encoding='utf-8')
            with patch.object(self.package,'SOURCE',source):self.package.build_package(Path(folder)/'package.zip')
            with zipfile.ZipFile(Path(folder)/'package.zip') as archive:
                self.assertFalse(any(name.endswith('/config.json') or '.private.json' in name for name in archive.namelist()))

    def test_package_preserves_existing_archive(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'package.zip';output.write_bytes(b'previous archive')
            with self.assertRaises(FileExistsError):self.package.build_package(output)
            self.assertEqual(output.read_bytes(),b'previous archive')


class TransportTests(unittest.TestCase):
    def test_foreign_paging_host_rejected_before_authentication(self):
        api = batch.Azure(None)
        with self.assertRaises(ValueError): api.call('GET','https://example.com/next')

    def test_role_detection_ignores_conditional_and_child_scope(self):
        scope='/subscriptions/11111111-1111-4111-8111-111111111111'
        row={'properties':{'principalId':'p','scope':scope,'roleDefinitionId':scope+'/providers/Microsoft.Authorization/roleDefinitions/'+batch.CONTRIBUTOR}}
        self.assertTrue(batch.granted([row],scope,'p'))
        row['properties']['condition']='expr'
        self.assertFalse(batch.granted([row],scope,'p'))
        row['properties'].pop('condition');row['properties']['scope']=scope+'/resourceGroups/test'
        self.assertFalse(batch.granted([row],scope,'p'))


if __name__ == '__main__': unittest.main()
