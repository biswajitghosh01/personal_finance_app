const category=document.getElementById('category');
if(category){category.addEventListener('change',()=>{const routes={BANK:'/bank-accounts/new',FIXED_DEPOSIT:'/fixed-deposits/new',SHARE:'/stocks/new',ESOP:'/esops/new',MUTUAL_FUND:'/mutual-funds/new',METAL:'/metals/new',LIABILITY:'/liabilities/new'};if(routes[category.value])window.location.assign(routes[category.value]);});}
