
from TickerData import *
from StockTrader import *
from AllImports import *

class Diff_Thread_Operations:
    watchlist_id = None
    watchlist_name = "MAIN_WATCHLIST"
    all_tickers = list()
    stock_trader_client = None
    client_trading = None
    DTO_LOCK = threading.Lock()

    def __init__(self) -> None:
        while True: # Should run this code even if internet is lost.
            try:
                SyncTickerVars.initialize_clients()   
                self.stock_trader_client = StockTraderClient()
                self.client_trading = TradingClient(API_KEY_AL, SECRET_AL, paper=True)
                assets = self.client_trading.get_all_assets()
                self.all_tickers = [asset.symbol for asset in assets if (
                    asset.tradable and asset.exchange in ['NASDAQ', 'NYSE'])]
                shuffle(self.all_tickers)
                self._retrieve_watchlist()
                return
                
            except ConnectionError:
                print("Lost Internet or some Internet error")
                time.sleep(5)
#            except BaseException as e:
#                print("Unhandled Exception occured:", str(e))
                
        
    def _retrieve_watchlist(self):
        watchlists = self.client_trading.get_watchlists()
        names = [x.name for x in watchlists]
        if self.watchlist_name not in names:
            wl = CreateWatchlistRequest(name=self.watchlist_name, symbols=[])
            response = self.client_trading.create_watchlist(wl)
            self.watchlist_id = response.id
        else:
            self.watchlist_id = next(x.id for x in watchlists if x.name == self.watchlist_name)
    
    def add_to_watchlist(self, ticker:str):
        all_wl_tickers = [x.symbol for x in self.client_trading.get_watchlist_by_id(self.watchlist_id).assets]
        with self.DTO_LOCK:
            if ticker not in all_wl_tickers:
                self.client_trading.add_asset_to_watchlist_by_id(self.watchlist_id, ticker)

    def remove_from_watchlist(self, ticker:str):
        all_wl_tickers = [x.symbol for x in self.client_trading.get_watchlist_by_id(self.watchlist_id).assets]
        with self.DTO_LOCK: 
            if ticker in all_wl_tickers:
                self.client_trading.remove_asset_from_watchlist_by_id(self.watchlist_id, ticker)
    

    def scanTickerTrendsThread(self): # To allow for exception handling outside of the thread itself.
        while True:
            try:
                self._scanTickerTrends()
            except (ConnectionError, MaxRetryError):
                print("Lost Connection in Thread-1. Going to sleep until is fixed.")
                time.sleep(5)
            except Exception as e:
                print("Issue caused THREAD-1 to terminate:", str(e))
    def _scanTickerTrends(self):
        today = date.today()
        n_months_ago = today - relativedelta(months=12)
        days = 7
        min_bars_needed = 252 / 2
        watchlist = self.client_trading.get_watchlist_by_id(watchlist_id=self.watchlist_id).assets
        watchlist = [x.symbol for x in watchlist if x.tradable]
        self.all_tickers = watchlist + [x for x in self.all_tickers if x not in watchlist]

        while True:
            print("IN THREAD-1")
            ticker = self.all_tickers.pop(0)
            with self.DTO_LOCK:  self.all_tickers.append(ticker) # Should move the ticker to back of the line
            ticker_data = None
            # If the ticker isn't tradable no point in doing anything else
            # Attempts to get ticker data. If no data found or specific error occurs, will continue. Otherwise should terminate program
            try:
                if not self.stock_trader_client.client_trading.get_asset(ticker).tradable: continue
                print("JUST POPPED TICKER:", ticker)
                ticker_data = TickerData(ticker, 1, "day", n_months_ago, today)
            except APIError as e:
                if "no bar found for" in str(e) or "asset not found for" in str(e): continue
                else: raise e
            except RuntimeError as e:
                continue
         
            print("Length of ticker_data:", len(ticker_data.data))
            if len(ticker_data.data) < min_bars_needed: # There isn't at least half a year's worth of information
                continue

            # First need to look at MACD. Should have a slightly above neutral moving average (above 0) so that 
            macd = ticker_data.get_MACD(standardized=True)
            signal = macd['SIGNAL']
            total_median_macd = np.median(signal[days:])
            current_median_macd = np.median(signal[:days])
            percent_above_zero = len([x for x in signal if x > 0]) / len(signal)
            volume = np.median(np.array([x.volume for x in ticker_data.data]))
            macd_conditions = volume >= 50000 and total_median_macd > 0 and current_median_macd - total_median_macd > -.04 and percent_above_zero > .50
            
            # Next need to look at the SMI, and see if it is faborable enough to continue investing in
            smi = ticker_data.get_SMI(periods=30)['SMI']
            extremas = ticker_data._process_SMI_extremas() # The Oversold and Overbought periods and how many days they lasted
            periods_above = np.array([x for x in extremas if x > 0])
            periods_below = np.array([-x for x in extremas if x < 0])

            pa_mean = periods_above.mean() if len(periods_above) != 0 else 0
            pb_mean = periods_below.mean() if (len(periods_below) != 0 and periods_below.mean() >= .005) else .01 # Just to be safe in case something occurs

            ratio_duration_above_below = pa_mean / pb_mean # Ratio of average length of overbought conditions vs oversold
            
            ratio_above_below = len(periods_above) / len(periods_below) if len(periods_below) != 0 else 999 # Times above should be happening as often as times below
            percent_extreme = (sum(periods_above) + sum(periods_below)) / len(smi) # Should always be in extreme boundaries as much as possible. If SMI is ever zero there's a bigger problem with a code. 
            
            num_failed_reversals = [extremas[i - 1] < 0 and extremas[i] < 0 for i in range(1, len(extremas))]
            num_failed_reversals = len([x for x in num_failed_reversals if x])
            ratio_failed = num_failed_reversals / len(periods_below) if len(periods_below) != 0 else 0 # There can't be failed reversals if there are no oversold periods
            smi_conditions = ratio_above_below > .6 and percent_extreme > .40 and ratio_failed < .50 and ratio_duration_above_below > .5
            
            if (macd_conditions and smi_conditions):
                self.add_to_watchlist(ticker)
                ticker_data.save_cache()
                print("ADDED TO WATCHLIST")
            else:   
                self.remove_from_watchlist(ticker)
                print("DID NOT MATCH CRITERIA")
            if self.client_trading.get_clock().is_open: # Need the second thread to be more active than the first one
                time.sleep(1.5)

    def tradeWatchlistTickersThread(self): # To allow for exception handling outside of the method itself
        while True:
            try:
                self._tradeWatchlistTickers()
            except (ConnectionError, MaxRetryError):
                print("Lost Connection in Thread-2. Going to sleep until is fixed.")
                time.sleep(5)
#            except Exception as e:
#                print("Issues casued THREAD-2 to temrinate:", str(e))
    def _tradeWatchlistTickers(self):   
        while True:
            print("IN THREAD-2")
            market_time_info = self.client_trading.get_clock()
            if not market_time_info.is_open: # Should only make trades when the market is open. Otherwise, sleep until open martket
                next_open = market_time_info.next_open.astimezone()
                now = datetime.datetime.now().astimezone()
                print("Market is closed. Sleeping until:", next_open.date())
                time.sleep((next_open - now).total_seconds())
                SyncTickerVars.clear_cache() # Don't want old data when market opens
                continue
            with self.DTO_LOCK:  watchlist = self.client_trading.get_watchlist_by_id(watchlist_id=self.watchlist_id).assets
            watchlist = [x.symbol for x in watchlist if x.tradable]
            
            # Need to put the symbols that are being traded as more important priority. Will do so by just making those tickers a second or third time. Shouldn't be too taxing since ticker_data being cahced
            traded_tickers = [x.symbol for x in self.client_trading.get_all_positions()]
            traded_tickers.extend(traded_tickers + traded_tickers)
            watchlist.extend(traded_tickers)
            shuffle(watchlist)

            # Goes through entire watchlist and then sleeps. Does this in case the watchlist gets updated, the reset allows for new tickers to be added.
            while (len(watchlist) > 0):
                print("IN THREAD-2")
                ticker = watchlist.pop(0)
                self._trade_stock(ticker)
            print("Finished scanning. Going to sleep!")
            SyncTickerVars.clear_cache() # So that the traded data is still being somewhat fresh
            time.sleep(300)  # Don't want to continuously query the api for useless reasons
           
    
    def _trade_stock(self, ticker:str):
        print("Trading stock for ticker:", ticker)
        today = date.today()
        n_months_ago = today - relativedelta(months=12)
        ticker_data = None
        records_client = self.stock_trader_client.records_client
        did_order_already = records_client.did_order_since_date(date=today - timedelta(days=5), ticker=ticker)
        
        try:
            ticker_data = TickerData(ticker, 1, "day", n_months_ago, today)
        except APIError as e:
            if "no bar found for" in str(e) or "asset not found for" in str(e):   return
            else: raise e
        trade_signal = ticker_data.get_current_signal()

        # Need to make sure a SELL signal was not missed. Would be extremely bad to lose profits becasue of a missed SELL signal. Shouldn't matter as much with a missed BUY SIGNAL
        prev_signal = ticker_data.get_previous_signal()[0] 
        if prev_signal['SIGNAL'] == None:
            print("No signal generated for stock. Skipping")
            return
        print("Signal:", trade_signal['SIGNAL'], "Reason:", trade_signal['REASON'])

        if trade_signal['SIGNAL'] == TickerData.BUY and not did_order_already:
            print("BUYING STOCK")
            self.stock_trader_client.buy_stock(ticker_data, trade_signal)

        elif prev_signal['SIGNAL'] == TickerData.SELL and prev_signal['REASON'] == TickerData.DEAD_TREND:
           print("SELLING STOCK")
           self.stock_trader_client.sell_stock(ticker_data, trade_signal)
        else:
            print("CHECKING STOCK")
            is_good = self.stock_trader_client.check_stock(ticker_data, prev_signal, trade_signal)
            if not is_good:
                print("STOCK IS BAD SELLING STOCK")
                trade_signal = TickerData.create_signal(signal_type=TickerData.SELL, reason=TickerData.BAD_CHECK)
                self.stock_trader_client.sell_stock(ticker_data, trade_signal)
                self.remove_from_watchlist(ticker_data.ticker)
