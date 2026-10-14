#!/usr/bin/env python3
"""Azure 图像模型批量部署。默认只读；仅支持 Azure 公有云。"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from uuid import UUID

ARM = 'https://management.azure.com'
GRAPH = 'https://graph.microsoft.com'
VERSION = '2025-06-01'
MODELS = ('gpt-image-2', 'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-6-sol', 'gpt-6-luna', 'gpt-6-astra', 'gpt-6.1-sol')
CONTRIBUTOR = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
OWNER = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'


class AzureError(RuntimeError):
    def __init__(self, status, code='AzureError'):
        self.status = status
        super().__init__(f'Azure HTTP {status}（{code}）；请检查权限、策略、配额或网络。')


class Azure:
    def __init__(self, credential, host=ARM):
        import requests
        self.credential = credential
        self.host = host
        self.session = requests.Session()

    def pause(self,seconds):time.sleep(seconds)

    def call(self, method, path, body=None, params=None, headers=None):
        url = self.host + path if path.startswith('/') else path
        if not url.startswith(self.host + '/') or urlsplit(url).netloc != urlsplit(self.host).netloc:
            raise ValueError('拒绝向非 Azure 管理端点发送凭据。')
        auth = {'Authorization': 'Bearer ' + self.credential.get_token(self.host + '/.default').token}
        auth.update(headers or {})
        for attempt in range(5):
            try:
                response = self.session.request(method, url, json=body, params=params, headers=auth, timeout=60, allow_redirects=False)
            except Exception:
                raise RuntimeError('Azure 网络请求未完成；如为写入，请先重新扫描核对状态，勿直接重复提交。') from None
            # Read operations only: never automatically repeat writes or addPassword.
            if method == 'GET' and response.status_code in (429, 503) and attempt < 4:
                wait = min(120, max(1, int(response.headers.get('Retry-After', 2**(attempt+1))) if response.headers.get('Retry-After','').isdigit() else 2**(attempt+1)))
                print(f'Azure 限流/繁忙，{wait} 秒后重试读取…', flush=True)
                self.pause(wait)
                continue
            if not response.ok:
                try: code = response.json().get('error', {}).get('code', 'AzureError')
                except ValueError: code = 'AzureError'
                # Never echo raw service responses, credentials or URLs into logs.
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', str(code)): code = 'AzureError'
                raise AzureError(response.status_code, code)
            return response.json() if response.content else {}

    def get(self, path, version=VERSION):
        return self.call('GET', path, params={'api-version':version})

    def optional(self, path, version=VERSION):
        try: return self.get(path, version)
        except AzureError as error:
            if error.status == 404: return None
            raise

    def all(self, path, params=None):
        rows, seen = [], set()
        params = params or {'api-version':VERSION}
        while path:
            if path in seen: raise ValueError('Azure 分页循环，不能确认扫描完整。')
            seen.add(path)
            result = self.call('GET', path, params=params)
            if not isinstance(result.get('value'), list): raise ValueError('Azure 列表响应不完整。')
            rows.extend(result['value'])
            path = result.get('nextLink') or result.get('@odata.nextLink')
            params = None
        return rows

    def put(self, path, body, version=VERSION):
        return self.call('PUT', path, body, {'api-version':version}, {'If-None-Match':'*'})


def integer(value,field='Azure 容量值'):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or value < 0:
        raise ValueError(field+' 缺失或不是非负整数，不能确认容量。')
    return int(value)


def allowed_capacity(limit, constraints):
    limit = integer(limit)
    if constraints.get('allowedValues'):
        values = [integer(v) for v in constraints['allowedValues']]
        minimum=integer(constraints.get('minimum',1),'SKU capacity.minimum')
        maximum=integer(constraints.get('maximum',max(values)),'SKU capacity.maximum')
        step=integer(constraints.get('step',1),'SKU capacity.step')
        if minimum<1 or maximum<minimum or step<1:raise ValueError('SKU 容量约束无效。')
        return max([0] + [v for v in values if minimum<=v<=min(limit,maximum) and (v-minimum)%step==0])
    minimum = integer(constraints.get('minimum'),'SKU capacity.minimum')
    maximum = integer(constraints.get('maximum'),'SKU capacity.maximum')
    step = integer(constraints.get('step'),'SKU capacity.step')
    if minimum < 1 or maximum < minimum or step < 1: raise ValueError('SKU 容量约束无效。')
    limit = min(limit, maximum)
    return minimum + ((limit-minimum)//step)*step if limit >= minimum else 0


def allocate(rows):
    """容量单位分配：独立区域用满；共享池按合法容量分配，不重复计数。"""
    values = [0]*len(rows)
    for pool in dict.fromkeys(row['pool'] for row in rows):
        indexes = [i for i, row in enumerate(rows) if row['pool'] == pool]
        budget = min(integer(rows[i]['remaining']) for i in indexes)
        # The common image model SKU has min=1/step=1. Water filling avoids a
        # quadratic allocation at high quota tiers while using all legal capacity.
        capacities=[rows[i].get('constraints') or {k:rows[i][k] for k in ('minimum','maximum','step')} for i in indexes]
        if all(not c.get('allowedValues') and c.get('minimum')==1 and c.get('step')==1 for c in capacities):
            limits={i:integer(rows[i]['maximum']) for i in indexes}
            active=[i for i in indexes if limits[i]>0]
            while active and budget:
                share=max(1,budget//len(active))
                for i in active:
                    amount=min(share,limits[i]-values[i],budget)
                    values[i]+=amount;budget-=amount
                active=[i for i in active if values[i]<limits[i]]
            continue
        # Sparse bounded allocation maximizes total capacity; for each total keep
        # the spread with more nonzero regions, then the more balanced spread.
        states = {0: []}
        for i in indexes:
            row = rows[i]
            constraints = row.get('constraints') or {k:row[k] for k in ('minimum','maximum','step')}
            ceiling = min(budget, integer(row['maximum']))
            if constraints.get('allowedValues'):
                choices = sorted({0} | {integer(v) for v in constraints['allowedValues'] if 0 < v <= ceiling and allowed_capacity(v,constraints)==v})
            else:
                lo, step = integer(constraints.get('minimum')), integer(constraints.get('step'))
                allowed_capacity(ceiling, constraints)
                choices = [0] + list(range(lo, ceiling+1, step))
            following = {}
            for total, previous in states.items():
                for capacity in choices:
                    updated = total + capacity
                    if updated > budget: break
                    candidate = previous + [capacity]
                    score = lambda v:(sum(n > 0 for n in v), -sum(n*n for n in v))
                    if updated not in following or score(candidate) > score(following[updated]): following[updated] = candidate
            states = following
        best = states[max(states)]
        for i, capacity in zip(indexes, best): values[i] = capacity
    return values


def same_model(deployment, name, sku=None):
    model = deployment.get('properties', {}).get('model', {})
    return model.get('name') == name and model.get('format') == 'OpenAI' and (sku is None or deployment.get('sku', {}).get('name') == sku)


def quota_pool(scope, region, zones):
    # Auto plans each location; writes re-read live quota, without assuming a
    # combined regional total is guaranteed or inferring the provider's scope.
    if scope in ('regional','auto'): return region
    if scope == 'subscription': return 'subscription'
    if scope == 'data-zone' and zones.get(region): return 'zone:' + zones[region]
    raise ValueError('必须确认真实配额范围；data-zone 还需配置每个区域所属的数据区。')


def minute_rate(limits,tokens=False):
    values = []
    for item in limits or []:
        key = str(item.get('key') or '').lower()
        if tokens and 'token' not in key:continue
        if not tokens and ('token' in key or (key and 'request' not in key)):continue
        count, period = item.get('count'), item.get('renewalPeriod')
        if not isinstance(count,bool) and not isinstance(period,bool) and isinstance(count, (int,float)) and isinstance(period, (int,float)) and math.isfinite(count) and math.isfinite(period) and count >= 0 and period > 0:
            values.append(count*60/period)
    return min(values) if values else None


def rpm(limits):return minute_rate(limits)


def tpm(limits):return minute_rate(limits,tokens=True)


def render_name(template, sid, region, kind, subscription_name='', index=1):
    code=re.search(r'(?<![A-Za-z0-9])A\d+(?:-\d+)?(?![A-Za-z0-9])',subscription_name,re.I)
    try: name = template.format(sub8=sid.replace('-','')[:8], subscription=sid, region=region,subcode=code.group().lower() if code else sid.replace('-','')[:8],index=index)
    except (KeyError, ValueError): raise ValueError('命名模板支持 {sub8}、{subscription}、{region}、{subcode}、{index:03d}。') from None
    pattern = r'[a-z0-9][a-z0-9-]{1,62}[a-z0-9]' if kind == 'account' else r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
    if not re.fullmatch(pattern,name): raise ValueError(f'{kind} 命名无效：请使用合法字母、数字及连字符。')
    return name


def granted(assignments, scope, principal):
    for row in assignments:
        p = row.get('properties', {})
        above = p.get('scope','').lower().rstrip('/')
        if p.get('principalId','').lower() != principal.lower() or p.get('condition'): continue
        if above != scope.lower() and above != '' and not above.startswith('/providers/microsoft.management/managementgroups/'): continue
        if p.get('roleDefinitionId','').split('/')[-1].lower() in (OWNER, CONTRIBUTOR): return True
    return False


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value, private=False):
    target = Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    # Do not overwrite any previously captured secret or execution record.
    with target.open('x', encoding='utf-8') as stream:
        if private and os.name != 'nt': os.chmod(target,0o600)
        json.dump(value,stream,ensure_ascii=False,indent=2)


def save_progress(path, value):
    """Only update the current run's exclusively reserved result file."""
    target=Path(path);temporary=target.with_name(target.name+'.tmp')
    with temporary.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
    os.replace(temporary,target)


def credential(config, mode, credential_file=None):
    from azure.identity import AzureCliCredential, ClientSecretCredential
    tenant = str(UUID(config['tenant_id']))
    if mode == 'admin': return AzureCliCredential(tenant_id=tenant)
    values = read_json(credential_file) if credential_file else {'tenant_id':os.environ.get('AZURE_TENANT_ID'), 'client_id':os.environ.get('AZURE_CLIENT_ID'), 'client_secret':os.environ.get('AZURE_CLIENT_SECRET')}
    if values.get('tenant_id') != tenant or not values.get('client_id') or not values.get('client_secret'): raise ValueError('应用凭据缺失或租户不匹配。')
    return ClientSecretCredential(tenant,str(UUID(values['client_id'])),values['client_secret'],authority='https://login.microsoftonline.com')


def subscriptions(api, config):
    tenant = str(UUID(config['tenant_id']))
    rows = api.all('/subscriptions',{'api-version':'2022-12-01'})
    visible = [r for r in rows if r.get('tenantId','').lower() == tenant and r.get('state') == 'Enabled']
    selected = config.get('subscription_ids', 'all')
    if selected != 'all':
        if not isinstance(selected,list) or not selected: raise ValueError('subscription_ids 必须是 all 或非空订阅 ID 列表。')
        selected = {str(UUID(s)) for s in selected}
        if not selected <= {r['subscriptionId'] for r in visible}: raise ValueError('所选订阅不可访问、未启用或不属于配置租户。')
        visible = [r for r in visible if r['subscriptionId'] in selected]
    if not visible: raise ValueError('当前身份没有可访问的本租户启用订阅。应用身份只能看到已授权订阅。')
    return sorted(visible,key=lambda r:r.get('displayName','').lower())


def check_config(config):
    str(UUID(config['tenant_id']))
    selected=config.get('subscription_ids','all')
    if selected != 'all':
        if not isinstance(selected,list) or not selected:
            raise ValueError('subscription_ids 必须是 "all" 或非空列表；单个订阅也要写成 ["订阅ID"]，不能直接填写字符串。')
        try:
            for sid in selected:
                if not isinstance(sid,str): raise ValueError()
                str(UUID(sid))
        except ValueError:
            raise ValueError('subscription_ids 列表中每一项都必须是有效的订阅 UUID 字符串。') from None
    if config.get('model') not in MODELS: raise ValueError('请选择支持的生图或文本模型；可用性仍以 Azure 模型目录为准。')
    if config.get('sku') not in ('GlobalStandard','DataZoneStandard'): raise ValueError('仅支持 GlobalStandard / DataZoneStandard。')
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,40}',config.get('model_version','')): raise ValueError('须明确填写模型版本，不自动选取或升级版本。')
    for key in ('resource_group_template','account_template','deployment_name'):
        if not config.get(key): raise ValueError('须由客户确认并填写命名规则。')
    if config.get('quota_scope','unknown') not in ('unknown','auto','regional','subscription','data-zone'): raise ValueError('quota_scope 无效。')
    if config.get('quota_scope') == 'subscription' and config['sku'] != 'GlobalStandard': raise ValueError('订阅全局共享池仅适用于 GlobalStandard。')
    if config.get('quota_scope') == 'data-zone' and config['sku'] != 'DataZoneStandard': raise ValueError('数据区共享池仅适用于 DataZoneStandard。')


def model_metadata(api, sid, region, config):
    path = f'/subscriptions/{sid}/providers/Microsoft.CognitiveServices/locations/{region}'
    catalog = api.all(path+'/models')
    matches = []
    for raw in catalog:
        model = raw.get('model') or raw
        if (model.get('format'),model.get('name'),model.get('version')) == ('OpenAI',config['model'],config['model_version']):
            matches.extend(s for s in model.get('skus',[]) if s.get('name') == config['sku'])
    matches=list({json.dumps(s,sort_keys=True):s for s in matches}.values())
    if len(matches) != 1: raise ValueError('区域模型/SKU 元数据缺失或不一致，不能确认容量。')
    sku = matches[0]
    usages = api.all(path+'/usages', {'api-version':'2024-10-01'})
    quota = [u for u in usages if u.get('name',{}).get('value') == sku.get('usageName')]
    if not sku.get('usageName') or len(quota) != 1 or quota[0].get('unit') != 'Count': raise ValueError('无法唯一匹配 Count 配额单位，不能猜测最大容量。')
    remaining = max(0,integer(quota[0].get('limit'),'配额上限 limit')-integer(quota[0].get('currentValue'),'已用配额 currentValue'))
    constraints = dict(sku.get('capacity') or {})
    # Standard SKUs allocate integer capacity units; default is not a minimum.
    # Preserve explicit constraints and never infer a missing maximum or quota.
    if config['sku'] in ('GlobalStandard','DataZoneStandard') and constraints:
        constraints.setdefault('minimum',1);constraints.setdefault('step',1)
    unit_rpm=rpm(sku.get('rateLimits'));unit_tpm=tpm(sku.get('rateLimits'))
    image=config['model'].startswith('gpt-image-');target=2 if image else 1000000
    unit=unit_rpm if image else unit_tpm;label='RPM' if image else 'TPM'
    if unit is None or unit<=0 or not math.isfinite(unit):raise ValueError('Azure 未返回有效的 '+label+' 与容量换算关系，无法按 Tier 1 目标安排创建。')
    maximum = allowed_capacity(min(remaining,math.floor(target/unit)),constraints)
    return dict(usage_name=sku['usageName'],remaining=remaining,maximum=maximum,constraints=constraints,unit_rpm=unit_rpm,unit_tpm=unit_tpm,**{'target_rpm' if image else 'target_tpm':target})


def scan(api, config, on_progress=None):
    check_config(config)
    report = {'config':config,'tenant_id':config['tenant_id'],'rows':[],'errors':[], 'created_at':time.time()}
    subs = subscriptions(api,config)
    for index, sub in enumerate(subs,1):
        if on_progress:on_progress(index-1,len(subs),'扫描订阅：'+sub.get('displayName',''))
        sid = sub['subscriptionId']; root = '/subscriptions/'+sid
        if not getattr(api,'quiet',False):print(f'[{index}/{len(subs)}] 扫描订阅：{sub.get("displayName",sid)}',flush=True)
        try:
            accounts = api.all(root+'/providers/Microsoft.CognitiveServices/accounts')
            inventory = []
            # Read every suitable account's deployments; any read failure stops this
            # subscription rather than assuming an empty inventory and duplicating.
            for account in accounts:
                if account.get('kind') in ('AIServices','OpenAI'):
                    for deployment in api.all(account['id']+'/deployments'):
                        if same_model(deployment, config['model']): inventory.append((account,deployment))
            versions=config.get('regional_versions',{}).get(sid,{})
            capacities=[];capacity_error=''
            try:
                if versions:
                    for version in dict.fromkeys(versions.values()):
                        found=api.all(root+'/providers/Microsoft.CognitiveServices/modelCapacities', {'api-version':VERSION,'modelFormat':'OpenAI','modelName':config['model'],'modelVersion':version})
                        capacities.extend(r for r in found if versions.get(r.get('location','').replace(' ','').lower())==version)
                elif not config.get('use_default'):capacities=api.all(root+'/providers/Microsoft.CognitiveServices/modelCapacities', {'api-version':VERSION,'modelFormat':'OpenAI','modelName':config['model'],'modelVersion':config['model_version']})
            except (ValueError,RuntimeError) as error:capacity_error=str(error)
            regions = {r['location'].replace(' ','').lower(): r for r in capacities if r.get('properties',{}).get('skuName') == config['sku']}
            requested = config.get('regions','auto')
            if requested != 'auto':
                if not isinstance(requested,list) or not requested: raise ValueError('regions 必须是 auto 或非空区域列表。')
                regions = {r:regions.get(r) for r in dict.fromkeys(requested)}
            else:
                for account,_ in inventory:regions.setdefault(account['location'].replace(' ','').lower(),None)
            if not regions: raise ValueError(capacity_error or '该订阅当前没有匹配模型版本/类型的可用区域。')
            pending = []
            for region_index, (region, raw_capacity) in enumerate(regions.items() if requested != 'auto' else sorted(regions.items()),1):
                region_index=config.get('region_indexes',{}).get(sid,{}).get(region,region_index)
                row = dict(subscription_id=sid, subscription=sub.get('displayName',sid), region=region, region_index=region_index, model=config['model'], version=versions.get(region,config['model_version']),sku=config['sku'])
                report['rows'].append(row)
                try:
                    existing = [(a,d) for a,d in inventory if a['location'].replace(' ','').lower() == region]
                    if existing:
                        if any(a.get('properties',{}).get('provisioningState')!='Succeeded' or d.get('properties',{}).get('provisioningState')!='Succeeded' for a,d in existing):
                            raise ValueError('已有同模型部署或账户尚未成功；请先检查失败/进行中的配置，不重复创建。')
                        row.update(status='existing', existing=[{'account_id':a['id'],'deployment':d['name'],'version':d.get('properties',{}).get('model',{}).get('version'),'sku':d.get('sku',{}).get('name'),'capacity':d.get('sku',{}).get('capacity'),'rpm':rpm(d.get('properties',{}).get('rateLimits')),'tpm':tpm(d.get('properties',{}).get('rateLimits'))} for a,d in existing])
                        row['message']='已有同模型部署，保留实际版本、部署类型和容量；不新建、不扩容。'
                        continue
                    if raw_capacity is None and not capacity_error:
                        report['rows'].pop()
                        report['errors'].append({'subscription_id':sid,'region':region,'message':'此区域未返回匹配模型容量；未计划创建。'})
                        continue
                    if config.get('use_default') and region not in versions:raise ValueError('此区域没有可确认的 Azure 默认版本；未安排创建。')
                    if raw_capacity is None:raise ValueError(capacity_error or '此区域未返回匹配模型容量；未计划创建。')
                    row.update(model_metadata(api,sid,region,{**config,'model_version':row['version']}))
                    row['maximum'] = allowed_capacity(min(row['maximum'],integer(raw_capacity['properties'].get('availableCapacity'),'区域可用容量 availableCapacity')),row['constraints'])
                    if not row['maximum']:raise ValueError('未找到此区域可复用的同模型部署，且剩余配额、可用容量或目标内合法容量为 0；不会新建。')
                    group = render_name(config['resource_group_template'],sid,region,'group',sub.get('displayName',''),region_index)
                    name = render_name(config['account_template'],sid,region,'account',sub.get('displayName',''),region_index)
                    desired = root+'/resourceGroups/'+group+'/providers/Microsoft.CognitiveServices/accounts/'+name
                    candidates = [a for a in accounts if a.get('kind') in ('AIServices','OpenAI') and a.get('location','').replace(' ','').lower() == region]
                    named = [a for a in candidates if a['id'].lower() == desired.lower()]
                    if named: candidates=named
                    if len(candidates)>1: raise ValueError('区域已有多个 Foundry/OpenAI 账户；请用命名规则明确选中其中一个，避免创建重复账户。')
                    if candidates: desired=candidates[0]['id'];group=desired.split('/')[4]
                    row.update(account_id=desired,resource_group=group,new_account=not candidates,deployment=render_name(config['deployment_name'],sid,region,'deployment',sub.get('displayName',''),region_index))
                    if config.get('quota_scope','unknown') == 'unknown':
                        row.update(status='blocked',message='当前是只读检查模式；切换为自动核对后可生成 Tier 1 创建清单。')
                        continue
                    row['pool'] = row['usage_name']+':'+quota_pool(config['quota_scope'],region,config.get('data_zones',{}))
                    row['status']='planned';pending.append(row)
                except (ValueError,RuntimeError) as error: row.update(status='blocked',message=str(error))
            for row, capacity in zip(pending,allocate(pending)):
                row.update(capacity=capacity,estimated_rpm=capacity*row['unit_rpm'] if row['unit_rpm'] is not None else None,estimated_tpm=capacity*row['unit_tpm'] if row['unit_tpm'] is not None else None)
                if not capacity: row.update(status='blocked',message='合法剩余额度不足；不会创建零容量部署。')
        except (ValueError,RuntimeError) as error:
            report['errors'].append({'subscription_id':sid,'message':str(error)})
        if on_progress:on_progress(index,len(subs),'订阅检查完成：'+sub.get('displayName',''))
    return report


def wait_ready(api, path, timeout=900):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        value = api.get(path)
        state = value.get('properties',{}).get('provisioningState')
        if state == 'Succeeded': return value
        if state in ('Failed','Canceled','Deleted'): raise RuntimeError('Azure 配置操作失败；重新扫描后检查失败资源，不会自动删除。')
        getattr(api,'pause',time.sleep)(5)
    raise RuntimeError('等待 Azure 操作超时；结果可能已创建，请重新扫描确认，不要直接重试写入。')


def account_result(account, deployment):
    props=account.get('properties',{})
    dp=deployment.get('properties',{})
    return {'account_id':account['id'],'endpoint':props.get('endpoint'),'endpoints':props.get('endpoints',{}),'deployment':deployment.get('name'),'model':dp.get('model'), 'capacity':deployment.get('sku',{}).get('capacity'),'rpm':rpm(dp.get('rateLimits')),'tpm':tpm(dp.get('rateLimits')),'rate_limits':dp.get('rateLimits',[])}


def execute(api, confirmed, on_progress=None):
    # Never trust an editable plan's resource IDs or capacity. Regenerate the
    # entire inventory, and stop if the reviewed rows no longer match.
    fresh = scan(api,confirmed['config'])
    if fresh['rows'] != confirmed['rows'] or fresh['errors'] != confirmed['errors']:
        raise ValueError('Azure 状态或配额已变化；请重新扫描并确认新清单。未执行创建。')
    results = []
    report={'tenant_id':fresh['tenant_id'],'rows':results,'errors':fresh['errors']}
    for index, row in enumerate(fresh['rows'],1):
        label={'planned':'准备创建','existing':'已有部署','blocked':'需要处理'}.get(row['status'],row['status'])
        if not getattr(api,'quiet',False):print(f'[{index}/{len(fresh["rows"])}] {row["subscription"]} / {row["region"]}：{label}',flush=True)
        item = {**row};results.append(item)
        try:
            if row['status'] == 'existing':
                item['outputs']=[]
                for d in row['existing']:
                    account=api.get(d['account_id']);deployed=api.get(d['account_id']+'/deployments/'+d['deployment'])
                    if account.get('properties',{}).get('provisioningState')!='Succeeded' or deployed.get('properties',{}).get('provisioningState')!='Succeeded' or not same_model(deployed,row['model'],d['sku']):raise ValueError('已有账户/部署状态已改变；请重新扫描。')
                    item['outputs'].append(account_result(account,deployed))
                continue
            if row['status'] != 'planned': continue
            aid=row['account_id'];did=aid+'/deployments/'+row['deployment']
            if api.optional(did) is not None: raise ValueError('目标部署名称已经占用；不覆盖已有部署。请重新扫描。')
            remaining=model_metadata(api,row['subscription_id'],row['region'],{**fresh['config'],'model_version':row['version']})
            if row['capacity']>remaining['maximum']:raise ValueError('当前余额低于清单目标；此项未创建资源，请重新检查。')
            if row['new_account']:
                if api.optional(aid) is not None: raise ValueError('目标账户已经存在；不覆盖，须重新扫描。')
                group='/subscriptions/'+row['subscription_id']+'/resourceGroups/'+row['resource_group']
                if api.optional(group,'2022-09-01') is None:
                    api.put(group,{'location':row['region']},'2022-09-01')
                api.put(aid,{'location':row['region'],'kind':'AIServices','sku':{'name':'S0'},'properties':{'customSubDomainName':aid.split('/')[-1]} })
                wait_ready(api,aid)
            else:
                account=api.get(aid)
                if account.get('location','').replace(' ','').lower()!=row['region'] or account.get('kind') not in ('AIServices','OpenAI'): raise ValueError('现有账户配置已改变；不执行。')
                if account.get('properties',{}).get('provisioningState')!='Succeeded': raise ValueError('现有账户尚未配置成功。')
            # Check quota again after long-running account creation. The planned
            # capacity stays fixed; shared quota is also checked conservatively.
            remaining=model_metadata(api,row['subscription_id'],row['region'],{**fresh['config'],'model_version':row['version']})
            if row['capacity']>remaining['maximum']: raise ValueError('当前剩余合法容量低于确认值；未创建部署，请重扫。')
            api.put(did,{'sku':{'name':row['sku'],'capacity':row['capacity']},'properties':{'model':{'format':'OpenAI','name':row['model'],'version':row['version']},'versionUpgradeOption':'NoAutoUpgrade'}})
            deployed=wait_ready(api,did)
            if not same_model(deployed,row['model'],row['sku']) or deployed.get('sku',{}).get('capacity')!=row['capacity'] or deployed.get('properties',{}).get('model',{}).get('version')!=row['version']: raise ValueError('Azure 返回部署与确认配置不一致，需人工检查。')
            item.update(status='created',outputs=[account_result(api.get(aid),deployed)])
        except (ValueError,RuntimeError) as error: item.update(status='failed',message=str(error))
        finally:
            if on_progress:on_progress(report)
    return report


def fetch_keys(api, report):
    accounts={r['account_id'] for row in report['rows'] for r in row.get('outputs',[])}
    results=[]
    for aid in sorted(accounts):
        try:
            account=api.get(aid)
            if account.get('properties',{}).get('disableLocalAuth'): raise ValueError('此账户禁用 Key 认证；不会擅自启用。')
            keys=api.call('POST',aid+'/listKeys',params={'api-version':VERSION})
            if not keys.get('key1'): raise ValueError('Azure 未返回 Key。')
            results.append({'account_id':aid,'endpoint':account.get('properties',{}).get('endpoint'),'endpoints':account.get('properties',{}).get('endpoints',{}),'key':keys['key1']})
        except (ValueError,RuntimeError) as error: results.append({'account_id':aid,'error':str(error)})
    return results


def environment_report(mode, config=None, credential_file=None, online=False):
    """只读环境诊断，不安装软件、不自动登录，也不输出身份或凭据。"""
    from importlib.metadata import version, PackageNotFoundError
    import shutil
    import subprocess
    report={'checks':[],'online_verified':False}
    def record(name,status,detail):report['checks'].append({'name':name,'status':status,'detail':detail})
    record('Python','ok' if sys.version_info>=(3,10) else 'failed','需要 Python 3.10 或更新版本。')
    for package in ('azure-identity','requests'):
        try:record(package,'ok','已安装 '+version(package))
        except PackageNotFoundError:record(package,'failed','未安装；请在当前虚拟环境运行 python -m pip install -r requirements.txt。')
    if mode=='admin':
        executable=shutil.which('az')
        if not executable:record('Azure CLI','failed','未找到 az。请按 README 安装 Azure CLI 并重新打开终端；浏览器已登录不等于 CLI 已登录。')
        else:
            record('Azure CLI','ok','已找到 az。')
            try:
                result=subprocess.run([executable,'cloud','show','--query','name','-o','tsv'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
                if result.returncode or result.stdout.strip()!='AzureCloud':
                    record('Azure 云环境','failed','CLI 未配置 Azure 公有云；确认后运行 az cloud set --name AzureCloud，再登录客户租户。')
                else:record('Azure 云环境','ok','Azure 公有云。')
            except (OSError,subprocess.TimeoutExpired):record('Azure 云环境','failed','Azure CLI 无法运行或超时。请先在当前终端检查 az version。')
    else:record('Azure CLI','not_required','应用身份直接使用 Python SDK，不需要安装 CLI 或 az login。')
    if not online:return report
    if any(c['status']=='failed' for c in report['checks']):return report
    if not config:
        record('客户配置','failed','未找到配置；先复制 config.example.json 为 config.json，填写客户租户与命名规则。');return report
    try:check_config(config)
    except ValueError as error:
        record('客户配置','failed',str(error));return report
    except KeyError:
        record('客户配置','failed','配置缺失或无效。请填写客户租户 ID、精确模型版本、部署类型与命名规则。');return report
    try:
        api=Azure(credential(config,mode,credential_file))
        visible=subscriptions(api,config)
        report['visible_subscriptions']=len(visible);report['online_verified']=True
        record('登录及订阅读取','ok',f'只读验证通过，可访问所选租户的 {len(visible)} 个启用订阅。此结果不证明创建、授权或 Key 读取权限。')
    except Exception:
        detail='CLI 登录无效、已过期或所选范围不可访问。请在相同终端/环境完成 az login --tenant 客户租户ID；需要 MFA 时由客户本人完成。' if mode=='admin' else '应用凭据缺失/失效、租户不匹配或订阅未授权。请核对私密凭据文件及订阅 RBAC；无需 az login。'
        record('登录及订阅读取','failed',detail)
    return report


def main():
    parser=argparse.ArgumentParser(description='Azure 图像模型批量部署：默认扫描；执行前重新核对。',add_help=False)
    parser._positionals.title='操作命令';parser._optionals.title='选项'
    parser.add_argument('-h','--help',action='help',help='显示中文帮助并退出')
    parser.add_argument('command',choices=('doctor','scan','deploy','setup-app'),help='doctor：环境检查；scan：扫描；deploy：部署；setup-app：检查/配置应用授权')
    parser.add_argument('--offline',action='store_true',help='doctor 只检查本地环境，不验证登录或访问 Azure')
    parser.add_argument('--config',default='config.json',help='客户配置文件')
    parser.add_argument('--auth',choices=('admin','app'),default='admin',help='管理员登录或应用身份')
    parser.add_argument('--credentials',help='应用凭据文件（不放入 Git）')
    parser.add_argument('--plan',default='output/plan.json',help='扫描清单')
    parser.add_argument('--output',default='output/result.json',help='结果文件；不覆盖已存在文件')
    parser.add_argument('--execute',action='store_true',help='明确执行创建 / 应用授权；无此参数不写入 Azure')
    parser.add_argument('--include-keys',action='store_true',help='读取账户 Key，单独保存在私密文件')
    parser.add_argument('--secret-output',default='output/keys.private.json',help='凭据/Key 的独立私密输出文件')
    parser.add_argument('--app-name',help='客户确认的应用名称')
    parser.add_argument('--new-secret',action='store_true',help='为已有应用增加一条新密钥（保留旧密钥）')
    parser.add_argument('--secret-days',type=int,default=90,help='应用密钥有效期，默认90天')
    args=parser.parse_args()
    try:
        if args.command=='doctor':
            config=read_json(args.config) if Path(args.config).is_file() else None
            report=environment_report(args.auth,config,args.credentials,online=not args.offline)
            labels={'ok':'通过','failed':'未通过','not_required':'无需'}
            for row in report['checks']:print(f'[{labels[row["status"]]}] {row["name"]}：{row["detail"]}')
            if args.offline:print('仅本地环境检查完成；尚未验证 Azure 登录和权限。')
            return 1 if any(c['status']=='failed' for c in report['checks']) else 0
        config=read_json(args.config);check_config(config)
        output=Path(args.plan if args.command=='scan' else args.output)
        if output.exists():raise ValueError('输出文件已存在，请使用新文件名，避免覆盖已确认清单、凭据与记录。')
        if args.include_keys or args.command=='setup-app':
            secret=Path(args.secret_output)
            if secret.resolve()==output.resolve() or secret.resolve() in {Path(args.config).resolve(),Path(args.plan).resolve()}:raise ValueError('私密文件必须与配置、清单和结果文件分开。')
            if secret.exists():raise ValueError('私密文件已经存在，请使用新的 --secret-output。')
        local=environment_report(args.auth,online=False)
        failures=[c['detail'] for c in local['checks'] if c['status']=='failed']
        if failures:raise ValueError(' '.join(failures))
        api=Azure(credential(config,args.auth,args.credentials))
        if args.command=='setup-app':
            if args.auth!='admin': raise ValueError('应用初始化必须由有权限的管理员执行。')
            from app_setup import setup
            write_json(output,{'status':'开始应用检查/配置','tenant_id':config['tenant_id']})
            result=setup(api,Azure(api.credential,GRAPH),config,args.app_name,args.execute,args.new_secret,args.secret_days,args.secret_output,lambda value:save_progress(output,value))
            save_progress(output,result)
        elif args.command=='scan':
            if Path(args.plan).exists(): raise ValueError('清单文件已存在，请指定新 --plan 文件名，保留已确认清单。')
            result=scan(api,config);write_json(args.plan,result)
        else:
            if not args.execute: raise ValueError('部署需要 --execute；请先运行 scan 并确认清单。')
            confirmed=read_json(args.plan)
            if confirmed['config']!=config: raise ValueError('配置与扫描清单不同；请重新扫描。')
            if not any(row.get('status') in ('planned','existing') for row in confirmed['rows']): raise ValueError('清单中没有可创建或可复用的部署。')
            if Path(args.output).exists() or args.include_keys and Path(args.secret_output).exists(): raise ValueError('输出文件已经存在；请换新文件名，避免覆盖凭据与执行记录。')
            write_json(output,{'status':'开始重新核对清单','tenant_id':config['tenant_id']})
            result=execute(api,confirmed,lambda value:save_progress(output,value));save_progress(output,result)
            if args.include_keys:
                keys=fetch_keys(api,result);write_json(args.secret_output,keys,private=True)
                if any('error' in item for item in keys):result.setdefault('errors',[]).append({'message':'部分账户 Key 读取失败，原因在私密结果文件中。'});save_progress(output,result)
        rows=result.get('rows',[])
        if args.command=='setup-app':
            subs=result.get('subscriptions',[])
            print(f'应用{"配置" if result["executed"] else "检查"}结束。已有授权 {sum(s["status"]=="existing" for s in subs)}，新授权 {sum(s["status"]=="assigned" for s in subs)}，失败 {sum(s["status"]=="failed" for s in subs)}。请查看结果文件。')
        else:print(f'处理结束。创建成功 {sum(r.get("status")=="created" for r in rows)}，已有 {sum(r.get("status")=="existing" for r in rows)}，阻塞/失败 {sum(r.get("status") in ("blocked","failed") for r in rows)}。请查看中文说明与结果文件。')
        return 2 if result.get('errors') or any(r.get('status') in ('blocked','failed') for r in rows) else 0
    except KeyboardInterrupt:
        print('操作已中断；Azure 已接收的请求可能继续执行。再次执行前请重新扫描。',file=sys.stderr);return 130
    except Exception as error:
        if isinstance(error,FileNotFoundError):print('未完成：配置、清单或凭据文件不存在。请先按 README 复制示例、填写配置，并核对文件路径。',file=sys.stderr)
        elif isinstance(error,OSError):print('未完成：本地文件读取/保存失败。请检查目录权限及剩余空间；若已发起 Azure 写入，先重扫确认状态。',file=sys.stderr)
        elif isinstance(error,(ValueError,RuntimeError,KeyError)):print(f'未完成：{error}',file=sys.stderr)
        else:print('未完成：登录或本地环境异常。请先运行 doctor 检查配置、依赖、登录及订阅范围。',file=sys.stderr)
        return 1


if __name__=='__main__': sys.exit(main())
