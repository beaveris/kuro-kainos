import unittest

from location import distance_km, validate_location


class LocationTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(validate_location(dict(lat=54.7, lon=25.3, accuracy=15))['lat'], 54.7)
        for value in [None, {}, dict(lat=91, lon=25, accuracy=1),
                      dict(lat=54, lon=float('nan'), accuracy=1),
                      dict(lat=54, lon=25, accuracy=-1)]:
            self.assertIsNone(validate_location(value))

    def test_distance(self):
        self.assertEqual(distance_km(54.7, 25.3, 54.7, 25.3), 0)
        # Vilnius to Kaunas is approximately 92 km in a straight line.
        self.assertAlmostEqual(distance_km(54.6872, 25.2797, 54.8985, 23.9036), 91.9, delta=1)
        self.assertAlmostEqual(distance_km(54, 25, 55, 24), distance_km(55, 24, 54, 25))


if __name__ == '__main__':
    unittest.main()
