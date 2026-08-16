export async function getStatus(){return jsonFetch('/api/status')}
export async function listIdentities(){return jsonFetch('/api/identities')}
export async function deleteIdentity(id){const r=await fetch(`/api/identities/${encodeURIComponent(id)}`,{method:'DELETE'});if(!r.ok&&r.status!==204)throw await apiError(r)}
export async function eraseAll(){return jsonFetch('/api/identities',{method:'DELETE'})}
export async function recognize(blob){return imageFetch('/api/recognize',blob)}
export async function enroll(blob,name){const qs=new URLSearchParams({display_name:name,consent:'true'});return imageFetch(`/api/enroll?${qs}`,blob,{method:'POST'})}
async function imageFetch(url,blob,init={}){const r=await fetch(url,{method:init.method||'POST',headers:{'content-type':'image/jpeg'},body:blob});if(!r.ok)throw await apiError(r);return r.json()}
async function jsonFetch(url,init){const r=await fetch(url,init);if(!r.ok)throw await apiError(r);return r.status===204?null:r.json()}
async function apiError(r){let detail=`HTTP ${r.status}`;try{const b=await r.json();detail=b.detail||detail}catch{}return new Error(detail)}
