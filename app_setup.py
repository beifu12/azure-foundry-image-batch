"""客户管理员显式初始化应用与订阅 Contributor；不会删除旧密钥或角色。"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL
from image_batch import CONTRIBUTOR, granted, subscriptions


def setup(arm, graph, config, name, execute, new_secret, days, secret_output, on_progress=None):
    if not name or not name.strip() or len(name)>100:
        raise ValueError('请用 --app-name 指定客户确认的应用名称。')
    if not 7<=days<=365:raise ValueError('应用密钥有效期须为 7–365 天。')
    apps=graph.all('/v1.0/applications',{'$select':'id,appId,displayName,signInAudience','$top':999})
    matches=[a for a in apps if a.get('displayName','').strip().casefold()==name.strip().casefold()]
    if len(matches)>1:raise ValueError('存在多个同名应用，不能自动选择。请使用唯一应用名称。')
    app=matches[0] if matches else None
    if app and app.get('signInAudience')!='AzureADMyOrg':raise ValueError('已有同名应用不是单租户应用；请使用新的唯一名称，避免改动现有应用。')
    selected=subscriptions(arm,config)
    result={'executed':False,'tenant_id':config['tenant_id'],'application_action':'reuse' if app else 'create','application':app,'subscriptions':[], 'errors':[]}
    principal=None
    if app:
        principals=graph.all('/v1.0/servicePrincipals',{'$filter':f"appId eq '{str(UUID(app['appId']))}'",'$select':'id,appId,appOwnerOrganizationId'})
        if len(principals)>1:raise ValueError('企业应用不唯一，已停止。')
        if principals:
            sp=principals[0]
            if sp.get('appOwnerOrganizationId','').lower()!=config['tenant_id'].lower():raise ValueError('企业应用不属于客户租户。')
            principal=str(UUID(sp['id']))
    for sub in selected:
        scope='/subscriptions/'+sub['subscriptionId']
        row={'id':sub['subscriptionId'],'name':sub.get('displayName')};result['subscriptions'].append(row)
        try:
            assignments=arm.all(scope+'/providers/Microsoft.Authorization/roleAssignments',{'api-version':'2022-04-01','$filter':f"principalId eq '{principal}'"}) if principal else []
            row['status']='existing' if principal and granted(assignments,scope,principal) else 'missing'
        except (ValueError,RuntimeError) as error:
            row.update(status='failed',message=str(error));result['errors'].append({'subscription_id':sub['subscriptionId'],'message':str(error)})
    if not execute:return result
    need_secret=not app or new_secret
    if need_secret:
        if not secret_output or Path(secret_output).exists():raise ValueError('私密凭据输出文件已存在或未指定；不会创建密钥。')
        # Confirm that the destination is writable before creating a one-time secret.
        target=Path(secret_output);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf-8') as stream:stream.write('{}')
        if os.name!='nt':os.chmod(target,0o600)
    if not app:
        app=graph.call('POST','/v1.0/applications',{'displayName':name.strip(),'signInAudience':'AzureADMyOrg'})
        result['application']={'id':app['id'],'appId':app['appId'],'displayName':name.strip()}
        if on_progress:on_progress(result)
    if not principal:
        # For a newly created registration, allow one Graph eventual-consistency
        # failure to remain a reported partial setup; do not repeat POST blindly.
        sp=graph.call('POST','/v1.0/servicePrincipals',{'appId':app['appId']})
        principal=str(UUID(sp['id']))
    result['principal_id']=principal
    if on_progress:on_progress(result)
    if need_secret:
        secret=graph.call('POST',f"/v1.0/applications/{str(UUID(app['id']))}/addPassword",{'passwordCredential':{'displayName':'图像模型批量部署','endDateTime':(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()}})
        if not secret.get('secretText'):raise ValueError('Microsoft 未返回密钥值，请核对应用密码状态，不要直接重复生成。')
        private={'tenant_id':config['tenant_id'],'client_id':app['appId'],'application_object_id':app['id'],'principal_id':principal,'key_id':secret['keyId'],'client_secret':secret['secretText'],'expires':secret.get('endDateTime')}
        # The file was created exclusively above and contains no prior credentials.
        Path(secret_output).write_text(json.dumps(private,ensure_ascii=False,indent=2),encoding='utf-8')
        result['credential_saved']=True
        if on_progress:on_progress(result)
    for sub in result['subscriptions']:
        scope='/subscriptions/'+sub['id']
        if sub['status']=='failed':continue
        try:
            # Re-read effective role assignments immediately before each grant.
            rows=arm.all(scope+'/providers/Microsoft.Authorization/roleAssignments',{'api-version':'2022-04-01','$filter':f"principalId eq '{principal}'"})
            if granted(rows,scope,principal):sub['status']='existing';continue
            assignment=str(uuid5(NAMESPACE_URL,scope.lower()+':'+principal+':'+CONTRIBUTOR))
            path=scope+'/providers/Microsoft.Authorization/roleAssignments/'+assignment
            if arm.optional(path,'2022-04-01') is not None:raise ValueError('目标角色分配 ID 已被占用；不会覆盖现有或带条件的授权。')
            arm.put(path,{'properties':{'roleDefinitionId':scope+'/providers/Microsoft.Authorization/roleDefinitions/'+CONTRIBUTOR,'principalId':principal,'principalType':'ServicePrincipal'}},'2022-04-01')
            sub['status']='assigned'
        except (ValueError,RuntimeError) as error:
            sub.update(status='failed',message=str(error));result['errors'].append({'subscription_id':sub['id'],'message':str(error)})
        finally:
            if on_progress:on_progress(result)
    result['executed']=True
    return result
