from AllImports import *

class SyncTickerVars:
    limit_queries = 0
    already_queried_tickers = dict()
    SYNC_LOCK = threading.Lock()
    remaining_keys = list()
    current_api_key = str()
    client_alpaca = None
    client_polygon = None
    
    @staticmethod
    def initialize_clients():
        stv = SyncTickerVars
        stv.client_alpaca = StockHistoricalDataClient(API_KEY_AL, SECRET_AL)
        stv.current_api_key = API_KEYS_POL[0]
        stv.client_polygon = RESTClient(api_key=API_KEYS_POL[0])
        stv.remaining_keys = API_KEYS_POL[:] if len(API_KEYS_POL) == 1 else API_KEYS_POL[1:]
    @staticmethod
    def rotate_api_keys():
        sv = SyncTickerVars
        sv.remaining_keys.append(sv.current_api_key)
        sv.current_api_key = sv.remaining_keys.pop(0)
        sv.client_polygon = RESTClient(api_key=sv.current_api_key)
    @staticmethod
    def increment_queries():
        stv = SyncTickerVars
        with stv.SYNC_LOCK:
            stv.limit_queries += 1
            print("INCREMENTED. AMOUNT DONE:", stv.limit_queries)
            max_queries = 5 * len(API_KEYS_POL)
            if stv.limit_queries % (max_queries + 1) == max_queries:
                print("GOING TO SLEEP")
                time.sleep(60)
                stv.limit_queries = 0
            elif stv.limit_queries % 5 == 0:
                print("ROTATING API KEYS")
                stv.rotate_api_keys()
         

    @staticmethod
    def add_TickerData(ticker, ticker_data):
        with SyncTickerVars.SYNC_LOCK:
            SyncTickerVars.already_queried_tickers.update({ticker : {'DATE' : datetime.datetime.today().date(), 'DATA' : ticker_data}})
            print("ADDED TICKER CACHE:", ticker)

    @staticmethod
    def retrieve_TickerData(ticker:str):
        ticker_data = SyncTickerVars.already_queried_tickers.get(ticker, None)
        if ticker_data == None:
            raise LookupError(f"No such data found for ticker: {ticker}")
        data_date = ticker_data['DATE']
        today = datetime.datetime.today().date()
        if today != data_date:
            raise LookupError(f"Outdated data for ticker: {ticker}")

        return ticker_data['DATA']
    @staticmethod
    def remove_TickerData(ticker:str):
        with SyncTickerVars.SYNC_LOCK:
            response = SyncTickerVars.already_queried_tickers.pop(ticker, None)
            if response == None:
                raise KeyError("No such key found")
    @staticmethod
    def clear_cache():
        SyncTickerVars.already_queried_tickers.clear()
    
class TickerData:    
    BUY = 'BUY'
    SELL = 'SELL'
    HOLD = 'HOLD'
    TRENDING = 'TRENDING'
    OVERBOUGHT = 'OVERBOUGHT'
    OVERSOLD = 'OVERSOLD'
    FAILED_REVERSAL = 'FAILED_REVERSAL'
    DEAD_TREND = 'DEAD_TREND'
    BAD_CHECK = 'BAD_CHECK'

    L_STOC_BOUND = 20
    H_STOC_BOUND = 80
    L_MFI_BOUND = 15
    H_MFI_BOUND = 80
    L_SMI_BOUND = -55
    H_SMI_BOUND = 50
    H_PER_B_BOUND = 103
    L_PER_B_BOUND = 0
    def __init__(self, ticker, multiplier, timespan, from_, to, limit=50000):
        self.ticker = ticker;   self.multiplier = multiplier;      self.timespan = timespan
        try:
            self.data = SyncTickerVars.retrieve_TickerData(ticker)
            return
        except LookupError:
            pass
        SyncTickerVars.increment_queries()
        self.data = SyncTickerVars.client_polygon.get_aggs(ticker=ticker, multiplier=1, timespan=timespan, from_= from_, to=to, limit=limit)
        if len(self.data) == 0: raise RuntimeError("Nothing found for ticker")
        # Confirm that the most recent bar is the date for today. If not it needs to estimate new pricing
        most_recent_agg_date = datetime.datetime.fromtimestamp(self.data[-1].timestamp / 1000, datetime.timezone.utc).date()
        if (most_recent_agg_date == datetime.datetime.today().date()):
            return
        
        # Requesting Alpaca Data for today and yesterday, so we can estimate Polygon's next entry       
        current_bar = SyncTickerVars.client_alpaca.get_stock_latest_bar(request_params=StockLatestBarRequest(symbol_or_symbols=ticker))
        if current_bar[ticker].timestamp.date() != datetime.datetime.today().date(): return # If today isn't a stock trading day then we have the full data already. No need to predict future data
        
        end_date = datetime.datetime.now() - timedelta(days=1)
        start_date = end_date - timedelta(days=30) # Happens if worst case a 2week holiday occurs (idk the market typical times)
        request_params = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=end_date
        )

        bars = SyncTickerVars.client_alpaca.get_stock_bars(request_params=request_params)
        if len(bars[ticker]) < 2:   raise RuntimeError("Could not get alpaca stock data") # If there are less than 2 data points no point in even trying to calculate. Something went wrong with retrieving alpaca data, cannot confirm current data
        yesterday = bars[ticker][-1]
        today = current_bar[ticker]

        # # Next have to estimate the increase for open, high, low close
        new_entry = deepcopy(self.data[-1])

        safe_div = lambda x, y: x / y if y != 0 else 0
        is_actual_value = lambda x: x is not None and x != 0 # For some reason theres a chance for one of the aggs to be a NoneType, this is best option to get accurate enough data. Might need to check for any NoneType in any of the data for some weird reason
        new_entry.open = (new_entry.open * safe_div(today.open, yesterday.open)) if is_actual_value(new_entry.open) else today.open 
        new_entry.high = new_entry.high * safe_div(today.high, yesterday.high) if is_actual_value(new_entry.high) else today.high 
        new_entry.low = new_entry.low * safe_div(today.low, yesterday.low) if is_actual_value(new_entry.low) else today.low
        new_entry.close = new_entry.close * safe_div(today.close, yesterday.close) if is_actual_value(new_entry.close) else today.close
        
        new_entry.volume = new_entry.volume * safe_div(today.volume, yesterday.volume) if is_actual_value(new_entry.volume) else today.volume
        new_entry.vwap = new_entry.vwap * safe_div(today.vwap, yesterday.vwap) if is_actual_value(new_entry.vwap) else today.vwap
        new_entry.timestamp = int(today.timestamp.timestamp() * 1000) 
        self.data.append(new_entry)

        # # Should now have somewhat complete data up to the current day (if possible)
    def get_close_prices(self):
        return [x.close for x in self.data]
    def delete_cache(self):
        try:
            SyncTickerVars.remove_TickerData(self.ticker)
        except KeyError:    pass

    def save_cache(self):
        SyncTickerVars.add_TickerData(self.ticker, self.data)
    
    @staticmethod    
    def get_EMA_static(input, periods=3):
        data = input[:]
        init_MA = sum(data[:periods]) / periods
        multiplier = 2 / (periods + 1)
        eMA = list()
        eMA.append(init_MA)
        for curr_day in range(periods, len(data)):
            previousDay = eMA[-1] # So it appropiately gets the right data
            eMA_current =  data[curr_day] * multiplier + previousDay * (1 - multiplier)
            eMA.append(eMA_current)
        return np.array(eMA)
    @staticmethod
    def get_SMA_static(input, periods=3):
        if periods <= 0: raise RuntimeError("Bad period")
        return np.array(
            [sum(input[i - periods : i]) / periods for i in range(periods, len(input))]
        )
    @staticmethod
    def create_signal(signal_type=None, reason=None):    return {'SIGNAL' : signal_type, 'REASON' : reason}

    def get_EMA(self, periods=3):
        init_MA = sum(self.data[i].close for i in range(periods)) / periods
        multiplier = 2 / (1 + periods)
        eMA = list()
        eMA.append(init_MA)
        for curr_day in range(periods, len(self.data)):
            previousDay = eMA[-1]
            eMA_current =  (self.data[curr_day].close) * multiplier + previousDay * (1 - multiplier)
            eMA.append(eMA_current)
        return np.array(eMA)
    def get_MACD(self, standardized=False):
        """
            Fetches the MACD of the data, along with its respective signal line. Ordered from newest to oldest.
            If standardized is set to true, a % (range 0 to 1) change version of the macd will be return
            Returns: dict of lists with keys {MACD, SIGNAL}   
        """
        #For the 9day EMA
        eMA_12 = self.get_EMA(periods=12)
        eMA_26 = self.get_EMA(periods=26)
        macd =  list()
        for item12, item26 in zip(reversed(eMA_12), reversed(eMA_26)):
            macd.append(item12 - item26) # Would be ordered from newest to oldest
        macd.reverse() # Reverses back from oldest to newest

        if standardized:
            # Need data to be ordered from newest to oldest so that the important data points are kept
            data = self.get_close_prices()
            macd = [x / y for x, y in zip(reversed(macd), reversed(data))]
            macd.reverse() # Reverses back from oldest to newest 
        
        # The reason it needs to be sorted from oldest to newest is so that signal can be properly calculated
        init_MA = sum(macd[i] for i in range(9)) / 9
        multiplier = 2 / 10
        signal_EMA = list()
        signal_EMA.append(init_MA)
        for i in range(9 + 1, len(macd)):
            previousDay = i - 9 - 1
            previousDay = signal_EMA[previousDay]
            eMA_current =  (macd[i] - previousDay) * multiplier + previousDay
            signal_EMA.append(eMA_current)
        

        d = {'MACD' : np.array(macd[::-1]), 'SIGNAL' : np.array(signal_EMA[::-1])}
        return d
    def get_stochastics(self, periods=14):
        """
            Returns the stocasthics of the data given a particular period. Ordered from newest to oldest
            
            Returns: dict of lists with keys {PER_K, PER_D}
        """
        per_k = list()
        per_d = list()
        while (index < len(self.data)):
            prev_n_high = max(self.data[index - periods : index][i].high for i in range(periods))
            prev_n_low = min(self.data[index - periods : index][i].low for i in range(periods))
            curr_close = self.data[index - 1].close
            per_k.append(100 * (curr_close - prev_n_low) / (prev_n_high - prev_n_low))
            index += 1
        for i in range(3, len(per_k)):
            per_d.append(sum(per_k[i - 3 : i]) / 3)
        
        return {'PER_K' : np.array(list(reversed(per_k))), 'PER_D' : np.array(list(reversed(per_d)))}
    def get_ROC(self, periods=9):
        """
            Returns the rate of change given the time period, newest data first.
            Returns: list of rate of change
        """
        roc = list()
        for i in range(periods + 1, len(self.data)):
            pr_now = self.data[i].close
            pr_before = self.data[i - periods - 1].close
            roc.append((pr_now - pr_before) / pr_before)
        return np.array(roc[::-1])
    @staticmethod
    def _get_MFR(rmf_list):

        positive_flow = sum(x for x in rmf_list if x > 0)
        negative_flow = sum(-x for x in rmf_list if x < 0)
        
        if negative_flow == 0: return 2147483640 # basically int32 max but with a few digits removed, same premise

        return positive_flow / negative_flow
    
    def get_MFI(self, periods=14):
        typical_price_list = [(entry.high + entry.low + entry.close) / 3 for entry in self.data]
        volumes_list = [entry.volume for entry in self.data]
        rmf = [typical_price_list[i] * volumes_list[i] for i in range(len(typical_price_list))]

        rate_change = list()
        for i in range(1, len(rmf)):
            val = typical_price_list[i] - typical_price_list[i - 1]
            if val > 0:         rate_change.append(rmf[i])
            elif val < 0:   rate_change.append(-rmf[i])
            else:           rate_change.append(0)
        mfi = [
            (100 - (100 / (1 + TickerData._get_MFR(rate_change[i : i + periods])))) for i in range(0, len(rmf) - periods)
        ]
        return np.array(list(reversed(mfi)))
    @staticmethod 
    def get_double_EMA(data, periods=3):
        ema = TickerData.get_EMA_static(data, periods=periods)
        double_ema = TickerData.get_EMA_static(ema, periods=periods)
        dema = [2 * a - b for a, b in zip(reversed(ema), reversed(double_ema))]
        return list(reversed(dema))
        
    def get_SMI(self, periods=14):
        relative_range = list()
        high_low_range = list()
        for i in range(len(self.data) - periods + 1):
            hh = max(x.high for x in self.data[i : i + periods])
            ll = min(x.low for x in self.data[i: i + periods])
            relative_range.append(self.data[i + periods - 1].close - (hh + ll) / 2)
            high_low_range.append(hh - ll)
        ema = TickerData.get_EMA_static
        relative_range = ema(ema(relative_range))
        high_low_range = ema(ema(high_low_range))
        smi = [200 * relative_range[i] / high_low_range[i] for i in range(len(relative_range))]
        signal = ema(smi, periods=10)
        return {'SMI' : np.array(list(reversed(smi))), 'SIGNAL' : np.array(list(reversed(signal)))}


    # Look for if previous signal was a buy or sell signal
    def get_hist_volatility(self, periods=10):
        hist_volatility = []
        for i in range(periods, len(self.data)):
            cl_prices = [x.close for x in self.data[i - periods : i]]
            inter_day = np.array([np.log(cl_prices[j] / cl_prices[j - 1]) for j in range(1, len(cl_prices))])
            curr_price = self.data[i].close
            hist_volatility.append(inter_day.std() * np.sqrt(252) * 100)
        return np.array(list(reversed(hist_volatility)))
    
    def get_bollinger_per_b(self, periods=20):
        """
            Provides bollinger bands and addtionally calculates %B.
        """
        data = np.array(self.get_close_prices())
        upper_line, lower_line,  center_line, per_b = [],[],[],[]
        for i in range(periods, len(data) + 1):
            n_days_data = data[i - periods: i]
            sma = n_days_data.mean()
            std = n_days_data.std()
            center_line.append(sma)
            upper_line.append(sma + 2 * std);   lower_line.append(sma - 2 * std)
            
            b = 100 * (n_days_data[-1] - lower_line[-1]) / (upper_line[-1] - lower_line[-1]) 
            per_b.append(b)

        d = {
            'UPPER_BAND' : np.array(upper_line[::-1]),
            'LOWER_BAND' : np.array(lower_line[::-1]),
            'CENTER_BAND' : np.array(center_line[::-1]),
            '%B' : np.array(per_b[::-1])
        }
        return d

    def get_previous_signal(self,  absolute=True):
        """
            Gets the previous basic BUY/SELL signal from the get_current_signal function. Does not check for failed reversals.
            
            absolute: Defaults to True. Toggles whether the signal returned is from the very first instance of the previous signal, or the very last.
                Ex: If for the past 5 days there has been a sell signal, it will return the absolute first time that signal was raised of the five. If not, it just returns the most current signal.
        """
        signal = TickerData.create_signal()
        temp_data_holder = []
        signal_index = -1
        data_len = len(self.data)
        try:
            while signal['SIGNAL'] not in [TickerData.BUY, TickerData.SELL]:
                signal_index += 1
                signal = self.get_current_signal()
                # print("NEW SIGNAL INDEX:", signal_index, " | ", signal)
                temp_data_holder.insert(0, self.data.pop())
        except IndexError:
            self.data = self.data + temp_data_holder
            return TickerData.create_signal(), -1
        try:
            if absolute:
                # print("Going back as far as possible.")
                temp = signal.copy()
                while temp == signal:
                    temp = self.get_current_signal()
                    # print("EARLIER SIGNAL INDEX:", signal_index, " | ", temp)
                    temp_data_holder.insert(0, self.data.pop())
                    signal_index += 1
        except IndexError:
            pass

        signal_index -= 1
        signal_index = signal_index if signal != -1 else 0
        # print("Final signal chosen:", signal)
        self.data = self.data + temp_data_holder
        return signal, signal_index
            
    def _is_trending(self):
        recent_n_periods = 10
        STD_TOL = .05
        SLOPE_TOL = .07
        MEAN_TOL = .03
        # Gets close data, calculates the 7-day sma of the last half of it, and turns it to a numpy array.
        recent_slope = np.array(self.get_SMA_static(self.get_close_prices()[:int(len(self.data) / 2)], periods = 7)) 
        recent_slope = np.diff(recent_slope)[-recent_n_periods:]
        recent_macd = TickerData.get_EMA_static(self.get_MACD(standardized=True)['SIGNAL'][::-1]) # Simple moving average starting at oldest datapoints--after resorts by new
        recent_macd = recent_macd[-recent_n_periods:]
        if (recent_slope.mean() > SLOPE_TOL and recent_slope.std() < STD_TOL and recent_macd.mean() > MEAN_TOL):   return True
        return False
    
    def get_current_signal(self):
        """
            Checks stock data to see whether criteria matches for buying/selling stocks. Checks for:
                - Steady upward trending of stock
                - Oversold/Overbought condtions based on determined criteria
            To check for a sell signal due to a failed reversal, please use the check_failed_reversal(). 
            To check for a previous signal, use the get_previous_signal() method.
            
            Parameters: None
            Retruns: {'SIGNAL' : SignalType, 'REASON' : ReasonType}
            SignalType options: BUY, SELL, HOLD
            ReasonType options: OVERBOUGHT, OVERSOLD, TRENDING
        """
 
        # Step 1: Check if the stock is having a slow upward trend, via checking low volaility and macd
        if (self._is_trending()):
            return TickerData.create_signal(TickerData.BUY, TickerData.TRENDING)
        # If not trending, then checks to see if stock is overbought or oversold
        mfi = self.get_MFI(periods=10)
        smi = self.get_SMI(periods=30)
        signal = smi['SIGNAL']
        smi = smi['SMI']
        bb_per_b = self.get_bollinger_per_b()['%B']
        
        curr_bb = bb_per_b[0];      curr_mfi = mfi[1]
        curr_smi = smi[0];          curr_signal = signal[0]
        if (not curr_bb < TickerData.L_PER_B_BOUND and curr_mfi < TickerData.L_MFI_BOUND and curr_smi < TickerData.L_SMI_BOUND):
            return TickerData.create_signal(TickerData.BUY, TickerData.OVERSOLD)
        elif (curr_bb > TickerData.H_PER_B_BOUND and curr_smi > TickerData.H_SMI_BOUND):
            if curr_signal > curr_smi:  return TickerData.create_signal(TickerData.SELL, TickerData.DEAD_TREND)
            else:                   return TickerData.create_signal(TickerData.SELL, TickerData.OVERBOUGHT)
        return TickerData.create_signal(TickerData.HOLD, TickerData.TRENDING)

    def check_failed_reversal(self):
        """
            Checks if a stock failed to have a reversal. For a failed reversal to have occured:
                - A previous BUY/SELL signal occured
                - From that signal onward, there was a double crossover found in the rest of the data
            Parameters: None
            Returns: {'SIGNAL': SignalType, 'REASON' : ReasonType}
            SignalType options: SELL, HOLD
            ReasonType options: DEAD_TREND, FAILED_REVERSAL, TRENDING
        """
        signal, index = self.get_previous_signal()
        if (index == 0): return TickerData.create_signal(TickerData.HOLD, TickerData.TRENDING)
        if signal['SIGNAL'] == TickerData.BUY:
            signal = self._check_B(index)
        elif signal['SIGNAL'] == TickerData.SELL:
            signal = self._check_S(index)

        return signal

    def _check_S(self, index):
        
        smi = self.get_SMI(periods=30)
        signal = smi['SIGNAL'][0 : index + 1][::-1] # Gets data points from signal to present time
        smi = smi['SMI'][0 : index + 1][::-1]
        per_b = self.get_bollinger_per_b()['%B'][0 : index + 1][::-1]

        # Finds index where %B exceeds high bound
        i = 0
        not_found = True
        while i < len(per_b): 
            if i < TickerData.H_PER_B_BOUND:    i += 1
            else:   not_found = False;   break

        # If %B is still below the bound, should check for smi going below a certain threshold since recieving the sell signal.
        # If it doesn't then, stock is fine
        if not_found:
            if (any([x <= 20 for x in smi])):
                return TickerData.create_signal(TickerData.SELL, TickerData.DEAD_TREND)
            else:
                return TickerData.create_signal(TickerData.HOLD, TickerData.TRENDING)
        
        # Executes if %B goes beyond the threshold, checks to see if at any point smi goes under the signal.
        # If it does, sends a sell signal for an imminent trend reversal. If not found, stock is fine.
        remaining_smi = smi[i:]
        remaining_signal = signal[i:]
        smi_below_signal = any([smi_val < signal_val for smi_val, signal_val in zip(remaining_smi, remaining_signal)])
        if smi_below_signal:
            return TickerData.create_signal(TickerData.SELL, TickerData.DEAD_TREND)
        else:
            return TickerData.create_signal(TickerData.HOLD, TickerData.TRENDING)
    
    def _check_B(self, index):
        smi = self.get_SMI(periods=30)
        signal = smi['SIGNAL'][0 : index + 1][::-1]
        smi = smi['SMI'][0 : index + 1][::-1]

        # Does div by 5 in case H_SMI_BOUND is changed (so its relative) MAYBE CHANGE LATER
        # If it goes above a certain value then it'll check if from that point onward the smi dropped to a critical value. If not then the stock will ride.
        # If the stock does go down to a critical value, it will signify to sell.
        # IF it never goes above a particular value then the next line of code will execute
        high_smi_bound = TickerData.H_SMI_BOUND - TickerData.H_SMI_BOUND / 5             
        for i in range(len(smi)):
            if smi[i] > high_smi_bound:
                remaining_smi = smi[i:]
                if any([x < 15 for x in remaining_smi]):  
                    TickerData.create_signal(TickerData.SELL, TickerData.FAILED_REVERSAL) 
                else: return TickerData.create_signal(TickerData.HOLD, TickerData.TRENDING)
     

        # Checks from initial signal point whether a double crossover happened
        crossover = False
        for i in range(len(smi)):
            smi_val = smi[i]
            signal_val = signal[i]
            if (smi_val > signal_val and not crossover):   crossover = True
            elif (smi_val < signal_val and crossover):
                return TickerData.create_signal(TickerData.SELL, TickerData.FAILED_REVERSAL) 
        return TickerData.create_signal(TickerData.HOLD, TickerData.TRENDING)
        
    def _process_SMI_extremas(self):
        smi = self.get_SMI(periods=30)['SMI'][::-1]
        extremas = []
        i = 0 
        while i < len(smi):
            if smi[i] > 40:
                extremas.append(0)
                while i < len(smi) and smi[i] > 40:
                    extremas[-1] += 1
                    i += 1
            elif smi[i] < -40:
                extremas.append(0)
                while i < len(smi) and smi[i] < -40:
                    extremas[-1] -= 1
                    i += 1
            else: i += 1

        return np.array(extremas)
    
