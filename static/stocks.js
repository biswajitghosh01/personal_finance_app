(() => {
  'use strict';
  const byId=id=>document.getElementById(id);
  const fields=['number_of_shares','buy_price','current_price','gst','brokerage','stt','exchange_fees','sale_units'].map(byId);
  const number=id=>Number(byId(id)?.value)||0;
  function calculate(){
    const units=number('number_of_shares');
    const buyPrice=number('buy_price');
    const currentPrice=number('current_price');
    const fees=number('gst')+number('brokerage')+number('stt')+number('exchange_fees');
    const sold=Math.min(number('sale_units'),units);
    const balance=Math.max(0,units-sold);
    const totalInvestment=units*buyPrice+fees;
    const remainingCost=units>0?totalInvestment*(balance/units):0;
    const holdingValue=balance*currentPrice;
    const pnl=holdingValue-remainingCost;
    const pct=remainingCost>0?pnl/remainingCost*100:0;
    byId('total_investment').value=totalInvestment.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    byId('remaining_units').value=balance.toLocaleString(undefined,{maximumFractionDigits:6});
    byId('holding_value').value=holdingValue.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    byId('profit_loss_amount').value=pnl.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    byId('profit_loss_percentage').value=pct.toFixed(2)+'%';
    ['profit_loss_amount','profit_loss_percentage'].forEach(id=>{const el=byId(id);el.classList.toggle('positive',pnl>=0);el.classList.toggle('negative',pnl<0);});
  }
  fields.filter(Boolean).forEach(field=>field.addEventListener('input',calculate));
  calculate();
})();
