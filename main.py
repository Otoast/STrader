from ThreadOperations import *

def main():
 
    dto = Diff_Thread_Operations()
    while True:
        thread1 = threading.Thread(target=dto.scanTickerTrendsThread)
        thread2 = threading.Thread(target=dto.tradeWatchlistTickersThread)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()



if __name__ == "__main__":
    main()

