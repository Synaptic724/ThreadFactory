import threading
import cProfile
import pstats


def test():
    print("Test begins")
    print("Lock Acquired")
    print("This is the thread ID " + str(threading.get_ident()))
    x = threading.RLock()
    x.acquire()
    print("Lock Released")
    x.release()
    print("Deadlock")
    x.acquire()
    x.acquire()
    print("Test ends")

test()

# profiler = cProfile.Profile()
# profiler.enable()
#
# # 🔁 Run your test or logic here
# my_buffer.stress_test()
#
# profiler.disable()
#
# # 📊 Print top 30 slowest functions by cumulative time
# stats = pstats.Stats(profiler).sort_stats("cumtime")
# stats.print_stats(30)



testing = threading.Thread(target=test)
testing2 = threading.Thread(target=test)
testing3 = threading.Thread(target=test)
testing4 = threading.Thread(target=test)


testing.start()
testing2.start()
testing3.start()
testing4.start()



