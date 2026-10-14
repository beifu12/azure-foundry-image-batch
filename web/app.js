'use strict';
const $=id=>document.getElementById(id);
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const imageModels=['gpt-image-2.5-flare','gpt-image-2.5-sunburst','gpt-image-2'];
const textModels=['gpt-5.6-terra','gpt-5.6-luna','gpt-5.6-sol','gpt-6-sol','gpt-6-luna','gpt-6-astra','gpt-6.1-sol'];
const regionNames={eastus2:'East US 2',westus3:'West US 3',polandcentral:'Poland Central',swedencentral:'Sweden Central',uaenorth:'UAE North'};
let state={},selected=new Set(),draft=new Set(),subscriptionSignature='',reviewSignature='',resultSignature='',catalogSignature='',settingsChanged=false,settingsRevision=0,scanRevision=-1,redirectedLogin='';
const versionInputs=new Map();
for(const name of [...imageModels,...textModels]){
 const label=document.createElement('label');label.className='model-choice';
 label.innerHTML=`<input type="checkbox" value="${name}" ${name==='gpt-image-2'?'checked':''}><span>${name}<small>${imageModels.includes(name)?'生图模型':'文本模型'} · Azure 默认版本</small></span><input aria-label="${name} 版本" placeholder="精确版本" autocomplete="off" list="versions-${name}" hidden><datalist id="versions-${name}"></datalist>`;
 $('models').append(label);versionInputs.set(name,label.querySelector('input:not([type=checkbox])'));
}
for(const [code,name] of Object.entries(regionNames)){$('regions').insertAdjacentHTML('beforeend',`<label class="region-chip"><input type="checkbox" value="${code}" checked>${name}</label>`);}
function error(message){$('error').textContent=message;$('error').hidden=!message;}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,2200);}
async function api(path,data){
 const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'FoundryUI'},body:JSON.stringify(data??{})});
 if(!response.ok){let message='请求未完成，请稍后重试。';try{message=(await response.json()).error||message;}catch{}throw new Error(message);}
 return response;
}
async function action(path,data){error('');try{await api(path,data);await refresh();}catch(e){error(e.message);}}
function confirmAction(title,message){return new Promise(resolve=>{
 const dialog=$('confirm-dialog');$('confirm-title').textContent=title;$('confirm-message').textContent=message;
 const finish=value=>{dialog.close();resolve(value);};$('confirm-yes').onclick=()=>finish(true);$('confirm-no').onclick=()=>finish(false);dialog.oncancel=e=>{e.preventDefault();finish(false);};dialog.showModal();
});}
function showSubscriptions(){
 const query=$('subscription-search').value.toLowerCase();$('subscriptions').replaceChildren();
 for(const sub of state.subscriptions||[]){if(!`${sub.displayName} ${sub.subscriptionId}`.toLowerCase().includes(query))continue;
 const label=document.createElement('label');label.className='check-row';label.innerHTML=`<input type="checkbox" ${draft.has(sub.subscriptionId)?'checked':''}><span>${escapeHTML(sub.displayName)}<small>${escapeHTML(sub.subscriptionId)}</small></span>`;
 label.querySelector('input').onchange=e=>{e.target.checked?draft.add(sub.subscriptionId):draft.delete(sub.subscriptionId);updateAll();};$('subscriptions').append(label);}
 updateAll();
}
function updateAll(){const count=(state.subscriptions||[]).length;$('subscription-all').checked=count>0&&draft.size===count;$('subscription-all').indeterminate=draft.size>0&&draft.size<count;}
function closePicker(){$('subscription-popover').hidden=true;$('subscription-trigger').setAttribute('aria-expanded','false');}
$('subscription-trigger').onclick=()=>{if(!$('subscription-popover').hidden){closePicker();return;}draft=new Set(selected);$('subscription-search').value='';showSubscriptions();$('subscription-popover').hidden=false;$('subscription-trigger').setAttribute('aria-expanded','true');$('subscription-search').focus();};
$('subscription-search').oninput=showSubscriptions;
$('subscription-all').onchange=e=>{draft=e.target.checked?new Set((state.subscriptions||[]).map(s=>s.subscriptionId)):new Set();showSubscriptions();};
$('subscription-apply').onclick=()=>{selected=new Set(draft);settingsChanged=true;settingsRevision++;closePicker();render(state);};$('subscription-cancel').onclick=closePicker;
document.addEventListener('click',e=>{if(!e.target.closest('.picker'))closePicker();});document.addEventListener('keydown',e=>{if(e.key==='Escape')closePicker();});
$('settings-panel').addEventListener('input',e=>{if(e.target.closest('.popover'))return;settingsChanged=true;settingsRevision++;$('deploy').disabled=true;$('create-note').textContent='设置已变化，请重新检查。';});
$('quota').onchange=()=>{$('zone-label').hidden=$('quota').value!=='data-zone';};
$('manual-versions').onchange=()=>{for(const input of versionInputs.values())input.hidden=!$('manual-versions').checked;};
function form(){const models=[...$('models').querySelectorAll('.model-choice')].filter(l=>l.querySelector('input[type=checkbox]').checked).map(l=>({name:l.querySelector('input[type=checkbox]').value,version:l.querySelector('input:not([type=checkbox])').value.trim()}));
 const regions=[...$('regions').querySelectorAll('input:checked')].map(i=>i.value);regions.push(...$('extra-regions').value.split(',').map(v=>v.trim().toLowerCase()).filter(Boolean));
 if(!selected.size)throw new Error('请至少勾选一个订阅。');if(!models.length)throw new Error('请至少选择一个模型。');if($('manual-versions').checked&&models.some(m=>!m.version))throw new Error('手动版本模式下，请填写所选模型的精确版本。');if(!regions.length)throw new Error('请至少选择一个区域。');if(!$('manual-versions').checked)for(const model of models)model.version='';
 let zones={};if($('quota').value==='data-zone'){try{zones=JSON.parse($('zones').value);}catch{throw new Error('请填写合法的数据区映射 JSON。');}}
 return {subscription_ids:[...selected],models,regions,auto_regions:$('auto-regions').checked,sku:$('sku').value,quota_scope:$('quota').value,data_zones:zones,resource_group_template:$('group-template').value.trim(),account_template:$('account-template').value.trim(),project_template:$('project-template').value.trim()};
}
$('login').onclick=()=>action('login',{tenant_id:$('tenant').value.trim()});
$('logout').onclick=async()=>{if(await confirmAction('退出客户账号','退出将清除当前页面的部署清单和密钥。正在执行的任务会停止后续步骤；Azure 已收到的操作不会撤销。')){await action('logout');selected.clear();settingsChanged=true;}};
$('copy-code').onclick=()=>copy($('login-code').textContent);
async function copy(value){try{await navigator.clipboard.writeText(value);toast('已复制');}catch{error('浏览器不允许自动复制，请选中文字后手动复制。');}}
$('catalog').onclick=()=>{const sub=[...selected][0],region=$('regions').querySelector('input:checked')?.value||$('extra-regions').value.split(',')[0].trim();if(!sub||!region)return error('请先勾选订阅和区域。');action('catalog',{subscription_id:sub,region});};
$('scan').onclick=()=>{try{const data=form();scanRevision=settingsRevision;action('scan',data);}catch(e){error(e.message);}};
$('deploy').onclick=async()=>{const planId=state.plan_id,revision=settingsRevision,planned=(state.plans||[]).flatMap(b=>b.plan.rows).filter(r=>r.status==='planned').length;
 if(await confirmAction('确认创建清单',`将执行当前检查清单：${planned} 个缺失模型部署；复用已有配置，并创建缺失的 Foundry 和 Project。\n新资源使用默认网络设置、S0 和系统托管身份。不会覆盖已有部署或重置密钥。`)){if(state.plan_id!==planId||revision!==settingsRevision||settingsChanged)return error('清单或设置已变化，请重新检查后确认。');action('deploy',{plan_id:planId,confirmed:true});}};
$('cancel').onclick=()=>action('cancel');
$('read-keys').onclick=async()=>{if(await confirmAction('读取账户 Key','只读取结果中资源的当前 Key，不重新生成。读取后可逐项显示、复制，或显式导出含密钥的 Excel。'))action('keys');};
$('export').onclick=async()=>{let include=false;if((state.results||[]).some(r=>r['密钥']==='••••••••'))include=await confirmAction('导出是否包含密钥','点击“确认”导出含明文密钥的 Excel；点击“取消”导出不含密钥的资源清单。请妥善保管含密钥的文件。');
 try{const response=await api('export',{include_keys:include,confirmed:include});const blob=await response.blob(),url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='foundry-resources.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);toast('已开始下载');}catch(e){error(e.message);}};
function render(next){state=next;const busy=['running','cancelling'].includes(next.job?.status);
 if(next.login_error)error(next.login_error);
 if(next.login_url&&next.login_url!==redirectedLogin){try{const destination=new URL(next.login_url);if(destination.protocol==='https:'&&destination.hostname==='login.microsoftonline.com'){redirectedLogin=next.login_url;window.location.assign(next.login_url);}}catch{error('Microsoft 登录地址无效，请重新连接。');}}
 $('connection-label').textContent=next.connected?'已连接客户 Azure':'尚未连接 Azure';$('connection-dot').classList.toggle('connected',!!next.connected);$('tenant-label').textContent=next.tenant_id||'登录后显示客户租户';$('logout').hidden=!next.connected;$('login-panel').hidden=!!next.connected;
 $('tenant').placeholder=next.login_mode==='browser'?'可留空：登录后自动识别客户租户':'请输入客户 Azure 租户 UUID';
 $('login').disabled=busy;for(const id of ['scan','catalog'])$(id).disabled=busy||!next.connected;
 const signature=JSON.stringify(next.subscriptions||[]);if(signature!==subscriptionSignature){subscriptionSignature=signature;selected=new Set((next.subscriptions||[]).map(s=>s.subscriptionId));closePicker();}
 $('subscription-count').textContent=next.connected?`已选择 ${selected.size} 项`:'尚未连接';
 $('challenge').hidden=!next.challenge;if(next.challenge){$('login-code').textContent=next.challenge.code;$('login-link').href=next.challenge.url;}
 const job=next.job||{};$('progress-panel').hidden=!job.status;$('job-title').textContent=job.title||'';$('job-message').textContent=job.message||'';
 $('progress').max=job.total||1;if(job.total)$('progress').value=job.completed||0;else if(busy)$('progress').removeAttribute('value');else $('progress').value=job.status==='done'?1:0;
 $('job-count').textContent=(job.phase?job.phase+' · ':'')+(job.total?`${job.completed||0} / ${job.total}`:'等待当前步骤反馈')+(busy?` · 已运行 ${Math.max(0,Math.floor(Date.now()/1000-(job.started_at||Date.now()/1000)))} 秒`:'');$('job-status').textContent=({running:'执行中',cancelling:'正在取消',done:'完成',failed:'未完成',cancelled:'已取消'})[job.status]||'';
 $('cancel').hidden=!busy;$('cancel').disabled=job.status==='cancelling';$('cancel').textContent=job.status==='cancelling'?'正在取消…':'取消任务';
 const cs=JSON.stringify(next.catalog);if(cs!==catalogSignature){catalogSignature=cs;for(const [name,input] of versionInputs){const entries=next.catalog?.models?.[name]||[];const list=$('versions-'+name);list.replaceChildren();for(const entry of entries){const option=document.createElement('option');option.value=entry.version||'';option.label=entry.skus.join(' / ');list.append(option);}if(entries.length===1&&!input.value)input.value=entries[0].version||'';}
 if(next.catalog?.region)$('catalog-note').textContent=`已读取 ${next.catalog.region} 的 Azure 目录；空列表表示该区域未返回此模型，请核对其他批准区域或访问权限。`;}
 const plans=next.plans||[],rows=plans.flatMap(b=>b.plan.rows||[]);$('review-panel').hidden=!plans.length;const rs=JSON.stringify(plans);
 if(rs!==reviewSignature){reviewSignature=rs;const body=$('review-rows');body.replaceChildren();for(const bundle of plans)for(const row of bundle.plan.rows){const aid=row.account_id||row.existing?.[0]?.account_id||'',project=bundle.projects?.[aid];const tr=document.createElement('tr');tr.innerHTML=`<td>${escapeHTML(row.subscription)}</td><td>${escapeHTML(regionNames[row.region]||row.region)}</td><td>${escapeHTML(row.model)}<small>${escapeHTML(row.version)}</small></td><td>${escapeHTML(aid.split('/').pop()||'待确认')}<small>${escapeHTML(project?.name||'尚未确定')}</small></td><td>${escapeHTML(row.capacity??'—')}<small>${row.estimated_rpm!=null?escapeHTML(row.estimated_rpm)+' RPM':'以 Azure 实际限流为准'}</small></td><td><span class="state ${row.status}">${({planned:'将创建',existing:'复用已有',blocked:'需要处理'})[row.status]||escapeHTML(row.status)}</span><small>${escapeHTML(row.message||'')}</small></td>`;body.append(tr);}}
 const blocked=rows.filter(r=>r.status==='blocked').length+(plans.flatMap(b=>b.plan.errors||[]).length);$('review-summary').textContent=`${rows.filter(r=>r.status==='planned').length} 个待创建 · ${rows.filter(r=>r.status==='existing').length} 个复用`;
 const executable=plans.some(b=>!b.project_errors?.length&&b.plan.rows.some(r=>['planned','existing'].includes(r.status)));
 $('deploy').disabled=busy||!next.plan_id||!executable||settingsChanged;$('create-note').textContent=settingsChanged?'设置已变化，请重新检查。':blocked?'存在阻塞项，仅执行可用项；Project 不兼容的模型会跳过。':'核对清单后即可创建。';
 const issues=next.issues||[];$('review-issues').hidden=!issues.length;$('review-issues').textContent=issues.join('\n');$('result-issues').hidden=!issues.length;$('result-issues').textContent=issues.join('\n');
 $('results-panel').hidden=!next.results?.length;$('read-keys').disabled=busy;$('export').disabled=!next.results?.length;
 const resultSig=JSON.stringify(next.results||[]);if(resultSig!==resultSignature){resultSignature=resultSig;const body=$('results');body.replaceChildren();const seen=new Set();for(const row of next.results||[]){const unique=row._account_id+'|'+row['资源'];if(seen.has(unique))continue;seen.add(unique);const tr=document.createElement('tr');for(const key of ['订阅','订阅 ID','资源组','资源名称-foundry','区域','资源','url','密钥']){const td=document.createElement('td');td.textContent=row[key]||'';if(key==='url'&&/^https:\/\//.test(row[key]||'')){const a=document.createElement('a');a.href=row[key];a.textContent=row[key];a.target='_blank';a.rel='noopener noreferrer';td.replaceChildren(a);}if(key==='密钥'&&row[key]==='••••••••'){const value=document.createElement('span');value.className='key-text';value.textContent=row[key];const show=document.createElement('button');show.className='key-button';show.textContent='显示';const copyButton=document.createElement('button');copyButton.className='key-button';copyButton.textContent='复制';const get=async()=>{const response=await api('reveal',{account_id:row._account_id});return (await response.json()).key;};show.onclick=async()=>{try{if(show.textContent==='隐藏'){value.textContent='••••••••';show.textContent='显示';}else{value.textContent=await get();show.textContent='隐藏';}}catch(e){error(e.message);}};copyButton.onclick=async()=>{try{await copy(await get());}catch(e){error(e.message);}};td.replaceChildren(value,show,copyButton);}tr.append(td);}body.append(tr);}}
 $('empty').hidden=plans.length>0||next.results?.length>0;
}
let refreshing=false;
async function refresh(){if(refreshing)return;refreshing=true;try{const response=await fetch('/api/state');if(!response.ok)throw new Error('会话已过期，请刷新页面重新连接。');const next=await response.json();if(next.plan_id&&next.plan_id!==state.plan_id)settingsChanged=scanRevision!==settingsRevision;render(next);}catch(e){error(e.message);}finally{refreshing=false;}}
refresh();setInterval(refresh,1000);
