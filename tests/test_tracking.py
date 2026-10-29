import unittest

from people_counter.tracking import PeopleCounter


def box_at(cx: int, cy: int) -> tuple[int, int, int, int]:
    return (cx - 10, cy - 20, 20, 40)


class PeopleCounterTests(unittest.TestCase):
    def test_crossing_with_dead_zone_counts_once(self):
        counter = PeopleCounter(margin=5)
        events = []
        for y in (25, 45, 49, 51, 55, 60, 65):
            events += counter.update([box_at(50, y)], (100, 100))
        self.assertEqual([(e.track_id, e.direction) for e in events], [(1, "entry")])
        self.assertEqual((counter.entries, counter.exits), (1, 0))
        self.assertEqual(counter.tracks[1].last_direction, "entry")

    def test_reverse_crossing_is_exit(self):
        counter = PeopleCounter(orientation="vertical", margin=2)
        counter.update([box_at(80, 50)], (100, 100))
        events = counter.update([box_at(30, 50)], (100, 100))
        self.assertEqual([e.direction for e in events], ["exit"])
        self.assertEqual(counter.tracks[1].last_direction, "exit")

    def test_direction_color_state_changes_after_recrossing(self):
        counter = PeopleCounter(margin=2)
        counter.update([box_at(50, 20)], (100, 100))
        self.assertIsNone(counter.tracks[1].last_direction)
        counter.update([box_at(50, 80)], (100, 100))
        self.assertEqual(counter.tracks[1].last_direction, "entry")
        counter.update([box_at(50, 20)], (100, 100))
        self.assertEqual(counter.tracks[1].last_direction, "exit")

    def test_missing_track_expires_and_cannot_create_false_crossing(self):
        counter = PeopleCounter(max_missed=1)
        counter.update([box_at(50, 20)], (100, 100))
        counter.update([], (100, 100))
        counter.update([], (100, 100))
        events = counter.update([box_at(50, 80)], (100, 100))
        self.assertEqual(events, [])

    def test_two_tracks_remain_distinct(self):
        counter = PeopleCounter(max_distance=30)
        counter.update([box_at(20, 20), box_at(80, 80)], (100, 100))
        counter.update([box_at(20, 40), box_at(80, 60)], (100, 100))
        events = counter.update([box_at(20, 65), box_at(80, 35)], (100, 100))
        self.assertEqual(sorted(e.direction for e in events), ["entry", "exit"])


if __name__ == "__main__":
    unittest.main()
