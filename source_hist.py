from ibapi.contract import Contract
from ibapi.wrapper import EWrapper
from ibapi.client import EClient
from ibapi.common import BarData
from time import sleep
import pandas as pd
import utils
import query

cout = utils.log(__file__,__name__)

class Wrapper(EWrapper):
    def __init__(self,qdate,symbol,currency,database,table,expiry=None,strike=None,right=None,window=None):
        self.Qdate = pd.to_datetime(qdate,format="%d/%m/%Y")
        self.qdate = self.Qdate.strftime("%Y%m%d")+" 23:00:00"
        self.df = pd.DataFrame(columns=["DateTime","Bid","Ask"])
        self.dic = {1:"BID_ASK"}
        self.database = database
        self.table = table
        
        self.c = Contract()
        self.c.symbol = symbol
        self.c.currency = currency
        self.c.exchange = "SMART"
        
        if symbol != "NDX": #If non index
            
            if expiry != None: 
                self.c.secType = "OPT"
                if type(expiry) == str: expiry = pd.to_datetime(expiry,format="%d/%m/%Y")
                self.c.lastTradeDateOrContractMonth = expiry.strftime("%Y%m%d")
                self.c.strike = float(strike)
                self.c.multiplier = 100.
                self.c.right = right
            else:
                self.c.secType = "STK"
                       
            if symbol == "CSCO":
                if self.c.secType == "STK": 
                    self.c.primaryExchange = "NASDAQ"        
                else:
                    self.c.primaryExchange = "CBOE"
                    
        else:
            if expiry != None:
                self.c.primaryExchange = "CBOE"
                self.c.secType = "OPT"
                if type(expiry) == str: expiry = pd.to_datetime(expiry,format="%d/%m/%Y")
                self.c.lastTradeDateOrContractMonth = expiry.strftime("%Y%m%d")
                self.c.strike = float(strike)
                self.c.multiplier = 100.
                self.c.right = right                 
            else:
                self.c.primaryExchange = "NASDAQ"
                self.c.secType = 'IND'
                self.dic = {1:"TRADES"}
             
        self.no_dat = False
        self.window = "1 D" if window == None else window
        self.tmr = utils.watchdog(90,self.timeout)       
        
    def nextValidId(self,orderId:int):
        self.nextValidOrderId = orderId
        self.request(orderId)

    def historicalData(self,reqId:int,bar:BarData):
        if self.c.secType != 'IND':
            row = [bar.date,bar.open,bar.close]
        else:
            row = [bar.date,bar.close,bar.close]
        self.df.loc[len(self.df)] = row
        self.tmr.reset(90)

    def historicalDataEnd(self,reqId:int,start:str,end:str):
        self.end_of_queue()
     
    def check_dates(self,df):
        if len(df[df["Date"]==self.Qdate]) == len(df):
            return df
        else:
            self.no_dat = True
            dfx = df[df["Date"]==df["Date"].unique()[0]].copy()
            dfx["Date"] = self.Qdate
            dfx["Bid"],dfx["Ask"] = 0,0
            return pd.concat([df,dfx],axis=0).reset_index(drop=True)
    
    def check_spot(self,df):
        dfx = df[(df["Bid"]==0)&(df["Ask"]==0)]
        if dfx.empty:
            return df
        else:
            cout.warn(f"{self.c.symbol} - no bids and asks for underlying")
            return pd.DataFrame()
    
    def dummy(self):
        dat = {"Date":self.Qdate,
               "Time":[1600],
               "Bid":[0.],
               "Ask":[0.],
               "Symbol":[self.c.symbol],
               "Currency":[self.c.currency],
               "Strike":[self.c.strike],
               "Expiry":[pd.to_datetime(self.c.lastTradeDateOrContractMonth,format="%Y%m%d")],
               "Type":[self.c.right],
               "Lotsize":[self.c.multiplier]}
        return pd.DataFrame(dat)
    
    def end_of_queue(self):
        app.disconnect()
        self.tmr.terminate()
        if self.df.empty == False:
            df = self.combine_data()
            df = self.check_dates(df)
            if self.c.secType == "STK":
                df = self.check_spot(df)
                if df.empty: return
            query.post(df,self.database,self.table,"append")
            row = list(df[["Symbol","Bid","Ask"]].loc[0])
            cout.info(f"{self.c.secType}, {row[0]}, {row[1]}, {row[2]}, {self.no_dat}")
        elif self.c.secType == "OPT":
            df = self.dummy()
            query.post(df,self.database,self.table,"append")
            cout.info(f"{self.c.symbol} - no bids and asks for contract, posting dummy")
        else:
            cout.info(f"{self.c.symbol} - no bids and asks for underlying, something is wrong")

    def timeout(self):
        cout.warn(f"{self.c.symbol} - no response, disconnecting")
        app.disconnect()
        
    def combine_data(self):
        df = self.df.set_index("DateTime")
        df.index = df.index.str.split("  ",expand=True)
        df = df.reset_index()
        df.columns = ["Date","Time","Bid","Ask"]
        df["Date"] = pd.to_datetime(df["Date"],format="%Y%m%d")
        df["Time"] = df["Time"].str.replace(":","").str[:-2].astype(int)
        df["Symbol"] = self.c.symbol
        df["Currency"] = self.c.currency
        if self.c.secType == "OPT":
            df["Strike"] = self.c.strike
            df["Expiry"] = pd.to_datetime(self.c.lastTradeDateOrContractMonth,format="%Y%m%d")
            df["Type"] = self.c.right
            df["Lotsize"] = self.c.multiplier
        return df

    def error(self, reqId, errorCode, errorString):
        if errorCode == 200: print(errorString)
        if errorCode in [321,200]: app.disconnect()
        if errorCode == 162:
            if "Bid" in errorString:
                self.no_bid = True
                self.end_of_queue()       
            elif "Ask" in errorString:
                self.no_ask = True
                self.end_of_queue()  
            else:
                cout.warn(f"{errorCode}:{errorString}")
                app.disconnect()

    def request(self,reqId):
        sleep(1)
        app.reqHistoricalData(reqId,self.c,self.qdate,self.window,"10 mins",self.dic[reqId],1,1,False,[])

class QuotesReq:
    def __init__(self,qdate,symbol,currency,window):
        self.qdate = qdate
        self.symbol = symbol
        self.currency = currency
        self.window = window
        
    def equities(self,database="Quotes",table="Spot"):
        global app
        app = EClient(Wrapper(self.qdate,self.symbol,self.currency,database,table,window=self.window))
        app.connect(host="127.0.0.1",port=4001,clientId=123)
        app.run()        

    def options(self,expiry,strike,right,database="Quotes",table=None):
        table = self.symbol if table == None else table
        global app
        app = EClient(Wrapper(self.qdate,self.symbol,self.currency,database,table,expiry,strike,right,self.window))
        app.connect(host="127.0.0.1",port=4001,clientId=123)
        app.run()
        
