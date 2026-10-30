const $=id=>document.getElementById(id);
function report(error){$('error').textContent=error.message||'Something went wrong. Please try again.';}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});const body=await response.json();if(!response.ok)throw new Error(body.message||body.error||'Request failed');return body;}
