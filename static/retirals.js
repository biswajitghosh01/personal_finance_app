(() => {
  'use strict';
  const invested=document.getElementById('amount_invested');
  const current=document.getElementById('current_value');
  const pnl=document.getElementById('retiral_profit_loss');
  const returned=document.getElementById('retiral_return');
  function calculate(){
    const investedValue=Number(invested?.value)||0;
    const currentValue=Number(current?.value)||0;
    const difference=currentValue-investedValue;
    const percentage=investedValue>0?difference/investedValue*100:0;
    if(pnl){pnl.value=difference.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});pnl.classList.toggle('positive',difference>=0);pnl.classList.toggle('negative',difference<0);}
    if(returned){returned.value=percentage.toFixed(2)+'%';returned.classList.toggle('positive',difference>=0);returned.classList.toggle('negative',difference<0);}
  }
  [invested,current].filter(Boolean).forEach(field=>field.addEventListener('input',calculate));
  calculate();
})();
