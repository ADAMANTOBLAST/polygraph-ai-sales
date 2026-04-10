"""
Проверка round-robin: N менеджеров, много лидов — равномерно и по кругу.
Запуск: python3 -m unittest tests.test_manager_router_rr -v
"""
from __future__ import annotations

import unittest


def simulate_rr_pick(ids: list[int], lead_rr_idx_start: int, num_leads: int) -> tuple[list[int], int]:
    """
    Та же формула, что в pick_account_for_new_lead (manager_router.py):
    idx = lead_rr_idx % len(ids); следующий lead_rr_idx = idx + 1
    """
    ids = sorted({int(x) for x in ids})
    n = len(ids)
    if n == 0:
        return [], lead_rr_idx_start
    out: list[int] = []
    rr = lead_rr_idx_start
    for _ in range(num_leads):
        idx = int(rr) % n
        out.append(ids[idx])
        rr = idx + 1
    return out, rr


class TestRoundRobin(unittest.TestCase):
    def test_five_managers_sixty_leads_equal_split(self):
        ids = [2, 12, 13, 14, 16]
        picks, _ = simulate_rr_pick(ids, 0, 60)
        counts = {a: picks.count(a) for a in ids}
        self.assertEqual(set(counts.values()), {12}, "Каждый из 5 менеджеров должен получить ровно 12 лидов")
        # Первые 5 по кругу
        self.assertEqual(picks[:5], [2, 12, 13, 14, 16])
        self.assertEqual(picks[5:10], [2, 12, 13, 14, 16])

    def test_three_managers_ten_leads_cycles(self):
        ids = [10, 20, 30]
        picks, _ = simulate_rr_pick(ids, 0, 10)
        expected = [10, 20, 30] * 3 + [10]
        self.assertEqual(picks, expected)

    def test_wrap_after_last(self):
        ids = [1, 2]
        picks, _ = simulate_rr_pick(ids, 0, 4)
        self.assertEqual(picks, [1, 2, 1, 2])


if __name__ == "__main__":
    unittest.main()
