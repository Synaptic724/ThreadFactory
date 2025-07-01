from thread_factory.concurrency.value_types.sync_int import SyncInt

def run_pow_tests():
    print("\n--- SyncInt pow() test combinations ---\n")

    s_base = SyncInt(3)
    s_exp = SyncInt(3)
    s_mod = SyncInt(4)

    print("pow(SyncInt, SyncInt, int):", pow(s_base, s_exp, 4))             # 3**3 % 4 == 3
    print("pow(SyncInt, int, SyncInt):", pow(s_base, 3, s_mod))             # 3**3 % 4 == 3
    print("pow(int, SyncInt, int):", pow(3, s_exp, 4))                       # 3**3 % 4 == 3
    print("pow(int, int, SyncInt):", pow(3, 3, s_mod))                       # 3**3 % 4 == 3
    print("pow(SyncInt, SyncInt, SyncInt):", pow(s_base, s_exp, s_mod))     # 3**3 % 4 == 3
    print("pow(int, SyncInt, SyncInt):", pow(3, s_exp, s_mod))              # 3**3 % 4 == 3

    s_base2 = SyncInt(4)
    s_exp2 = SyncInt(3)
    print("pow(SyncInt, SyncInt, int):", pow(s_base2, s_exp2, 10))          # 4**3 % 10 == 4

if __name__ == "__main__":
    run_pow_tests()
