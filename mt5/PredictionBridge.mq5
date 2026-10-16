#property strict
#property version "1.02"
#property description "Loopback coordinator bridge. OANDA demo accounts only; orders disabled by default."

input string CoordinatorURL="http://127.0.0.1:8787";
input string LocalToken="";
input long ExpectedLogin=0;
input string ExpectedServer="OANDA_Global-Demo-1";
input string EURUSDSymbol="EURUSD";
input string XAUUSDSymbol="XAUUSD";
input bool EnableOrders=false;
input int PollSeconds=2;
input int MaxTickAgeSeconds=5;

#define LOCK_NAME "PredictionBridge.v1.executor"
#define STATE_DIR "PredictionBridge"
#define PENDING_FILE "PredictionBridge\\pending.json"
#define MAGIC_MIN 700000000000
#define MAGIC_MAX 800000000000

int lock_handle=INVALID_HANDLE;
bool owns_lock=false,halted=false;
string pending="";
MqlTick submitted_ticks[2];
ulong submitted_at=0;

string Symbols[2]={"EURUSD","XAUUSD"};
string J(string text)
{
   string out="\"";
   for(int i=0;i<StringLen(text);i++)
   {
      ushort c=StringGetCharacter(text,i);
      if(c==34) out+="\\\"";
      else if(c==92) out+="\\\\";
      else if(c<32) out+=StringFormat("\\u%04x",c);
      else out+=ShortToString(c);
   }
   return out+"\"";
}
string N(double value) { return MathIsValidNumber(value) ? DoubleToString(value,12) : "null"; }
string I(long value) { return StringFormat("%I64d",value); }
string B(bool value) { return value ? "true" : "false"; }
bool Positive(double value) { return MathIsValidNumber(value) && value>0; }
int SymbolIndex(string symbol) { for(int i=0;i<2;i++) if(Symbols[i]==symbol) return i; return -1; }
bool MagicKnown(long magic) { return magic>=MAGIC_MIN && magic<MAGIC_MAX; }
bool ValidBrokerSymbol(string value,string base)
{
   if(value==base) return true;
   int start=StringLen(base)+1,n=StringLen(value);
   if(n<=start || n>31 || StringFind(value,base+".")!=0) return false;
   for(int i=start;i<n;i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(!((c>=65 && c<=90) || (c>=97 && c<=122) || (c>=48 && c<=57) || c==95 || c==45)) return false;
   }
   return true;
}

bool IdentityOK()
{
   string company=AccountInfoString(ACCOUNT_COMPANY);
   StringToUpper(company);
   return ExpectedLogin>0 && AccountInfoInteger(ACCOUNT_LOGIN)==ExpectedLogin
      && AccountInfoString(ACCOUNT_SERVER)==ExpectedServer
      && AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO
      && StringFind(company,"OANDA")>=0;
}
bool PermissionsOK()
{
   return TerminalInfoInteger(TERMINAL_CONNECTED) && TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
      && MQLInfoInteger(MQL_TRADE_ALLOWED) && AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
      && AccountInfoInteger(ACCOUNT_TRADE_EXPERT);
}
bool TickOK(string symbol,MqlTick &tick)
{
   if(!SymbolIsSynchronized(symbol) || !SymbolInfoTick(symbol,tick)) return false;
   long age=(long)TimeTradeServer()-(long)tick.time;
   return Positive(tick.bid) && Positive(tick.ask) && tick.ask>=tick.bid
      && age>=0 && age<=MaxTickAgeSeconds;
}

bool WriteDurable(string name,string body)
{
   int h=FileOpen(name,FILE_WRITE|FILE_BIN);
   if(h==INVALID_HANDLE) return false;
   uchar data[];
   int count=StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8)-1;
   bool ok=count>=0 && FileWriteArray(h,data,0,count)==(uint)count;
   ResetLastError();
   FileFlush(h);
   ok=ok && GetLastError()==0;
   FileClose(h);
   return ok;
}
bool ReplacePending(string body)
{
   string temp=STATE_DIR+"\\pending.tmp";
   if(!WriteDurable(temp,body)) return false;
   if(!FileMove(temp,0,PENDING_FILE,FILE_REWRITE)) return false;
   pending=body;
   return true;
}
bool LoadPending()
{
   if(!FileIsExist(PENDING_FILE)) return true;
   int h=FileOpen(PENDING_FILE,FILE_READ|FILE_BIN);
   if(h==INVALID_HANDLE) return false;
   ulong size=FileSize(h);
   if(size==0 || size>16384) { FileClose(h); return false; }
   uchar data[];
   bool ok=FileReadArray(h,data,0,(int)size)==(uint)size;
   FileClose(h);
   if(!ok) return false;
   pending=CharArrayToString(data,0,(int)size,CP_UTF8);
   // File corruption blocks the bridge. JSON authority remains the Python API.
   return StringFind(pending,"{\"id\":\"")==0 && StringFind(pending,"\"status\":")>0;
}
bool Post(string path,string body,string &response)
{
   char data[],result[];
   int count=StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8)-1;
   if(count<0 || count>2097152) return false;
   ArrayResize(data,count);
   string headers="Content-Type: application/json\r\nAuthorization: Bearer "+LocalToken+"\r\n";
   string returned_headers;
   int code=WebRequest("POST",CoordinatorURL+path,headers,4000,data,result,returned_headers);
   if(code!=200 || ArraySize(result)>4096) return false;
   response=CharArrayToString(result,0,WHOLE_ARRAY,CP_UTF8);
   return true;
}
bool Acknowledge()
{
   if(pending=="") return true;
   string response;
   if(!Post("/v1/result",pending,response) || response!="OK") return false;
   if(!FileDelete(PENDING_FILE)) { halted=true; return false; }
   pending="";
   return true;
}
string ResultBody(string id,string status,uint retcode,ulong order,ulong deal,double volume,double price,string detail)
{
   return "{\"id\":"+J(id)+",\"status\":"+J(status)+",\"retcode\":"+I((long)retcode)
      +",\"order\":"+I((long)order)+",\"deal\":"+I((long)deal)+",\"volume\":"+N(volume)
      +",\"price\":"+N(price)+",\"detail\":"+J(detail)+"}";
}
void Reject(string id,string detail)
{
   if(!ReplacePending(ResultBody(id,"rejected",0,0,0,0,0,detail))) halted=true;
}

string BarJSON(string symbol,ENUM_TIMEFRAMES frame)
{
   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   // Copy initiates missing history download/building; do not gate it on synchronization.
   int copied=CopyRates(symbol,frame,1,240,rates);
   if(copied!=240 || !SymbolIsSynchronized(symbol)
      || !SeriesInfoInteger(symbol,frame,SERIES_SYNCHRONIZED)) return "[]";
   string out="[";
   for(int i=0;i<240;i++)
   {
      if(i>0) out+=",";
      out+="{\"time\":"+I(rates[i].time)+",\"open\":"+N(rates[i].open)+",\"high\":"+N(rates[i].high)
         +",\"low\":"+N(rates[i].low)+",\"close\":"+N(rates[i].close)+"}";
   }
   return out+"]";
}
long BarAge(string symbol,ENUM_TIMEFRAMES frame)
{
   datetime times[];
   int copied=CopyTime(symbol,frame,1,1,times);
   if(copied!=1 || !SymbolIsSynchronized(symbol)
      || !SeriesInfoInteger(symbol,frame,SERIES_SYNCHRONIZED)) return -1;
   long age=(long)TimeTradeServer()-(long)times[0]-PeriodSeconds(frame);
   return age>=0 ? age : -1;
}
double SelectedPositionRisk()
{
   string symbol=PositionGetString(POSITION_SYMBOL);
   double sl=PositionGetDouble(POSITION_SL),volume=PositionGetDouble(POSITION_VOLUME),profit;
   MqlTick tick;
   if(!Positive(sl) || !Positive(volume) || !TickOK(symbol,tick)) return -1;
   bool buy=PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY;
   double liquidation=buy ? tick.bid : tick.ask;
   if((buy && sl>=liquidation) || (!buy && sl<=liquidation)) return 0;
   if(!OrderCalcProfit(buy?ORDER_TYPE_BUY:ORDER_TYPE_SELL,symbol,volume,liquidation,sl,profit)
      || !MathIsValidNumber(profit)) return -1;
   return MathMax(0,-profit);
}
string PositionJSON()
{
   string out="[";
   bool first=true;
   for(int i=0;i<PositionsTotal();i++)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) { halted=true; continue; }
      if(!first) out+=",";
      first=false;
      out+="{\"ticket\":"+I((long)ticket)+",\"identifier\":"+I(PositionGetInteger(POSITION_IDENTIFIER))
         +",\"symbol\":"+J(PositionGetString(POSITION_SYMBOL))+",\"magic\":"+I(PositionGetInteger(POSITION_MAGIC))
         +",\"side\":"+J(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY?"BUY":"SELL")
         +",\"volume\":"+N(PositionGetDouble(POSITION_VOLUME))+",\"sl\":"+N(PositionGetDouble(POSITION_SL))
         +",\"tp\":"+N(PositionGetDouble(POSITION_TP))+",\"profit\":"+N(PositionGetDouble(POSITION_PROFIT))
         +",\"risk\":"+N(SelectedPositionRisk())+"}";
   }
   return out+"]";
}
string OrderJSON()
{
   string out="[";
   bool first=true;
   for(int i=0;i<OrdersTotal();i++)
   {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0) { halted=true; continue; }
      if(!first) out+=",";
      first=false;
      out+="{\"ticket\":"+I((long)ticket)+",\"symbol\":"+J(OrderGetString(ORDER_SYMBOL))
         +",\"magic\":"+I(OrderGetInteger(ORDER_MAGIC))+"}";
   }
   return out+"]";
}
string DealJSON(bool &complete)
{
   string out="[";
   complete=HistorySelect(0,TimeTradeServer());
   if(!complete) return "[]";
   int count=0;
   for(int i=0;i<HistoryDealsTotal();i++)
   {
      ulong ticket=HistoryDealGetTicket(i);
      if(ticket==0) { complete=false; continue; }
      long type=HistoryDealGetInteger(ticket,DEAL_TYPE);
      if(type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL) continue;
      count++;
      if(count>2000) { complete=false; continue; }
      if(count>1) out+=",";
      out+="{\"ticket\":"+I((long)ticket)+",\"order\":"+I(HistoryDealGetInteger(ticket,DEAL_ORDER))
         +",\"position_id\":"+I(HistoryDealGetInteger(ticket,DEAL_POSITION_ID))
         +",\"magic\":"+I(HistoryDealGetInteger(ticket,DEAL_MAGIC))
         +",\"entry\":"+I(HistoryDealGetInteger(ticket,DEAL_ENTRY))
         +",\"symbol\":"+J(HistoryDealGetString(ticket,DEAL_SYMBOL))
         +",\"volume\":"+N(HistoryDealGetDouble(ticket,DEAL_VOLUME))
         +",\"profit\":"+N(HistoryDealGetDouble(ticket,DEAL_PROFIT))
         +",\"commission\":"+N(HistoryDealGetDouble(ticket,DEAL_COMMISSION))
         +",\"swap\":"+N(HistoryDealGetDouble(ticket,DEAL_SWAP))
         +",\"fee\":"+N(HistoryDealGetDouble(ticket,DEAL_FEE))
         +",\"time\":"+I(HistoryDealGetInteger(ticket,DEAL_TIME))+"}";
   }
   return out+"]";
}
string Snapshot()
{
   submitted_at=GetTickCount64();
   bool complete;
   string deals=DealJSON(complete);
   string out="{\"version\":1,\"utc\":"+I(TimeGMT())
      +",\"connected\":"+B((bool)TerminalInfoInteger(TERMINAL_CONNECTED))
      +",\"trade_allowed\":"+B(EnableOrders && IdentityOK() && PermissionsOK() && !halted)
      +",\"history_complete\":"+B(complete)+",\"account\":{\"login\":"+I(AccountInfoInteger(ACCOUNT_LOGIN))
      +",\"server\":"+J(AccountInfoString(ACCOUNT_SERVER))+",\"company\":"+J(AccountInfoString(ACCOUNT_COMPANY))
      +",\"currency\":"+J(AccountInfoString(ACCOUNT_CURRENCY))
      +",\"demo\":"+B(AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO)
      +",\"balance\":"+N(AccountInfoDouble(ACCOUNT_BALANCE))+",\"equity\":"+N(AccountInfoDouble(ACCOUNT_EQUITY))
      +",\"margin_free\":"+N(AccountInfoDouble(ACCOUNT_MARGIN_FREE))+"},\"positions\":"+PositionJSON()
      +",\"orders\":"+OrderJSON()+",\"deals\":"+deals+",\"symbols\":{";
   for(int i=0;i<2;i++)
   {
      string symbol=Symbols[i];
      MqlTick tick={};
      bool valid=TickOK(symbol,tick);
      submitted_ticks[i]=tick;
      if(i>0) out+=",";
      out+=J(symbol)+":{\"bid\":"+N(tick.bid)+",\"ask\":"+N(tick.ask)
         +",\"tick_age\":"+(valid?I((long)TimeTradeServer()-(long)tick.time):"-1")
         +",\"point\":"+N(SymbolInfoDouble(symbol,SYMBOL_POINT))
         +",\"tick_size\":"+N(SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE))
         +",\"digits\":"+I(SymbolInfoInteger(symbol,SYMBOL_DIGITS))
         +",\"stops_level\":"+I(SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL))
         +",\"trade_mode\":"+I(SymbolInfoInteger(symbol,SYMBOL_TRADE_MODE))
         +",\"bar_age\":{\"M15\":"+I(BarAge(symbol,PERIOD_M15))+",\"H1\":"+I(BarAge(symbol,PERIOD_H1))
         +",\"H4\":"+I(BarAge(symbol,PERIOD_H4))+"}"
         +",\"bars\":{\"M15\":"+BarJSON(symbol,PERIOD_M15)+",\"H1\":"+BarJSON(symbol,PERIOD_H1)
         +",\"H4\":"+BarJSON(symbol,PERIOD_H4)+"}}";
   }
   return out+"}}";
}

bool DigitsOnly(string value)
{
   int n=StringLen(value);
   if(n<1 || n>18) return false;
   for(int i=0;i<n;i++) { ushort c=StringGetCharacter(value,i); if(c<48 || c>57) return false; }
   return true;
}
bool Number(string value,double &result)
{
   int n=StringLen(value),i=0,digits=0;
   if(n<1 || n>32) return false;
   while(i<n && StringGetCharacter(value,i)>=48 && StringGetCharacter(value,i)<=57) { i++; digits++; }
   if(i<n && StringGetCharacter(value,i)==46)
   {
      i++;
      while(i<n && StringGetCharacter(value,i)>=48 && StringGetCharacter(value,i)<=57) { i++; digits++; }
   }
   if(digits==0) return false;
   if(i<n && (StringGetCharacter(value,i)==69 || StringGetCharacter(value,i)==101))
   {
      i++;
      if(i<n && (StringGetCharacter(value,i)==43 || StringGetCharacter(value,i)==45)) i++;
      int start=i;
      while(i<n && StringGetCharacter(value,i)>=48 && StringGetCharacter(value,i)<=57) i++;
      if(i==start) return false;
   }
   if(i!=n) return false;
   result=StringToDouble(value);
   return Positive(result);
}
bool CommandID(string id)
{
   if(StringLen(id)!=24) return false;
   for(int i=0;i<24;i++)
   {
      ushort c=StringGetCharacter(id,i);
      if(!((c>=48 && c<=57) || (c>=97 && c<=102))) return false;
   }
   return true;
}
bool OwnedLifecycle(long identifier,long magic)
{
   if(identifier<=0 || !HistorySelectByPosition((ulong)identifier)) return false;
   int count=HistoryDealsTotal();
   if(count<1 || count>2000) return false;
   bool own_entry=false;
   for(int i=0;i<count;i++)
   {
      ulong ticket=HistoryDealGetTicket(i);
      long deal_position,entry,deal_magic;
      if(ticket==0 || !HistoryDealGetInteger(ticket,DEAL_POSITION_ID,deal_position)
         || !HistoryDealGetInteger(ticket,DEAL_ENTRY,entry)
         || !HistoryDealGetInteger(ticket,DEAL_MAGIC,deal_magic)
         || deal_position!=identifier) return false;
      // Netting additions/reversals can retain the original position identifier.
      if(entry==DEAL_ENTRY_INOUT || (entry==DEAL_ENTRY_IN && deal_magic!=magic)) return false;
      if(entry==DEAL_ENTRY_IN && deal_magic==magic) own_entry=true;
      // OUT and OUT_BY may legitimately have another magic (manual/broker exit).
   }
   return own_entry;
}
bool ExposureOK(string symbol,double risk,double equity,bool check_history=true)
{
   if(!Positive(equity) || risk>equity*.0025 || OrdersTotal()!=0 || PositionsTotal()>=2) return false;
   double total=risk;
   for(int i=0;i<PositionsTotal();i++)
   {
      if(PositionGetTicket(i)==0) return false;
      long magic=PositionGetInteger(POSITION_MAGIC);
      long identifier=PositionGetInteger(POSITION_IDENTIFIER);
      string existing_symbol=PositionGetString(POSITION_SYMBOL);
      double stop=PositionGetDouble(POSITION_SL);
      double existing=SelectedPositionRisk();
      if(existing_symbol==symbol || SymbolIndex(existing_symbol)<0
         || !MagicKnown(magic) || !FileIsExist(STATE_DIR+"\\magic_"+I(magic)+".claim")) return false;
      if(!MathIsValidNumber(existing) || existing<0 || !Positive(stop)) return false;
      if(check_history && !OwnedLifecycle(identifier,magic)) return false;
      total+=existing;
   }
   return total<=equity*.005;
}
bool DefinitiveReject(uint code)
{
   switch(code)
   {
      case TRADE_RETCODE_REQUOTE: case TRADE_RETCODE_REJECT: case TRADE_RETCODE_CANCEL:
      case TRADE_RETCODE_INVALID: case TRADE_RETCODE_INVALID_VOLUME: case TRADE_RETCODE_INVALID_PRICE:
      case TRADE_RETCODE_INVALID_STOPS: case TRADE_RETCODE_TRADE_DISABLED: case TRADE_RETCODE_MARKET_CLOSED:
      case TRADE_RETCODE_NO_MONEY: case TRADE_RETCODE_PRICE_CHANGED: case TRADE_RETCODE_PRICE_OFF:
      case TRADE_RETCODE_INVALID_EXPIRATION: case TRADE_RETCODE_TOO_MANY_REQUESTS:
      case TRADE_RETCODE_SERVER_DISABLES_AT: case TRADE_RETCODE_CLIENT_DISABLES_AT:
      case TRADE_RETCODE_INVALID_FILL: case TRADE_RETCODE_ONLY_REAL:
      case TRADE_RETCODE_LIMIT_ORDERS: case TRADE_RETCODE_LIMIT_VOLUME: case TRADE_RETCODE_INVALID_ORDER:
      case TRADE_RETCODE_LIMIT_POSITIONS: case TRADE_RETCODE_LONG_ONLY: case TRADE_RETCODE_SHORT_ONLY:
      case TRADE_RETCODE_CLOSE_ONLY: case TRADE_RETCODE_HEDGE_PROHIBITED:
         return true;
   }
   return false;
}
bool StopsOK(string symbol,bool buy,MqlTick &tick,double sl,double tp)
{
   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   double distance=SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL)*point;
   if(!Positive(point) || !MathIsValidNumber(distance) || distance<0) return false;
   if(buy) return sl<tick.bid && tp>tick.ask && tick.bid-sl>=distance && tp-tick.bid>=distance;
   return sl>tick.ask && tp<tick.bid && sl-tick.ask>=distance && tick.ask-tp>=distance;
}
bool FreshHistory()
{
   if(!HistorySelect(0,TimeTradeServer())) return false;
   int count=0;
   for(int i=0;i<HistoryDealsTotal();i++)
   {
      ulong ticket=HistoryDealGetTicket(i);
      if(ticket==0) return false;
      long type=HistoryDealGetInteger(ticket,DEAL_TYPE);
      if(type==DEAL_TYPE_BUY || type==DEAL_TYPE_SELL) count++;
      if(count>2000) return false;
   }
   return true;
}
bool FillPolicy(string symbol,ENUM_ORDER_TYPE_FILLING &policy)
{
   long execution=SymbolInfoInteger(symbol,SYMBOL_TRADE_EXEMODE);
   long modes=SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE);
   if(execution==SYMBOL_TRADE_EXECUTION_INSTANT || execution==SYMBOL_TRADE_EXECUTION_REQUEST
      || (modes & SYMBOL_FILLING_FOK)!=0) { policy=ORDER_FILLING_FOK; return true; }
   if((modes & SYMBOL_FILLING_IOC)!=0) { policy=ORDER_FILLING_IOC; return true; }
   return false; // RETURN can leave an unfilled remainder; never use it.
}
void Execute(string wire)
{
   string fields[];
   if(StringLen(wire)>1024 || StringSplit(wire,'|',fields)!=14 || fields[0]!="OPEN" || !CommandID(fields[1]))
   { Print("Invalid coordinator response: execution blocked."); return; }
   string id=fields[1],symbol=fields[3];
   int index=SymbolIndex(symbol);
   bool buy=fields[4]=="BUY";
   double sl,tp,risk,spread_limit,slippage,equity_floor,margin_fraction;
   if(!DigitsOnly(fields[2]) || !DigitsOnly(fields[8]) || !DigitsOnly(fields[9]) || index<0
      || (!buy && fields[4]!="SELL") || !Number(fields[5],sl) || !Number(fields[6],tp)
      || !Number(fields[7],risk) || !Number(fields[10],spread_limit) || !Number(fields[11],slippage)
      || !Number(fields[12],equity_floor) || !Number(fields[13],margin_fraction) || margin_fraction>.20)
   { Reject(id,"Invalid command fields"); return; }
   long login=StringToInteger(fields[2]),expires=StringToInteger(fields[8]),magic=StringToInteger(fields[9]);
   string claim=STATE_DIR+"\\id_"+id+".claim";
   string magic_claim=STATE_DIR+"\\magic_"+I(magic)+".claim";
   string gv="PredictionBridge.id."+id;
   if(FileIsExist(claim) || GlobalVariableCheck(gv) || FileIsExist(magic_claim))
   {
      if(!ReplacePending(ResultBody(id,"uncertain",0,0,0,0,0,"Previously claimed command; never resubmitted"))) halted=true;
      return;
   }
   long now=(long)TimeGMT();
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(!EnableOrders || halted || !IdentityOK() || !PermissionsOK() || login!=ExpectedLogin
      || !MagicKnown(magic) || expires<=now || expires>now+15 || GetTickCount64()-submitted_at>15000
      || !Positive(equity) || equity<equity_floor || !ExposureOK(symbol,risk,equity) || !FreshHistory())
   { Reject(id,"Identity, permissions, expiry, history or account risk guard"); return; }
   long mode=SymbolInfoInteger(symbol,SYMBOL_TRADE_MODE),flags=SymbolInfoInteger(symbol,SYMBOL_ORDER_MODE);
   if((mode!=SYMBOL_TRADE_MODE_FULL && mode!=(buy?SYMBOL_TRADE_MODE_LONGONLY:SYMBOL_TRADE_MODE_SHORTONLY))
      || (flags & SYMBOL_ORDER_MARKET)==0 || (flags & SYMBOL_ORDER_SL)==0 || (flags & SYMBOL_ORDER_TP)==0
      || SymbolInfoInteger(symbol,SYMBOL_ORDER_GTC_MODE)==SYMBOL_ORDERS_DAILY)
   { Reject(id,"Symbol direction, market/stops support or stop persistence guard"); return; }
   MqlTick tick;
   if(!TickOK(symbol,tick)
      || tick.ask-tick.bid>spread_limit || MathAbs(tick.ask-submitted_ticks[index].ask)>slippage
      || MathAbs(tick.bid-submitted_ticks[index].bid)>slippage)
   { Reject(id,"Stale tick, spread or snapshot drift guard"); return; }
   double tick_size=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   if(!Positive(tick_size) || digits<0 || digits>12)
   { Reject(id,"Invalid symbol price granularity"); return; }
   double normal_sl=NormalizeDouble(MathRound(sl/tick_size)*tick_size,digits);
   double normal_tp=NormalizeDouble(MathRound(tp/tick_size)*tick_size,digits);
   // The coordinator rounds stops. Reject substantial changes instead of widening risk silently.
   if(MathAbs(normal_sl-sl)>tick_size*1e-6 || MathAbs(normal_tp-tp)>tick_size*1e-6)
   { Reject(id,"Stops must already be normalized to tick size"); return; }
   sl=normal_sl; tp=normal_tp;
   if(!StopsOK(symbol,buy,tick,sl,tp)) { Reject(id,"Invalid stop direction or distance"); return; }
   ENUM_ORDER_TYPE side=buy?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   double adverse=buy?tick.ask+slippage:tick.bid-slippage;
   double min_volume=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN),max_volume=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP),loss;
   if(!Positive(adverse) || !Positive(min_volume) || !Positive(max_volume) || !Positive(step)
      || !OrderCalcProfit(side,symbol,min_volume,adverse,sl,loss) || !MathIsValidNumber(loss) || loss>=0)
   { Reject(id,"Account-currency risk calculation unavailable"); return; }
   double volume=NormalizeDouble(MathFloor(MathMin(max_volume,risk/(-loss/min_volume))/step)*step,8);
   double measured;
   if(volume<min_volume || !OrderCalcProfit(side,symbol,volume,adverse,sl,measured)
      || !MathIsValidNumber(measured) || measured>=0 || -measured>risk)
   { Reject(id,"Volume below minimum or calculated risk exceeds budget"); return; }
   MqlTradeRequest request={};
   MqlTradeResult result={};
   MqlTradeCheckResult check={};
   request.action=TRADE_ACTION_DEAL;
   request.magic=(ulong)magic;
   request.symbol=symbol;
   request.volume=volume;
   request.type=side;
   request.price=buy?tick.ask:tick.bid;
   request.sl=sl; request.tp=tp;
   request.comment="PE:"+id;
   request.type_time=ORDER_TIME_GTC;
   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   if(!Positive(point) || slippage/point>1000000 || !FillPolicy(symbol,request.type_filling))
   { Reject(id,"Unsupported execution granularity or filling mode"); return; }
   request.deviation=(ulong)MathFloor(slippage/point);
   if(!OrderCheck(request,check) || !MathIsValidNumber(check.margin) || check.margin<0
      || !Positive(check.equity) || check.equity<equity_floor
      || check.margin>check.equity*margin_fraction || !MathIsValidNumber(check.margin_free) || check.margin_free<0)
   { Reject(id,"OrderCheck or projected total margin guard"); return; }
   // Claim BOTH command identity and magic durably before any broker call.
   if(!WriteDurable(claim,I(magic)) || !WriteDurable(magic_claim,id)
      || GlobalVariableSet(gv,(double)TimeGMT())==0)
   { halted=true; return; }
   GlobalVariablesFlush();
   string uncertain=ResultBody(id,"uncertain",0,0,0,0,0,"Claimed before broker send; outcome requires reconciliation");
   if(!ReplacePending(uncertain)) { halted=true; return; }
   MqlTick final_tick;
   // History selection may synchronize: finish it before sampling final equity and risk.
   if(!ExposureOK(symbol,risk,AccountInfoDouble(ACCOUNT_EQUITY)))
   { Reject(id,"Final position lifecycle or exposure guard"); return; }
   equity=AccountInfoDouble(ACCOUNT_EQUITY);
   // Reprice all positions without selecting history again, then check identity/quote/clock.
   if(!ExposureOK(symbol,risk,equity,false) || !IdentityOK() || !PermissionsOK() || !EnableOrders || !TickOK(symbol,final_tick)
      || TimeGMT()>=expires || GetTickCount64()-submitted_at>15000 || equity<equity_floor
      || final_tick.ask-final_tick.bid>spread_limit
      || MathAbs(final_tick.ask-submitted_ticks[index].ask)>slippage
      || MathAbs(final_tick.bid-submitted_ticks[index].bid)>slippage
      || (buy?final_tick.ask>adverse:final_tick.bid<adverse) || !StopsOK(symbol,buy,final_tick,sl,tp))
   { Reject(id,"Final identity, clock, quote or account guard"); return; }
   // Exactly one call. Even errors/timeouts are never retried.
   bool sent=OrderSend(request,result);
   string status="uncertain";
   if(sent && (result.retcode==TRADE_RETCODE_DONE || result.retcode==TRADE_RETCODE_DONE_PARTIAL) && result.deal>0)
      status="filled";
   else if(DefinitiveReject(result.retcode)) status="rejected";
   string body=ResultBody(id,status,result.retcode,result.order,result.deal,result.volume,result.price,"Single broker send completed");
   // Failure keeps the already-durable uncertain acknowledgement and stops execution.
   if(!ReplacePending(body)) halted=true;
}

int OnInit()
{
   // MT5 may reinitialize this instance after an input/account/chart change.
   lock_handle=INVALID_HANDLE;
   owns_lock=false;
   halted=false;
   pending="";
   submitted_at=0;
   string port=StringSubstr(CoordinatorURL,17);
   if(StringFind(CoordinatorURL,"http://127.0.0.1:")!=0 || !DigitsOnly(port)
      || StringToInteger(port)<1 || StringToInteger(port)>65535
      || StringLen(LocalToken)<32 || StringLen(LocalToken)>512 || StringFind(LocalToken,"\r")>=0 || StringFind(LocalToken,"\n")>=0
      || ExpectedLogin<=0 || ExpectedServer=="" || PollSeconds<1 || PollSeconds>60
      || !ValidBrokerSymbol(EURUSDSymbol,"EURUSD") || !ValidBrokerSymbol(XAUUSDSymbol,"XAUUSD")
      || MaxTickAgeSeconds<1 || MaxTickAgeSeconds>10 || MQLInfoInteger(MQL_TESTER))
   { Print("Bridge configuration invalid; configure pinned demo identity and loopback token."); return INIT_PARAMETERS_INCORRECT; }
   // File ownership is authoritative and serializes temporary-mutex recovery.
   lock_handle=FileOpen(STATE_DIR+"\\executor.lock",FILE_READ|FILE_WRITE|FILE_BIN);
   if(lock_handle==INVALID_HANDLE) { Print("Another bridge owns the executor lock, or storage is unavailable."); return INIT_FAILED; }
   // A temporary variable survives EA reinitialization. Create only if absent.
   // With the exclusive file held, any remaining flag belongs to a departed
   // executor. Recover only this mutex; never change pending/order claim state.
   if((!GlobalVariableCheck(LOCK_NAME) && !GlobalVariableTemp(LOCK_NAME))
      || GlobalVariableSet(LOCK_NAME,0)==0 || !GlobalVariableSetOnCondition(LOCK_NAME,1,0))
   { FileClose(lock_handle); lock_handle=INVALID_HANDLE; Print("Executor mutex unavailable."); return INIT_FAILED; }
   owns_lock=true;
   if(!LoadPending()) { Print("Pending acknowledgement unreadable; manual review required."); return INIT_FAILED; }
   Symbols[0]=EURUSDSymbol;
   Symbols[1]=XAUUSDSymbol;
   for(int i=0;i<2;i++)
      if(!SymbolSelect(Symbols[i],true)) { Print("Required exact symbol unavailable: ",Symbols[i]); return INIT_FAILED; }
   if(!EventSetTimer(PollSeconds)) return INIT_FAILED;
   Print("Prediction bridge initialized. Orders enabled: ",EnableOrders,". Demo identity must match before execution.");
   Print("Exact broker symbols: ",Symbols[0],", ",Symbols[1]);
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(owns_lock) GlobalVariableSetOnCondition(LOCK_NAME,0,1);
   owns_lock=false;
   if(lock_handle!=INVALID_HANDLE) FileClose(lock_handle);
   lock_handle=INVALID_HANDLE;
}
void OnTimer()
{
   if(!owns_lock || !GlobalVariableCheck(LOCK_NAME) || GlobalVariableGet(LOCK_NAME)!=1) return;
   if(!Acknowledge()) return;
   if(halted) return;
   string body=Snapshot(),response;
   if(halted) return;
   if(!Post("/v1/snapshot",body,response) || response=="WAIT") return;
   Execute(response);
   Acknowledge();
}
