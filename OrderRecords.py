from AllImports import *
class OrderRecordsClient:
    API_KEY = API_KEY_AL
    SECRET = SECRET_AL
    title_rows = ["date", "operation_done", "ticker", "amount", "uuid", "additional_info"]
    client = None
    def __init__(self) -> None:
        abspath = os.path.abspath(__file__)
        dname = os.path.dirname(abspath)
        os.chdir(dname)
        os.makedirs("ORDER_RECORDS", exist_ok=True)
        os.chdir("ORDER_RECORDS")
        self.client = TradingClient(self.API_KEY, self.SECRET)

    def record_order(self, signal, uuid):
        response = self.client.get_order_by_client_id(uuid)
        order_type = response.side.name
        ticker = response.symbol
        date = response.created_at
        amount = response.notional
        reason = signal['REASON']
        self._write_order_entry(date, order_type, ticker, amount, uuid, reason)
    
    def _write_order_entry(self, date, order_type, ticker, amount, uuid, reason):
        entry = [date, order_type + " STOCK BECASUE " + reason, ticker, amount, uuid]
        self._create_OR_file(date=date.date())
        with open (f"{date.date()}OR.csv", 'a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(entry)
    
    def _create_OR_file(self, date):
            """ 
                Creates a new log file if one doesn't previously exist.
            """
            if not os.path.exists(f"{date}OR.csv"):
                with open(f"{date}OR.csv", 'w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(self.title_rows)
            all_files = os.listdir()
            if len(all_files) > 7:
                oldest_date = datetime.datetime.today() - datetime.timedelta(days=7)
                oldest_date = oldest_date.date()
                try:    os.remove(f"{oldest_date}OR.csv")
                except  FileNotFoundError:   pass

    def record_watchlist_change(self, date, operation_done, ticker):
            entry = [date, operation_done, ticker, "N/A", "N/A", "N/A"]
            self._create_OR_file(date)
            with open (f"{date.date()}OR.csv", 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(entry)
    
    def did_order_at_date(self, date, ticker):
        file = None
        try:
            file = open(f"{date}OR.csv", "r", newline='')
        except FileNotFoundError:
            return False
        
        reader = csv.reader(file)
        for line in reader:
            if line[2] == ticker and "BUY STOCK" in line[1]:    
                return True
        return False

    def did_order_since_date(self, date, ticker):
        days_since = (datetime.date.today() - date).days
        dates = [date + timedelta(days=i) for i in range(days_since + 1)]
     
        return any([self.did_order_at_date(d, ticker) for d in dates])

        

        
