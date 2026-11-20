// Establish a signed browser session before allowing booking mutations.
let accessPromise;
async function accessSession() {
  if (!accessPromise) accessPromise=fetch('/api/session').then(async response => {
    if (!response.ok) throw new Error('Could not establish your browser session. Reload to retry.');
    return response.json();
  }).catch(error => { accessPromise=null; throw error; });
  return accessPromise;
}
window.prepareApi=async options => {
  const access=await accessSession();
  if (access.enabled && options.method==='POST') {
    options.headers={...options.headers,'X-CSRF-Token':access.csrf};
  }
};
window.createBrowserIdentity=async name => {
  const access=await accessSession();
  if (!access.enabled) return null;
  let key=load('identityCreationKey');
  if (!key) { key=crypto.randomUUID();save('identityCreationKey',key); }
  const user=await api('session/identities',{name,key});
  window.allowedBrowserUsers?.add(user.user_id);
  save('identityCreationKey',null);
  return user;
};
window.initializeAccess=async () => {
  const access=await accessSession();
  document.getElementById('admin-access').hidden=!access.enabled;
  if (access.enabled) {
    const users=new Map(access.users.map(user=>[user.user_id,user]));
    window.allowedBrowserUsers=access.admin?null:new Set(users.keys());
    // Browser storage is a convenience cache; only the server grants ownership.
    if (!access.admin) {
      if (getCurrentUser() && !users.has(getCurrentUser().user_id)) selectDemoIdentity(null);
    }
    for (const user of access.users) rememberDemoUser(user);
    document.querySelector('.admin-group').hidden=!access.admin;
    document.getElementById('admin-access').textContent=access.admin?'Sign out of admin':'Administrator sign in';
    if (!access.admin) save('currentTab','join');
  }
};
document.getElementById('admin-access').addEventListener('click',async () => {
  try {
    const access=await accessSession();
    if (!access.enabled) return;
    if (access.admin) await api('session/logout',{});
    else {
      document.getElementById('admin-login-error').innerHTML='';
      document.getElementById('admin-login-dialog').showModal();
      document.getElementById('admin-password').focus();
      return;
    }
    window.location.reload();
  } catch(error) { window.alert(error.message); }
});
document.getElementById('admin-login-close').addEventListener('click',() => {
  document.getElementById('admin-login-dialog').close();
  document.getElementById('admin-login-form').reset();
});
document.getElementById('admin-login-form').addEventListener('submit',async event => {
  event.preventDefault();
  const button=document.getElementById('admin-login-submit');
  button.disabled=true;
  try {
    await api('session/admin',{password:document.getElementById('admin-password').value});
    document.getElementById('admin-login-form').reset();
    window.location.reload();
  } catch(error) {
    document.getElementById('admin-login-error').innerHTML=message(error.message,true);
  } finally { button.disabled=false; }
});
