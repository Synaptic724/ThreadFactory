"""
test_sync_bool_full.py
======================

**Mega-suite** for :class:`thread_factory.concurrency.value_types.sync_bool.SyncBool`.

• 100 + test methods
• No third-party deps — pure  *unittest*

Run::

    python -m unittest tests.concurrency.value_types.test_sync_bool_full
"""
from __future__ import annotations
import gc, math, os, pickle, random, sys, threading, time, unittest, multiprocessing as mp
from decimal import Decimal
from fractions import Fraction

from thread_factory.concurrency.sync_types.sync_bool  import SyncBool
from thread_factory.concurrency.sync_types.sync_int   import SyncInt
from thread_factory.concurrency.sync_types.sync_float import SyncFloat


# ──────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────
def _many_threads(fn, n=64):
    threads = [threading.Thread(target=fn) for _ in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()

def _toggle_n(sb, n):
    for _ in range(n): sb.toggle()

def _child(conn, value: SyncBool):
    conn.send(value); conn.close()


# ──────────────────────────────────────────────────────────────
#  big test-suite
# ──────────────────────────────────────────────────────────────
class TestSyncBoolFull(unittest.TestCase):

    # region — construction & coercion (1-15)
    # ----------------------------------------------------------
    def test_01_default_false(self):               self.assertFalse(SyncBool().get())
    def test_02_initial_true(self):                self.assertTrue (SyncBool(True).get())
    def test_03_initial_int1(self):                self.assertTrue (SyncBool(1).get())
    def test_04_initial_int0(self):                self.assertFalse(SyncBool(0).get())
    def test_05_initial_float(self):               self.assertTrue (SyncBool(0.1).get())
    def test_06_initial_empty_str(self):           self.assertFalse(SyncBool("").get())
    def test_07_initial_nonempty_str(self):        self.assertTrue (SyncBool("x").get())
    def test_08_initial_list(self):                self.assertTrue (SyncBool([1]).get())
    def test_09_initial_empty_list(self):          self.assertFalse(SyncBool([]).get())
    def test_10_initial_decimal(self):             self.assertTrue (SyncBool(Decimal(1)).get())
    def test_11_set_true(self):
        s=SyncBool(False); s.set(True);            self.assertTrue (s.get())
    def test_12_set_false(self):
        s=SyncBool(True);  s.set(False);           self.assertFalse(s.get())
    def test_13_toggle_once(self):
        s=SyncBool(False); s.toggle();             self.assertTrue (s.get())
    def test_14_toggle_twice(self):
        s=SyncBool(False); s.toggle(); s.toggle(); self.assertFalse(s.get())
    def test_15_index(self):
        s=SyncBool(True);                          self.assertEqual([0,1][s],1)

    # endregion
    # region — conversion dunders (16-25)
    # ----------------------------------------------------------
    def test_16_int_conversion(self):              self.assertEqual(int(SyncBool(True)),1)
    def test_17_float_conversion(self):            self.assertEqual(float(SyncBool(True)),1.0)
    def test_18_index_conversion(self):            self.assertEqual(SyncBool(True).__index__(),1)
    def test_19_bool_conversion(self):             self.assertTrue(bool(SyncBool(True)))
    def test_20_str_true(self):                    self.assertEqual(str(SyncBool(True)) ,"True")
    def test_21_str_false(self):                   self.assertEqual(str(SyncBool(False)),"False")
    def test_22_repr(self):                        self.assertEqual(repr(SyncBool(True)),"True")
    def test_23_hash_match_true(self):             self.assertEqual(hash(SyncBool(True)), hash(True))
    def test_24_hash_match_false(self):            self.assertEqual(hash(SyncBool(False)),hash(False))
    def test_25_format_d(self):                    self.assertEqual(format(SyncBool(True),"d"),"1")

    # endregion
    # region — equality / comparison (26-35)
    # ----------------------------------------------------------
    def test_26_eq_bool(self):                     self.assertTrue (SyncBool(True)==True)
    def test_27_ne_bool(self):                     self.assertTrue (SyncBool(True)!=False)
    def test_28_eq_int(self):                      self.assertTrue (SyncBool(True)==1)
    def test_29_gt_int(self):                      self.assertTrue (SyncBool(True)>0)
    def test_30_lt_int(self):                      self.assertTrue (SyncBool(False)<1)
    def test_31_ge_self(self): s=SyncBool(True);   self.assertTrue (s>=s)
    def test_32_le_self(self): s=SyncBool(False);  self.assertTrue (s<=s)
    def test_33_eq_other_sync(self):
        self.assertTrue(SyncBool(True)==SyncBool(True))
    def test_34_ne_other_sync(self):
        self.assertTrue(SyncBool(True)!=SyncBool(False))
    def test_35_compare_float(self):
        self.assertTrue(SyncBool(True)>0.5)

    def test_rapid_flip_logic_mix(self):
        sb = SyncBool(True)

        def worker():
            for i in range(10_000):
                if sb.get():
                    sb.set(False)
                else:
                    sb.toggle()
                _ = sb & True
                _ = sb | False

        threads = [threading.Thread(target=worker) for _ in range(64)]

        for t in threads: t.start()
        for t in threads: t.join()

        self.assertIn(sb.get(), (True, False))

    # endregion
    # region — arithmetic forward ops (36-50)
    # ----------------------------------------------------------
    def test_36_add(self):       self.assertEqual(SyncBool(True)+5,6)

    def test_toggle_read_pressure(self):
        sb = SyncBool(False)

        def toggler():  # constant flipping
            for _ in range(500_000):
                sb.toggle()

        def reader():  # constantly reading
            for _ in range(500_000):
                _ = sb.get()

        threads = [threading.Thread(target=toggler) for _ in range(10)] + \
                  [threading.Thread(target=reader) for _ in range(10)]

        for t in threads: t.start()
        for t in threads: t.join()

        # Final state is nondeterministic, just ensure it's still usable
        self.assertIn(sb.get(), (True, False))

    def test_37_sub(self):
        self.assertEqual(SyncBool(True) - 2, -1)
    def test_38_mul(self):       self.assertEqual(SyncBool(True)*3,3)
    def test_39_truediv(self):   self.assertEqual(SyncBool(True)/2,0.5)
    def test_40_floordiv(self):  self.assertEqual(SyncBool(True)//2,0)
    def test_41_mod(self):       self.assertEqual(SyncBool(True)%2,1)
    def test_42_pow(self):       self.assertEqual(SyncBool(False)**0,1)
    def test_43_radd(self):      self.assertEqual(5+SyncBool(True),6)
    def test_44_rsub(self):      self.assertEqual(5-SyncBool(True),4)
    def test_45_rmul(self):      self.assertEqual(3*SyncBool(False),0)
    def test_46_rtruediv(self):  self.assertEqual(6/SyncBool(True),6)
    def test_47_rfloordiv(self): self.assertEqual(6//SyncBool(True),6)
    def test_48_rmod(self):      self.assertEqual(6%SyncBool(True),0)
    def test_49_rpow(self):      self.assertEqual(2**SyncBool(False),1)
    def test_50_zero_div_raises(self):
        with self.assertRaises(ZeroDivisionError): _=5/SyncBool(False)

    # endregion
    # region — bitwise ops (51-65)
    # ----------------------------------------------------------
    def test_51_and_bool(self):  self.assertFalse(SyncBool(False)&True)
    def test_52_or_int(self):    self.assertEqual(SyncBool(True)|5,5)
    def test_53_xor_int(self):   self.assertEqual(SyncBool(True)^5,4)
    def test_54_rand(self):      self.assertEqual(5&SyncBool(True),1)
    def test_55_ror(self):       self.assertEqual(4|SyncBool(False),4)
    def test_56_rxor(self):      self.assertEqual(1^SyncBool(True),0)
    def test_57_invert_true(self): self.assertEqual(~SyncBool(True),-2)
    def test_58_inplace_and(self):
        s=SyncBool(True); s&=0;  self.assertFalse(s.get())
    def test_59_inplace_or(self):
        s=SyncBool(False); s|=1; self.assertTrue (s.get())
    def test_60_inplace_xor(self):
        s=SyncBool(True);  s^=1; self.assertFalse(s.get())

    # endregion
    # region — concurrency (66-75)
    # ----------------------------------------------------------
    def test_66_many_threads_toggle_even(self):
        sb=SyncBool(False)
        _many_threads(lambda:_toggle_n(sb,2_000),64)
        self.assertFalse(sb.get())

    def test_67_many_threads_toggle_odd(self):
        sb = SyncBool(False)
        flips_per_thread = 1_001
        num_threads = 32
        total_flips = flips_per_thread * num_threads
        _many_threads(lambda: _toggle_n(sb, flips_per_thread), num_threads)
        self.assertEqual(sb.get(), bool(total_flips % 2))
    def test_68_deadlock_free_binary_op(self):
        a,b=SyncBool(True),SyncBool(False)
        def worker(): _=a&b; _=b|a
        _many_threads(worker,128)
    def test_69_contention_get_set(self):
        sb=SyncBool(False)
        def writer(): sb.set(True); sb.set(False)
        def reader(): _=sb.get()
        _many_threads(writer,32); _many_threads(reader,32)
        self.assertIn(sb.get(),[True,False])
    def test_70_visible_toggle(self):
        sb=SyncBool(False); seen=[False]
        def reader():
            for _ in range(1000):
                if sb.get():
                    seen[0]=True; break
        t1=threading.Thread(target=_toggle_n,args=(sb,999))
        t2=threading.Thread(target=reader)
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertTrue(seen[0])

    # endregion
    # region — serialization & copy (76-85)
    # ----------------------------------------------------------
    def test_76_copy_independent(self):
        s1=SyncBool(True); s2=pickle.loads(pickle.dumps(s1))
        s1.set(False);                       self.assertTrue(s2.get())
    def test_77_shallow_copy(self):
        import copy; s1=SyncBool(True); s2=copy.copy(s1)
        self.assertIsInstance(s2,SyncBool)
    def test_78_deep_copy(self):
        import copy; s1=SyncBool(True); s2=copy.deepcopy(s1)
        self.assertIsInstance(s2,SyncBool)
    def test_79_pickle_cross_process(self):
        parent,child=mp.Pipe(); sb=SyncBool(True)
        p=mp.Process(target=_child,args=(child,sb)); p.start()
        recv=parent.recv(); p.join()
        self.assertIsInstance(recv,SyncBool); self.assertTrue(recv.get())
    def test_80_pickle_lock_is_fresh(self):
        s1=SyncBool(True); s2=pickle.loads(pickle.dumps(s1))
        self.assertIsNot(s1._lock,s2._lock)

    # endregion
    # region — g.c. / memory (86-90)
    # ----------------------------------------------------------
    def test_86_gc_no_leak(self):
        gc.collect(); before=len(gc.get_objects())
        for _ in range(10_000): SyncBool()
        gc.collect(); after=len(gc.get_objects())
        self.assertLess(after,before+500)
    def test_87_many_instances_slots(self):
        arr=[SyncBool(True) for _ in range(10_000)]
        self.assertFalse(hasattr(arr[0],'__dict__'))
    def test_88_lock_unique(self):
        a,b=SyncBool(),SyncBool()
        self.assertIsNot(a._lock,b._lock)
    def test_89_format_binary(self):
        self.assertEqual(format(SyncBool(True),"b"),"1")
    def test_90_fraction_interop(self):
        self.assertEqual(Fraction(1,2)+SyncBool(True),Fraction(3,2))

    # endregion
    # region — oddball / misc (91-100+)
    # ----------------------------------------------------------
    def test_91_eq_object(self):
        self.assertFalse(SyncBool(True)==object())
    def test_92_hash_in_set(self):
        s=set([SyncBool(True),SyncBool(True)]); self.assertEqual(len(s),1)
    def test_93_as_key_dict(self):
        d={SyncBool(True):"yes"}; self.assertEqual(d[SyncBool(True)],"yes")
    def test_94_pow_negative_exp(self):
        self.assertEqual(SyncBool(True)**-1,1)
    def test_95_rpow_zero_zero(self):
        self.assertEqual(0**SyncBool(False),1)
    def test_96_unwrap_decimal(self):
        sb=SyncBool(True); self.assertEqual(sb._unwrap_other(Decimal("2.5")),Decimal("2.5"))
    def test_97_unwrap_numeric_str(self):
        sb=SyncBool(True); self.assertEqual(sb._unwrap_other("3.14"),3.14)
    def test_98_unwrap_str_non_numeric(self):
        sb=SyncBool(True); self.assertEqual(sb._unwrap_other("hello"),"hello")
    def test_99_infinite_loop_safe_toggle(self):
        sb=SyncBool(False)
        for _ in range(1_000): sb.toggle()
        self.assertEqual(sb.get(), bool(1_000%2))
    def test_100_large_arithmetic_chain(self):
        sb=SyncBool(True)
        res=((sb+2)*3-4)/2
        self.assertEqual(res,((1+2)*3-4)/2)


# ──────────────────────────────────────────────────────────────
if __name__=="__main__":
    mp.set_start_method("spawn",force=True)
    unittest.main()
