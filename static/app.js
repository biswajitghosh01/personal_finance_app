const toggle=document.getElementById('menu-toggle');
const sidebar=document.getElementById('sidebar');
if(toggle&&sidebar){toggle.addEventListener('click',()=>{const open=sidebar.classList.toggle('is-open');toggle.setAttribute('aria-expanded',String(open));});document.addEventListener('click',event=>{if(window.innerWidth<=900&&sidebar.classList.contains('is-open')&&!sidebar.contains(event.target)&&event.target!==toggle){sidebar.classList.remove('is-open');toggle.setAttribute('aria-expanded','false');}});}
const current=window.location.pathname;
document.querySelectorAll('.side-nav a').forEach(link=>{if(link.pathname===current||(current.startsWith(link.pathname)&&link.pathname!=='/'))link.classList.add('active');});
