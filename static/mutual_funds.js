(() => {
  'use strict';
  const invested=document.getElementById('invested_amount');
  const current=document.getElementById('current_value');
  const profitLoss=document.getElementById('profit_loss');
  const percentageReturn=document.getElementById('percentage_return');
  function calculate(){
    const investedValue=Number(invested?.value)||0;
    const currentValue=Number(current?.value)||0;
    const pnl=currentValue-investedValue;
    const percentage=investedValue>0?pnl/investedValue*100:0;
    if(profitLoss){profitLoss.value=pnl.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});profitLoss.classList.toggle('positive',pnl>=0);profitLoss.classList.toggle('negative',pnl<0);}
    if(percentageReturn){percentageReturn.value=percentage.toFixed(2)+'%';percentageReturn.classList.toggle('positive',pnl>=0);percentageReturn.classList.toggle('negative',pnl<0);}
  }
  [invested,current].filter(Boolean).forEach(field=>field.addEventListener('input',calculate));
  calculate();
})();
