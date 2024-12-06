from TickerData import *
from OrderRecords import *
from AllImports import *

class StockTraderClient:
    client_trading = None
    MIN_PURCHASE = 100
    MAX_TIMES_BOUGHT = 2
    BASE_PURCHASE_PERCENT = .03
    STOP_LOSS_PERCENT = -.047 # Max percentage allowed to lose
    TRENDING_STOP_LOSS_PERCENT = -.037 #Max Percentage allowed to lose 
    records_client = None

    BAD = 0;    GOOD = 1 
    def __init__(self) -> None:
        self.client_trading = TradingClient(API_KEY_AL, SECRET_AL, paper=True)
        self.records_client = OrderRecordsClient()
    def _get_positions(self, ticker:str):
        positions = self.client_trading.get_all_positions()
        return [pos for pos in positions if (pos.symbol == ticker)]

    def buy_stock(self, ticker_data:TickerData, signal) -> None:
            """
                Purchases some stock given the TickerData. Doesn't check for signals, but does check how many times the stock has been purchased before and sets a limit
                on how much stock can be purchased in totality. Calculates amount bought by minimumPrice * current rate of change / (2 * rate of change st.dev)
                Could possibly add a feature where I can see all the stocks being traded, or if there is a limit overflow sell a stock right now to buy another one
                Returns: None
            """
        
            cash = float(self.client_trading.get_account().equity)
            MAX_PURCHASE = cash / 10 # 10% of buying power is max allowed to buy
            dollar_amt = self.BASE_PURCHASE_PERCENT * cash
            loss_percent = None
            recent_price = ticker_data.data[-1].close
            
            if signal['REASON'] == TickerData.OVERSOLD:
                loss_percent = StockTraderClient.STOP_LOSS_PERCENT        
                multiplier = 1
                smi_extremas = ticker_data._process_SMI_extremas()
                roc = ticker_data.get_ROC(periods=14)
                recent_roc = roc[:3].mean()
                if (recent_roc - roc.mean()) / roc.std() < -2.5: multiplier -= .1
                
                avg_neg_duration = [-x for x in smi_extremas if x < 0]
                negative_len = len(avg_neg_duration)

                avg_neg_duration = sum(avg_neg_duration) / negative_len if negative_len != 0 else 1
                if avg_neg_duration > 25:   multiplier -= .1

                ratio_positive_negative = len([x for x in smi_extremas if x > 0]) / negative_len if negative_len != 0 else 1
                if ratio_positive_negative < .7: multiplier -= .1
                dollar_amt *= multiplier

            elif signal['REASON'] == TickerData.TRENDING:
                loss_percent = StockTraderClient.TRENDING_STOP_LOSS_PERCENT
                multiplier = 1
                roc = ticker_data.get_ROC(periods=14)
                recent_roc = roc[:4].mean()
                if (recent_roc - roc.mean()) / roc.std() > 2.5: multiplier -= .1
                macd_slope = np.diff(ticker_data.get_MACD()['MACD'])
                recent_macd_slope = macd_slope[:4].mean()
                if (recent_macd_slope - macd_slope.mean()) / macd_slope.std() > 2.5: multiplier -= .1
                dollar_amt = dollar_amt * multiplier # Shouldn't be that big of an issue if its slowly trending
            dollar_amt = dollar_amt if dollar_amt < MAX_PURCHASE else MAX_PURCHASE


            ticker_positions = self._get_positions(ticker_data.ticker)
            if len(ticker_positions) < self.MAX_TIMES_BOUGHT:
                total_purchased = sum(float(t.cost_basis) for t in ticker_positions)
                amt_left = MAX_PURCHASE - float(total_purchased)
                if amt_left < self.MIN_PURCHASE:   return # If there's only like $100 worth of stock left there's no point. Just return
                dollar_amt = dollar_amt if amt_left > dollar_amt else amt_left
            else: return # Can maybe add a feature to see if selling a stock to buy another one is possible, just trying to simplify things rn
            
            liquid_cash = float(self.client_trading.get_account().cash)
            if dollar_amt > liquid_cash:  dollar_amt =  liquid_cash / 2
            if dollar_amt < StockTraderClient.MIN_PURCHASE: return
            is_fractionable = self.client_trading.get_asset(ticker_data.ticker).fractionable
            
            if is_fractionable:
                order_details = MarketOrderRequest(
                    symbol=ticker_data.ticker,
                    side=OrderSide.BUY,
                    notional=round(dollar_amt, 2),
                    time_in_force = TimeInForce.DAY
                    )
            else:
                qty = int(dollar_amt / ticker_data.data[-1].close)
                if qty == 0 or ticker_data.data[-1].close > MAX_PURCHASE:    pass # Cant afford the purchase essentially
                order_details = MarketOrderRequest(
                    symbol=ticker_data.ticker,
                    side=OrderSide.BUY,
                    qty=qty,
                    time_in_force = TimeInForce.DAY               
                    )                
            
            order = self.client_trading.submit_order(order_data=order_details)
            self.records_client.record_order(signal, order.client_order_id)
            print("Bought stock:", ticker_data.ticker)

    def check_stock(self, ticker_data:TickerData, prev_signal, signal=None):
        """
            Checks the integrity of the stock being traded. Only looks at bought stock: If a stock hasn't been bought, will return Good (TRUE).
            If an indicator fails, it will be indicated via the return value. Signal is not needed, and will be disregarded if passed.

            PARAMETERS: TickerData, prev_signal, Signal (optional)
            RETURNS: StockTrader.GOOD (True), StockTrader.BAD (False)
        """
        print("Checked stock:", ticker_data.ticker)
        
        # STEP 1: Check if any stock has been bought at all. If not, then no need to proceed
        ticker_positions = self._get_positions(ticker_data.ticker)
        if len(ticker_positions) <= 0:  return self.GOOD 
        print("\tThere's actually bought stock of ticker:", ticker_data.ticker)
        # STEP 2: Check if positions have lost more in total than the tolerated loss amount
        # If the stock was bought previously becasue of a trending signal, should be less tolerant of the max loss percent.
        max_loss_percent = 0
        if prev_signal['SIGNAL'] == TickerData.BUY and prev_signal['REASON'] == TickerData.TRENDING:
            max_loss_percent = self.TRENDING_STOP_LOSS_PERCENT
        else:
            max_loss_percent = self.STOP_LOSS_PERCENT

        percent_GL = list()
        for pos in ticker_positions:
            percent_GL.append(float(pos.unrealized_plpc))
        avg_GL = sum(percent_GL) / len(percent_GL)
        if (avg_GL <= max_loss_percent):               return self.BAD
        print("\tPassed Percent Loss Check")
        # STEP 3: Check if a failed reversal has occured or a trend has reached the end of its lifespan
        signal = ticker_data.check_failed_reversal()
        if (signal['REASON'] == TickerData.FAILED_REVERSAL) or (signal['REASON'] == TickerData.DEAD_TREND):   
            print("Bad stock. Signal['REASON'] is:", signal['REASON'])
            return self.BAD
        print("\tPassed Failed Reversal Check. Stock is Good.")
        return self.GOOD


    def sell_stock(self, ticker_data:TickerData, signal=None):
            """
                Sells all positions of the particular stock. Does a series of checks to verify the integrity of the stock.
                Note that ALL shares will be sold.

                PARAMETERS: TickerData, signal (optional)
                RETURNS: None
            """
            ticker_positions = self._get_positions(ticker_data.ticker)
            ticker_positions = [x.asset_id for x in ticker_positions]
            try:
                for uuid in ticker_positions:
                    response = self.client_trading.close_position(uuid)
                    self.records_client.record_order(signal, response.client_order_id)
                print("Sold stock:", ticker_data.ticker)
            except APIError as e:
                if "insufficient qty available" in str(e): 
                    print("Stock already sold.")
                    pass
                else: raise e
            ticker_data.delete_cache()
